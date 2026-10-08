import unittest
import json
import tempfile
from pathlib import Path
from shapely.geometry import box,Point,mapping,Polygon
from voxel_mapper.park_paving import NearbyMaterials,emit_paving
from voxel_mapper.paving_palette import palette_block,material_label,PALETTES
from voxel_mapper.park_paving_plans import align_shared_labels,control_labels
from voxel_mapper.bedrock import ALLOWED_MATERIALS,material_block,export_world


def feature(polygon,surface='brick',status='contained_native_floor_label',fid='plan'):
    return {'type':'Feature','id':fid,'geometry':mapping(polygon),'properties':{
        'kind':'plaza','surface':surface,'material_status':status,'document_id':'drawing-hash'}}


class ParkPavingTests(unittest.TestCase):
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
