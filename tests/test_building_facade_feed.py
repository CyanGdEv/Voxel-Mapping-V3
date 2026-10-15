import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import Polygon, box, mapping, shape

from voxel_mapper.building_facade_feed import VERSION,normalize_region,region_study,prepare


class FacadeFeedTests(unittest.TestCase):
    def record(self,sha='a'*64):
        polygon=Polygon([(30,40),(130,40),(130,140),(30,140)],
            holes=[[(60,70),(100,70),(100,110),(60,110)]])
        return {'document_sha256':sha,'page':1,'number':2,'component_class_candidate':'wall_face',
            'raster_contrast_boundary_review':{'status':'unverified_contrast_boundary_candidate','geometry':mapping(polygon)},
            'drawing_view_candidate':{'view_key_candidate':['2967',26,1],
                'bearing_label_candidate':'SE','nominal_metres_per_pdf_point_candidate':.035277777777777776}}

    def source(self,root):
        doc=pymupdf.open();doc.new_page(width=400,height=300);data=doc.tobytes();doc.close()
        (root/'source.pdf').write_bytes(data);sha=hashlib.sha256(data).hexdigest()
        return sha,{'version':VERSION,'buildings':[{'building_id':'shop','revision_scope':'declared revision A',
            'sources':[{'path':'source.pdf','sha256':sha,'drawing_number':'2967-26'}]}]}

    def fake_faces(self,sha):
        def run(documents,output,**kwargs):
            root=Path(output);root.mkdir()
            accepted=self.record(sha);rejected=copy.deepcopy(accepted)
            rejected['raster_contrast_boundary_review']['status']='withheld_contrast_mixed_material_anchors'
            (root/'face-associations.jsonl').write_text(json.dumps(accepted)+'\n'+json.dumps(rejected)+'\n')
            return {'pages':[],'view_link_statuses':{},
                'raster_contrast_statuses':{'unverified_contrast_boundary_candidate':1,
                    'withheld_contrast_mixed_material_anchors':1}}
        return run

    def test_native_conversion_rotation_holes_and_original_record_unchanged(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=300);record=self.record();before=copy.deepcopy(record)
        try:
            normalized=normalize_region(record,page)
            self.assertEqual(shape(normalized['geometry']).bounds,(30,160,130,260))
            self.assertEqual(normalized['interior_ring_candidates'],1)
            self.assertIsNone(normalized['physical_opening_count']);self.assertEqual(record,before)
            page.set_rotation(90);rotated=normalize_region(record,page)
            self.assertEqual(normalized['geometry'],rotated['geometry']);self.assertEqual(page.rotation,90)
            self.assertNotEqual(normalized['display_geometry'],rotated['display_geometry'])
            rejected=copy.deepcopy(record);rejected['raster_contrast_boundary_review']['status']='withheld'
            self.assertIsNone(normalize_region(rejected,page))
        finally:doc.close()

    def test_nominal_region_mesh_preserves_hole_area_and_unknown_roles(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=300)
        try:
            row=normalize_region(self.record(),page);spec,model=region_study('source-view',[row])
            mesh=model['components'][0]['mesh'];area=0
            for triangle in mesh['triangles']:
                points=[mesh['vertices'][i] for i in triangle]
                area+=Polygon([(p[0],p[2]) for p in points]).area
            self.assertAlmostEqual(area,8400*row['nominal_metres_per_pdf_point_candidate']**2)
            self.assertEqual(spec['sources'][0]['state'],'unknown')
            self.assertEqual(spec['components'][0]['role'],'detail');self.assertFalse(mesh['watertight'])
            self.assertFalse(spec['acceptance']['physical_identity_verified'])
            second=copy.deepcopy(row);second['view_key_candidate'][-1]=2
            with self.assertRaises(ValueError):region_study('mixed',[row,second])
        finally:doc.close()

    def test_cli_preview_source_queue_and_deterministic_replay(self):
        from voxel_mapper.building_pipeline import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha,config=self.source(root)
            (root/'config.json').write_text(json.dumps(config))
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run',side_effect=self.fake_faces(sha)),\
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run',return_value={'results':[]}):
                with redirect_stdout(StringIO()):main(['discover-facades','--config',str(root/'config.json'),'--output',str(root/'out')])
                r=prepare(config,lambda p:root/p,root/'again')
            first=json.loads((root/'out/report.json').read_text());self.assertEqual(first,r)
            self.assertEqual(first['region_preview_specs_generated'],1)
            self.assertEqual(first['complete_building_specs_generated'],0)
            self.assertEqual(first['training_labels_generated'],0)
            self.assertEqual((root/'out/building-0000/region-view-0000/model.glb').read_bytes(),
                (root/'again/building-0000/region-view-0000/model.glb').read_bytes())
            queue=json.loads((root/'out/source-review-queue.json').read_text());self.assertEqual(queue['review_outcomes_generated'],0)
            with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'out')

    def test_adjacent_review_channel_keeps_raw_withholding_and_native_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha,config=self.source(root)
            def faces(documents,output,**kwargs):
                report=self.fake_faces(sha)(documents,output,**kwargs)
                path=Path(output)/'face-associations.jsonl'
                record=self.record(sha)
                record['raster_region_review']={'artwork_review_window_ids':['window']}
                path.write_text(json.dumps(record)+'\n')
                report['pages']=[{'document_sha256':sha,'page':1,'raster_review':{'atlas':{
                    'artwork_review_windows':[{'id':'window','bbox_page_points':[20,20,150,150]}]}}}]
                return report
            def scans(gray,**kwargs):
                if not kwargs:return {'status':'scan_budget_withheld','candidates':[]}
                return {'status':'jamb_head_correspondence_candidates_only',
                    'candidates':[{'bounds_pixels':[30,30,80,100],'physical_opening_verified':False}]}
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run',side_effect=faces),\
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run',return_value={'results':[]}),\
                 patch('voxel_mapper.building_facade_feed.scan',side_effect=scans):
                report=prepare(config,lambda p:root/p,root/'out')
            self.assertEqual(report['buildings'][0]['status'],'awaiting_facade_interpretation',report)
            row=json.loads((root/'out/building-0000/opening-candidates.json').read_text())['views'][0]
            self.assertEqual(row['scan']['candidates'],[])
            candidate=row['adjacent_bay_review_scan']['candidates'][0]
            self.assertEqual(candidate['coordinate_frame'],'pdf_native_points_y_up')
            self.assertIn('source_png_sha256',candidate)
            self.assertFalse(row['adjacent_bay_candidates_are_complete_openings'])

    def test_invalid_source_isolation_and_no_publication_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha,config=self.source(root);bad=copy.deepcopy(config['buildings'][0]);bad['building_id']='bad'
            bad['sources'][0]['sha256']='f'*64;config['buildings'].insert(0,bad)
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run',side_effect=self.fake_faces(sha)),\
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run',return_value={'results':[]}):
                report=prepare(config,lambda p:root/p,root/'out')
            self.assertEqual(report['buildings'][0]['status'],'invalid_facade_source_input')
            self.assertEqual(report['buildings'][1]['region_preview_specs_generated'],1)
            self.assertFalse((root/'out/building-0000').exists())
            config['buildings'].pop(0)
            def mutate(*args,**kwargs):
                (root/'source.pdf').write_bytes(b'changed');return {'results':[]}
            with patch('voxel_mapper.building_facade_feed.drawing_faces.run',side_effect=self.fake_faces(sha)),\
                 patch('voxel_mapper.building_facade_feed.plan_elevation_edges.run',side_effect=mutate):
                report=prepare(config,lambda p:root/p,root/'mutated')
            self.assertEqual(report['region_preview_specs_generated'],0)
            self.assertFalse((root/'mutated/building-0000').exists())

    def test_scope_and_source_contract_reject_acceptance_bypasses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,config=self.source(root)
            for extra in ({'world_placement_eligible':True},{'revision_scope':''}):
                bad=copy.deepcopy(config);bad['buildings'][0].update(extra)
                with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')
            for value in (26,'other-project',None):
                bad=copy.deepcopy(config);bad['buildings'][0]['sources'][0]['drawing_number']=value
                with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')


if __name__=='__main__':unittest.main()
