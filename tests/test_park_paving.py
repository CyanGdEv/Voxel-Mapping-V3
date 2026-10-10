import unittest
import json
import tempfile
from pathlib import Path
from shapely.geometry import box,Point,mapping,Polygon,shape
from voxel_mapper.park_paving import NearbyMaterials,emit_paving,protected_record,paving_extensions,plaza_coverage
from voxel_mapper.paving_palette import palette_block,material_label,PALETTES
from voxel_mapper.park_paving_plans import align_shared_labels,control_labels,cached_paving_faces,scale_bar_regions
from voxel_mapper.bedrock import ALLOWED_MATERIALS,material_block,export_world


def feature(polygon,surface='brick',status='contained_native_floor_label',fid='plan'):
    return {'type':'Feature','id':fid,'geometry':mapping(polygon),'properties':{
        'kind':'plaza','surface':surface,'material_status':status,'document_id':'drawing-hash'}}


class ParkPavingTests(unittest.TestCase):
    def test_multi_page_landscape_inspection_preserves_page_provenance(self):
        import hashlib
        import pymupdf
        from unittest.mock import patch
        from voxel_mapper.park_paving_plans import recover_park_plans
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'files').mkdir()
            pdf=pymupdf.open();pdf.new_page();pdf.new_page()
            payload=pdf.tobytes();pdf.close();digest=hashlib.sha256(payload).hexdigest()
            (root/'files'/f'{digest}.pdf').write_bytes(payload)
            entry={'sha256':digest,'title':'Existing Landscape','role':'landscape-plan',
                   'applicationReference':'SMD/2024/0579','application_context':'Alton Towers, Farley Lane',
                   'url':'https://publicaccess.staffsmoorlands.gov.uk/example'}
            registration={'document_id':digest,'status':'shop_track_alignment_hypothesis',
                          'candidate':{'scale_m_per_pdf_point':1,'rotation':[[1,0],[0,1]],
                                       'translation_epsg27700_m':[0,0]}}
            (root/'wicker-man-registration.json').write_text(json.dumps(registration))
            catalogue=json.dumps({'entries':[entry]});read=Path.read_text
            def read_source(path,*args,**kwargs):
                if path.name=='alton-planning-catalogue.json':return catalogue
                return read(path,*args,**kwargs)
            with patch('voxel_mapper.park_paving_plans.ANCHOR',digest),patch.object(Path,'read_text',read_source):
                collection,audit=recover_park_plans(root,root,root/'output','EPSG:27700')
            self.assertEqual(audit['inspected_documents'],1)
            self.assertEqual(audit['inspected_pages'],2)
            self.assertEqual([d['page'] for d in audit['documents']],[1,2])
            self.assertTrue(all(d['document_id']==digest for d in audit['documents']))
            self.assertEqual(audit['documents'][1]['status'],'unregistered')
            self.assertEqual(collection['features'],[])

    def test_scale_bar_cannot_close_a_landscape_face(self):
        labels=[{'text':str(i*100),'origin':[i*200,100],
                 'bbox':[i*200,80,i*200+30,105]} for i in range(6)]
        labels+=[{'text':'178.30','origin':[150,100],'bbox':[150,97,170,101]},
                 {'text':'2','origin':[500,100],'bbox':[500,97,504,101]}]
        regions=scale_bar_regions(labels)
        self.assertEqual(len(regions),1)
        self.assertTrue(box(100,0,800,120).boundary.intersects(regions[0]))
        self.assertFalse(box(100,0,200,20).boundary.intersects(regions[0]))
        self.assertEqual(scale_bar_regions(labels[1:]),[])

    def test_interrupted_geometry_cache_is_rebuilt_then_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'faces.json.gz';path.write_bytes(b'\x1f\x8b')
            expected={'polygons':[{'geometry':mapping(box(0,0,1,1))}]}
            result=cached_paving_faces(path,lambda:expected['polygons'])
            self.assertEqual(json.loads(json.dumps(result)),json.loads(json.dumps(expected)))
            self.assertEqual(cached_paving_faces(path,lambda:self.fail('cache was not reused')),json.loads(json.dumps(expected)))
            self.assertFalse(path.with_suffix('.gz.tmp').exists())

    def test_plaza_coverage_detects_missing_and_wrong_material_cells(self):
        f=feature(box(0,0,2,2),fid='planning-paving/wicker/1')
        f['properties']['contained_labels']=['Plaza']
        rows=[{'x':0,'z':0,'surface':'brick'},{'x':0,'z':1,'surface':'stone'}]
        self.assertEqual(plaza_coverage([f],rows),[{'feature':f['id'],'footprint_cells':4,
                         'brick_cells':1,'missing_cells':2,'wrong_material_cells':1}])

    def test_reviewed_cbeebies_corridors_keep_provenance_and_material_unknown(self):
        from pyproj import Transformer
        rows,audit=paving_extensions(Transformer.from_crs(4326,27700,always_xy=True).transform)
        self.assertEqual(len(rows),4)
        self.assertTrue(audit['withheld_sources'])
        self.assertTrue(all(not f['properties']['registration_verified'] for f in rows))
        self.assertTrue(all(f['properties']['material_status']=='paving_label_unspecified_material' for f in rows))
        self.assertEqual(NearbyMaterials(rows).features,[])
        self.assertTrue(all(100<shape(f['geometry']).area<2000 for f in rows))

    def test_legacy_paving_can_be_repainted_without_unlocking_ride_or_air_cells(self):
        r={'kind':'structure','source':'wicker-estimated-reconstruction',
           'feature':'reconstruction/proposed_plaza_paving','material':'stone_bricks'}
        self.assertFalse(protected_record(r))
        self.assertTrue(protected_record({**r,'material':'air'}))
        self.assertTrue(protected_record({**r,'feature':'reconstruction/track_ties'}))
        self.assertTrue(protected_record({**r,'source':'other'}))

    def test_user_plaza_assignment_covers_whole_footprint_and_matching_osm(self):
        plaza=feature(box(0,0,20,20),status='user_material_assignment')
        osm=feature(box(1,1,21,21),'stone',fid='osm/plaza')
        rows,report=emit_paving([osm],[plaza],lambda x,z:100,box(-5,-5,25,25),Polygon())
        self.assertTrue(all(r['surface']=='brick' for r in rows))
        self.assertEqual(sum(r['material_origin']=='user_material_assignment' for r in rows),400)
        self.assertTrue(any(r['material_origin']=='nearby_user_material_estimate' for r in rows))

    def test_nearby_transfer_is_metric_and_bounded(self):
        matcher=NearbyMaterials([feature(box(0,0,10,10))],2)
        self.assertEqual(matcher.match(Point(11.9,5))['surface'],'brick')
        self.assertIsNone(matcher.match(Point(12.1,5)))
        self.assertAlmostEqual(matcher.match(Point(11,5))['distance_m'],1)

    def test_unknown_paving_never_donates_an_invented_material(self):
        matcher=NearbyMaterials([feature(box(0,0,10,10),status='unspecified_paving_approximation')])
        self.assertIsNone(matcher.match(Point(5,5)))
        self.assertIsNone(material_label('brick wall 0.50 ht'))
        self.assertEqual(material_label('block paving'),'paving_stones')

    def test_similar_polygon_inherits_material_for_whole_footprint(self):
        matcher=NearbyMaterials([feature(box(0,0,10,10))],2)
        result=matcher.match_geometry(box(1,1,11,11))
        self.assertEqual(result['surface'],'brick')
        self.assertEqual(result['method'],'close_footprint_match')
        self.assertIsNone(matcher.match_geometry(box(1,1,101,11)))

    def test_conflicting_equally_close_materials_remain_unresolved(self):
        matcher=NearbyMaterials([feature(box(0,0,10,10)),feature(box(0,0,10,10),'asphalt',fid='other')])
        self.assertEqual(matcher.match(Point(5,5))['status'],'ambiguous_material_proximity')

    def test_long_path_only_inherits_locally_and_masks_survive(self):
        path=feature(box(0,0,30,3),'asphalt',fid='osm/path');path['properties']['kind']='path'
        planning=feature(box(0,0,5,3))
        rows,r=emit_paving([path],[planning],lambda x,z:100,box(-5,-5,40,20),box(10,0,12,3),2)
        by={(x['x'],x['z']):x for x in rows}
        self.assertEqual(by[6,1]['surface'],'brick')
        self.assertEqual(by[20,1]['surface'],'asphalt')
        self.assertNotIn((10,1),by)
        self.assertEqual(len(rows),len({(x['x'],x['y'],x['z']) for x in rows}))
        self.assertTrue(all(x['y']==100 for x in rows))

    def test_holes_and_missing_terrain_remain_empty(self):
        p=Polygon([(0,0),(8,0),(8,8),(0,8)],holes=[[(2,2),(6,2),(6,6),(2,6)]])
        rows,r=emit_paving([],[feature(p)],lambda x,z:None if x<1 else 99,box(-1,-1,9,9),Polygon())
        self.assertFalse(any(2<=x['x']<6 and 2<=x['z']<6 for x in rows))
        self.assertFalse(any(x['x']==0 for x in rows))

    def test_all_palettes_export_supported_stable_blocks(self):
        for surface,p in PALETTES.items():
            for x in range(-20,20):
                for z in range(-3,3):
                    block=palette_block(surface,x,z)
                    self.assertIn(block,ALLOWED_MATERIALS)
                    self.assertEqual(block,palette_block(surface,x,z))
        self.assertEqual(material_block('red_terracotta').base_name,'stained_terracotta')

    def test_shared_native_labels_recover_similarity_with_outlier(self):
        local={f'CK{i:02}':[float(i%4)*100,float(i//4)*100] for i in range(12)}
        reference={k:[400000+v[0]*.1,340000-v[1]*.1] for k,v in local.items()}
        reference['CK11']=[420000,350000]
        result=align_shared_labels(local,reference)
        self.assertIsNotNone(result)
        self.assertFalse(result['registration_verified'])
        self.assertEqual(len(result['matched_labels']),11)
        self.assertLess(result['max_withheld_residual_m'],.001)
        self.assertIsNone(align_shared_labels({'CK00':[0,0]},reference))

    def test_duplicate_survey_labels_are_not_controls(self):
        labels=[{'text':'CK01','origin':[0,0]},{'text':'CK01','origin':[10,0]},
                {'text':'CK02','origin':[0,10]},{'text':'tarmac','origin':[2,2]}]
        self.assertEqual(control_labels(labels),{'CK02':[0,10]})

    def test_every_palette_block_survives_actual_bedrock_export(self):
        blocks=sorted({b for p in PALETTES.values() for b in p['blocks']})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);voxels=root/'voxels.jsonl'
            records=[{'x':i,'y':100,'z':0,'kind':'path','material':b} for i,b in enumerate(blocks)]
            voxels.write_text(''.join(json.dumps(r)+'\n' for r in records))
            report=export_world(voxels,root,{'voxel_size_m':1},max_blocks=100)
            self.assertEqual(report['composed_blocks'],len(blocks))
            import amulet
            level=amulet.load_level(str(root/'bedrock-world'))
            try:
                for i,b in enumerate(blocks):
                    chunk=level.get_chunk(i//16,0,'minecraft:overworld')
                    self.assertEqual(chunk.block_palette[int(chunk.blocks[i%16,64,0])],material_block(b))
            finally:level.close()


if __name__=='__main__':unittest.main()
