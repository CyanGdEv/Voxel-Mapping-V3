import copy
import unittest
import test_architectural_view_layout as fixtures
from voxel_mapper.architectural_graph import build
from voxel_mapper.architectural_view_layout import review as layout_review
from voxel_mapper.architectural_linework_frames import review
from voxel_mapper.drawing_geometry import extract_page

class LineworkFramesTests(unittest.TestCase):
    def test_exact_frame_preserves_source_and_crossings(self):
        doc,page,parents,graph=fixtures.ViewLayoutTests().source()
        try:
            page.draw_rect((10,10,260,220));page.draw_line((240,100),(290,100))
            parents,_=extract_page(page,'f'*64,1,min_line_length_points=.25,max_candidates=10000)
            graph=build(parents);layout=layout_review(page,'f'*64,1,graph);before=copy.deepcopy(graph)
            result=review(graph,layout)
            self.assertEqual(result['counts']['closed_source_frame_caption_candidate'],1)
            self.assertTrue(any(m['status']=='frame_boundary_crossing' for r in result['frames'] for m in r['component_membership']))
            self.assertEqual(graph,before);self.assertFalse(result['view_scope_verified'])
            self.assertEqual(result['world_geometry_additions'],0)
            limited=review(graph,layout,max_checks=1)
            self.assertEqual(limited['frames'],[])
            with self.assertRaises(ValueError):review(graph,layout,max_checks=True)
        finally:doc.close()

    def test_nested_frames_compete_and_open_lines_do_not_close(self):
        doc,page,parents,graph=fixtures.ViewLayoutTests().source()
        try:
            page.draw_rect((10,10,260,220));page.draw_rect((5,5,270,225))
            parents,_=extract_page(page,'f'*64,1,min_line_length_points=.25,max_candidates=10000)
            graph=build(parents);layout=layout_review(page,'f'*64,1,graph)
            result=review(graph,layout)
            self.assertEqual(result['counts']['competing_source_frames'],2)
            broken=copy.deepcopy(graph);broken['page']=2
            with self.assertRaises(ValueError):review(broken,layout)
        finally:doc.close()
