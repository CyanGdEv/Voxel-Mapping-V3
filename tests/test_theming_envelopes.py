"""Layered theming labels are not solid buildings or guessed queue routes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import planning_theming_notes as notes,planning_plan_markings as markings,planning_geometry_world as world
from voxel_mapper.building_spec import digest
from tests.test_planning_plan_markings import source_fixture
from tests.test_planning_geometry_world import inputs,request


def layered_fixture(sha=None):
    document,preset=source_fixture(sha)
    page=document[0];first=len(page.get_drawings())
    page.draw_circle((180,200),45,fill=(1,1,1),fill_opacity=.5,color=None)
    page.draw_circle((300,200),35,fill=(1,1,1),fill_opacity=.7,color=None)
    for i,line in enumerate(('Theming','Envelope 1','to 195.8','with','queuing','below')):
        page.insert_text((158,175+i*8),line,fontsize=7)
    for i,line in enumerate(('Theming','Envelope 2','to 196.8')):
        page.insert_text((278,190+i*8),line,fontsize=7)
    preset['source_content_sha256']=hashlib.sha256(page.read_contents()).hexdigest()
    a={'trace_indices':list(range(6))};b={'trace_indices':list(range(6,9))}
    preset['features'] += [
        {'key':'envelope1','label':'Theming Envelope 1','role':'theming_envelope',
            'selector':{'ordinals':[first]},'annotation':a,'filled_boundary':True,'allow_source_curves':True,'source_fill_opacity':.5},
        {'key':'envelope2','label':'Theming Envelope 2','role':'theming_envelope',
            'selector':{'ordinals':[first+1]},'annotation':b,'filled_boundary':True,'allow_source_curves':True,'source_fill_opacity':page.get_drawings()[first+1]['fill_opacity']},
        {'key':'queue-note','label':'Queue below note','role':'queue_below_annotation','selector':{'annotation_anchor':5},'annotation':a}]
    records,_=markings._capture(page,preset)
    for spec,row in zip(preset['features'],records):
        spec['expected']={k:row[k] for k in ('geometry_sha256','source_paint_groups','source_paint_witnesses_sha256')}
        if 'semantic_evidence' in row:spec['expected']['source_annotation_sha256']=row['source_annotation_sha256']
    return document,preset


class ThemingEnvelopeTests(unittest.TestCase):
    def test_upper_limit_and_queuing_below_are_separate_semantics(self):
        for spelling in ('queuing','queueing'):
            r=notes.parse('Theming Envelope 1 to 195 .8 with '+spelling+' below')
            self.assertEqual(r['printed_upper_level'],195.8);self.assertTrue(r['queueing_below_stated'])
            self.assertFalse(r['upper_level_is_building_height']);self.assertIsNone(r['queue_floor_level'])
            self.assertIsNone(r['queue_route_geometry']);self.assertIsNone(r['queue_extent_geometry'])
            self.assertFalse(r['solid_building_footprint_authorized'])

    def test_second_envelope_does_not_inherit_first_queue_claim(self):
        r=notes.parse('Theming\nEnvelope 2\nto 196.8')
        self.assertEqual(r['printed_upper_level'],196.8);self.assertFalse(r['queueing_below_stated'])
        for text in ('Theming Envelope 1 height 195.8','Theming Envelope 1 to 195.8 with queuing above','Please see Theming Envelope 1 to 195.8'):
            self.assertIsNone(notes.parse(text))

    def test_original_translucent_curved_boundaries_retain_visible_note_proofs(self):
        document,preset=layered_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(document[0],preset['document_sha256'],1)
            self.assertTrue(r['analysis_complete'],r.get('reason'))
            envelopes=[x for x in r['records'] if x['role']=='theming_envelope']
            self.assertEqual(len(envelopes),2)
            self.assertTrue(envelopes[0]['semantic_evidence']['claim']['queueing_below_stated'])
            self.assertFalse(envelopes[1]['semantic_evidence']['claim']['queueing_below_stated'])
            self.assertEqual(envelopes[0]['curve_tolerance_pdf_points'],.05)
            self.assertEqual(r['records'][-1]['geometry_pdf_native']['type'],'Point')
        finally:document.close()

    def test_changed_relationship_and_hidden_note_cannot_authorize_markers(self):
        document,preset=layered_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(document[0],preset['document_sha256'],1)
                altered=copy.deepcopy(r);e=altered['records'][-3]['semantic_evidence']
                e['claim']['queue_floor_level']=183.5;e['source_annotation_sha256']=notes.source_digest(e)
                with self.assertRaises(ValueError):markings.validate_review(altered,preset['document_sha256'],1)
            document[0].draw_rect((150,165,205,225),fill=(1,1,1),color=None)
            with self.assertRaises(ValueError):notes.capture(document[0],list(range(6)))
        finally:document.close()

    def test_legacy_four_feature_reviews_remain_reloadable(self):
        old_doc,old_profile=source_fixture()
        try:
            with patch.object(markings,'profile',return_value=old_profile):old=markings.page_review(old_doc[0],old_profile['document_sha256'],1)
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'wicker-plan-markings-v1.json').write_text(json.dumps(old_profile))
                current=copy.deepcopy(old_profile);current['interpretation']='new revision'
                with patch.object(markings,'profile',return_value=current),patch.object(markings,'PROFILE_PATH',root/'current.json'):
                    markings.validate_review(old,old_profile['document_sha256'],1)
        finally:old_doc.close()

    def test_native_purple_envelopes_and_yellow_note_leave_interiors_unfilled(self):
        data=inputs();document,preset=layered_fixture(data['layout']['document_sha256'])
        try:
            with patch.object(markings,'profile',return_value=preset):
                data['markings']=markings.page_review(document[0],preset['document_sha256'],1)
                with tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary);r=world.run(request(root,data),root/'world')
                    cells=json.loads((root/'world/plan-marking-cells.json').read_text())
                    self.assertTrue({'purple_wool','yellow_wool'}<={x['material'] for x in cells})
                    self.assertEqual(sum(x['role']=='queue_below_annotation' for x in cells),1)
                    for key in ('envelope1','envelope2'):
                        self.assertEqual(r['plan_markings']['display_cells_by_feature'][key],r['plan_markings']['source_sample_cells_by_feature'][key])
                    self.assertFalse(r['plan_markings']['queue_route_generated'])
                    self.assertFalse(r['plan_markings']['queue_area_generated'])
                    self.assertEqual(r['reconstructed_buildings'],0)
                    self.assertTrue(r['saved_geometry_validation']['native_block_states_verified'])
                    self.assertTrue(r['archive_validation']['saved_world_reopened'])
                    claims=r['plan_markings']['theming_relationships']
                    self.assertTrue(claims['envelope1']['queueing_below_stated'])
                    self.assertFalse(claims['envelope2']['queueing_below_stated'])
        finally:document.close()


if __name__=='__main__':unittest.main()
