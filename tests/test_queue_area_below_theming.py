"""The user-identified circle is a queue floor area, not merely a note marker."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import Point,shape
from shapely.affinity import affine_transform

from voxel_mapper import planning_plan_markings as markings,planning_geometry_world as world
from tests.test_theming_envelopes import layered_fixture
from tests.test_planning_geometry_world import inputs,request


def queue_fixture(sha=None):
    doc,preset=layered_fixture(sha)
    spec=copy.deepcopy(preset['features'][-3]);spec.update(key='queue-floor',label='Queue area under Envelope 1',role='queue_area',filled_area=True,
        queue_area_context={'below_feature_key':'envelope1','extent_basis':'explicit_user_identification_of_white_circle',
            'geometry_source':'original Envelope 1 plan circle','internal_queue_lanes_verified':False,'entrance_positions_verified':False,
            'queue_floor_level':None,'physical_extent_verified':False})
    spec.pop('filled_boundary');preset['features'][-1]=spec
    records,_=markings._capture(doc[0],preset)
    for s,row in zip(preset['features'],records):
        s['expected']={k:row[k] for k in ('geometry_sha256','source_paint_groups','source_paint_witnesses_sha256')}
        if 'semantic_evidence' in row:s['expected']['source_annotation_sha256']=row['source_annotation_sha256']
    return doc,preset


class QueueAreaTests(unittest.TestCase):
    def test_circle_interior_is_paved_but_second_envelope_is_not(self):
        data=inputs();doc,preset=queue_fixture(data['layout']['document_sha256'])
        try:
            with patch.object(markings,'profile',return_value=preset):
                data['markings']=markings.page_review(doc[0],preset['document_sha256'],1)
                self.assertTrue(data['markings']['analysis_complete'],data['markings'].get('reason'))
                sampled=world.rasterize(data)
            affine=data['layout']['shared_frame']['native_to_nominal_local_affine']
            a=affine_transform(Point(180,200),affine);key=(math.floor(a.x),math.floor(a.y))
            self.assertEqual(sampled['ground'][key],'stone_bricks')
            self.assertEqual(sampled['plan_markers'][key]['role'],'queue_area')
            b=affine_transform(Point(300,200),affine);key2=(math.floor(b.x),math.floor(b.y))
            self.assertNotEqual(sampled['plan_markers'].get(key2,{}).get('role'),'queue_area')
            self.assertGreater(sampled['plan_marking_report']['display_cells_by_feature']['queue-floor'],10)
            self.assertTrue(sampled['plan_marking_report']['queue_area_generated'])
            self.assertFalse(sampled['plan_marking_report']['queue_route_generated'])
        finally:doc.close()

    def test_envelope_without_queue_below_claim_cannot_supply_queue_floor(self):
        doc,preset=queue_fixture()
        try:
            preset['features'][-1]['annotation']={'trace_indices':[6,7,8]}
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(doc[0],preset['document_sha256'],1)
            self.assertFalse(r['analysis_complete']);self.assertFalse(r['records'])
        finally:doc.close()

    def test_resigned_extent_or_queue_interpretation_is_rejected(self):
        doc,preset=queue_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(doc[0],preset['document_sha256'],1)
                altered=copy.deepcopy(r);altered['records'][-1]['queue_area_context']['below_feature_key']='envelope2'
                with self.assertRaises(ValueError):markings.validate_review(altered,preset['document_sha256'],1)
                altered=copy.deepcopy(r);altered['records'][-1]['geometry_pdf_native']['coordinates'][0][0][0]+=10
                with self.assertRaises(ValueError):markings.validate_review(altered,preset['document_sha256'],1)
        finally:doc.close()

    def test_native_queue_floor_is_saved_without_queue_lane_or_height_inference(self):
        data=inputs();doc,preset=queue_fixture(data['layout']['document_sha256'])
        try:
            with patch.object(markings,'profile',return_value=preset):
                data['markings']=markings.page_review(doc[0],preset['document_sha256'],1)
                with tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary);r=world.run(request(root,data),root/'world')
                    self.assertTrue(r['plan_markings']['queue_area_generated'])
                    self.assertFalse(r['plan_markings']['queue_route_generated'])
                    cells=json.loads((root/'world/plan-marking-cells.json').read_text())
                    floors=[x for x in cells if x['role']=='queue_area']
                    self.assertGreater(len(floors),10);self.assertTrue(all(x['material']=='stone_bricks' for x in floors))
                    self.assertFalse(any(x['role']=='queue_below_annotation' for x in cells))
                    self.assertTrue(r['saved_geometry_validation']['native_block_states_verified'])
                    self.assertTrue(r['archive_validation']['saved_world_reopened'])
                    self.assertIsNone(r['plan_markings']['queue_areas']['queue-floor']['queue_floor_level'])
                    self.assertEqual(r['reconstructed_buildings'],0)
        finally:doc.close()

    def test_previous_note_only_review_remains_reloadable(self):
        doc,old=layered_fixture()
        try:
            with patch.object(markings,'profile',return_value=old):review=markings.page_review(doc[0],old['document_sha256'],1)
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'wicker-plan-markings-v2.json').write_text(json.dumps(old))
                current=copy.deepcopy(old);current['interpretation']='queue area revision'
                with patch.object(markings,'profile',return_value=current),patch.object(markings,'PROFILE_PATH',root/'current.json'):
                    markings.validate_review(review,old['document_sha256'],1)
        finally:doc.close()


if __name__=='__main__':unittest.main()
