import unittest

from voxel_mapper.wicker_track import (ordered_route, bind_annotation, filled_ring_candidate,
                                       height_marker, reviewed_binding, REVIEW_DOCUMENT)


class WickerTrackTests(unittest.TestCase):
    def test_height_label_uses_crosshair_and_rejects_plain_support_circle(self):
        circle = {'seqno':123,'rect':[94.6,94.6,105.4,105.4],
                  'items':[['c',[0,0],[0,0],[0,0],[0,0]]]*4}
        horizontal = {'items':[['l',[91.4,100],[108.6,100]]]}
        vertical = {'items':[['l',[100,91.4],[100,108.6]]]}
        bbox = [108.5,82,180,98]
        self.assertIsNone(height_marker([circle],bbox))
        self.assertEqual(height_marker([horizontal,circle,vertical],bbox),
                         {'point_pdf':[100,100],'pdf_vector_sequence':123})
        self.assertIsNone(height_marker([horizontal,circle,vertical]*2,bbox))

    def test_crossing_review_is_document_scoped_and_retains_alternative(self):
        binding = {'status':'ambiguous_route_section','candidates':[
            {'station_m':775,'distance_m':.5},{'station_m':438,'distance_m':.8}]}
        self.assertIs(reviewed_binding(binding,'HP7','other-document'),binding)
        reviewed = reviewed_binding(binding,'HP7',REVIEW_DOCUMENT)
        self.assertEqual(reviewed['nearest_candidate']['station_m'],438)
        self.assertFalse(reviewed['as_built_verified'])
        self.assertEqual(len(reviewed['candidates']),2)

    def way(self, identifier, nodes, coords):
        return {'id': identifier, 'nodes': nodes, 'geometry': [{'lon': x, 'lat': y} for x,y in coords]}

    def test_way_reversal_preserves_closed_route_and_does_not_join_crossings(self):
        ways = [self.way(1,[1,2,3],[(0,0),(2,2),(4,0)]),self.way(2,[1,4,3],[(0,0),(2,-2),(4,0)])]
        route = ordered_route(ways, lambda x,y:(x,y))
        self.assertEqual(route['coordinates_wgs84'][0],route['coordinates_wgs84'][-1])
        self.assertEqual(len(route['segments']),4)
        self.assertEqual(route['ordered_way_ids'],[1,2])
        with self.assertRaises(ValueError):
            ordered_route(ways[:1],lambda x,y:(x,y))

    def test_nearest_branch_is_withheld_when_two_distant_route_sections_cross(self):
        route = {'route_length_m':100,'segments':[
            {'start':(-2,0),'end':(2,0),'station_start_m':0,'station_end_m':4,'way_id':1},
            {'start':(0,-2),'end':(0,2),'station_start_m':50,'station_end_m':54,'way_id':2}]}
        binding = bind_annotation((.1,.2),route)
        self.assertEqual(binding['status'],'ambiguous_route_section')
        self.assertEqual(len(binding['alternate_route_sections']),1)

    def test_filled_outline_can_close_implicitly_but_text_mask_and_open_stroke_cannot(self):
        drawing = {'type':'fs','fill':[1,1,1],'color':[.3,.2,.1],'stroke_opacity':.7,
                   'items':[['l',[0,0],[20,0]],['l',[20,0],[20,3]],['l',[20,3],[0,3]]]}
        self.assertIsNotNone(filled_ring_candidate(drawing,[8,1,12,2]))
        drawing['type']='s'
        self.assertIsNone(filled_ring_candidate(drawing,[8,1,12,2]))
        drawing['type']='fs'
        self.assertIsNone(filled_ring_candidate(drawing,[0,0,20,3]))
