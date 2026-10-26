"""Pinned source selections, open walls, projected crossing guides and native wool."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import LineString,MultiLineString,mapping

from voxel_mapper import planning_plan_markings as markings,planning_geometry_world as world
from voxel_mapper.building_spec import digest
from tests.test_planning_geometry_world import inputs,request


def source_fixture(sha=None):
    with pymupdf.open() as doc:
        page=doc.new_page(width=600,height=400)
        page.draw_rect((50,50,140,80),fill=(1,1,1))
        page.draw_polyline([(200,40),(200,100),(260,100)],color=(0,0,0),closePath=False)
        page.draw_polyline([(80,170),(350,170),(350,270),(80,270)],color=(.5,.3,.1),closePath=False)
        page.draw_polyline([(60,150),(370,150),(370,290),(60,290)],color=(.6,.4,.2),closePath=False)
        raw=doc.tobytes()
    document=pymupdf.open(stream=raw,filetype='pdf');page=document[0]
    preset={'version':'reviewed-wicker-marking-source-v1','origin':'source_review_for_user_marking_instruction',
        'document_sha256':sha or hashlib.sha256(raw).hexdigest(),'page':1,'source_content_sha256':hashlib.sha256(page.read_contents()).hexdigest(),
        'side_marking_offset_blocks':1,'side_offset_is_source_measurement':False,'features':[
            {'key':'games','label':'Games','role':'building_boundary','selector':{'ordinals':[0]},'filled_boundary':True},
            {'key':'toilets','label':'Toilets','role':'building_boundary','selector':{'ordinals':[1]}},
            {'key':'centre','label':'Track alignment','role':'track_centre','selector':{'ordinals':[2]}},
            {'key':'supports','label':'Support frame','role':'support_boundaries','selector':{'ordinals':[3]}}]}
    records,_=markings._capture(page,preset)
    for spec,row in zip(preset['features'],records):spec['expected']={k:row[k] for k in ('geometry_sha256','source_paint_groups','source_paint_witnesses_sha256')}
    return document,preset


class PlanMarkingTests(unittest.TestCase):
    def test_unreviewed_document_never_classifies_tracks_from_colour(self):
        document,preset=source_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(document[0],'f'*64,1)
            self.assertEqual(r['records'],[]);self.assertTrue(r['analysis_complete'])
        finally:document.close()

    def test_selected_native_markings_preserve_open_toilet_walls(self):
        document,preset=source_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(document[0],preset['document_sha256'],1)
                self.assertTrue(r['analysis_complete'],r.get('reason'));markings.validate_review(r,preset['document_sha256'],1)
            toilet=r['records'][1]['geometry_pdf_native']['coordinates']
            self.assertNotEqual(toilet[0],toilet[-1]);self.assertEqual(r['records'][2]['material'],'orange_wool')
            self.assertEqual(r['records'][3]['material'],'brown_wool');self.assertFalse(r['side_offset_is_source_measurement'])
        finally:document.close()

    def test_changed_original_or_resigned_geometry_is_rejected(self):
        document,preset=source_fixture()
        try:
            with patch.object(markings,'profile',return_value=preset):
                r=markings.page_review(document[0],preset['document_sha256'],1)
                altered=copy.deepcopy(r);altered['records'][2]['geometry_pdf_native']=mapping(LineString([(0,0),(1,1)]))
                altered['records'][2]['geometry_sha256']=digest(altered['records'][2]['geometry_pdf_native'])
                with self.assertRaises(ValueError):markings.validate_review(altered,preset['document_sha256'],1)
                document[0].draw_line((20,20),(30,30))
                self.assertFalse(markings.page_review(document[0],preset['document_sha256'],1)['analysis_complete'])
        finally:document.close()

    def test_grid_traversal_covers_negative_endpoints_and_reversal(self):
        for coordinates in ([(-3,-2),(3,4)],[(0,0),(3,0)],[(2,0),(2,-4)],[(1,1),(1,1)]):
            line=LineString(coordinates)
            a=set(markings.line_cells(line));b=set(markings.line_cells(LineString(coordinates[::-1])))
            self.assertEqual(a,b);self.assertTrue(a)
            self.assertLessEqual(len(a),20)

    def test_side_guides_keep_both_branches_at_projected_crossing(self):
        line=LineString([(0,0),(10,10),(0,10),(10,0)])
        guides=markings.side_lines(line)
        self.assertEqual(len(guides.geoms),10)
        self.assertGreater(guides.length,2*line.length)

    def test_work_quota_and_cancellation_do_not_return_partial_success(self):
        value={'records':[{'key':'track','role':'track_centre','material':'orange_wool','geometry_pdf_native':mapping(LineString([(1,1),(10,10)]))}],
            'profile_sha256':'a'*64,'side_marking_offset_blocks':1}
        with self.assertRaises(ValueError):markings.rasterize(value,lambda g:LineString(g['coordinates']),[0,0,20,20],max_steps=1)
        with self.assertRaises(CancelledError):list(markings.line_cells(LineString([(0,0),(1,1)]),cancelled=lambda:True))

    def test_native_world_retains_all_wool_colours_and_portable_source_pin(self):
        data=inputs();document,preset=source_fixture(data['layout']['document_sha256'])
        try:
            with patch.object(markings,'profile',return_value=preset):
                review=markings.page_review(document[0],preset['document_sha256'],1);data['markings']=review
                self.assertTrue(review['analysis_complete'],review.get('reason'))
                with tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary);config=request(root,data);r=world.run(config,root/'world')
                    self.assertTrue(r['saved_geometry_validation']['native_block_states_verified'])
                    self.assertTrue(r['archive_validation']['saved_world_reopened'])
                    self.assertGreater(r['plan_marking_cells'],0)
                    cells=json.loads((root/'world/plan-marking-cells.json').read_text())
                    self.assertTrue({'orange_wool','blue_wool','brown_wool'}<={row['material'] for row in cells})
                    self.assertEqual(hashlib.sha256((root/'world/source-markings.json').read_bytes()).hexdigest(),config['markings_sha256'])
        finally:document.close()


if __name__=='__main__':unittest.main()
