import copy
import unittest
from unittest.mock import patch
import pymupdf
from shapely.geometry import box,mapping
import test_linework_boundaries as fixtures
from voxel_mapper.architectural_interpretation import wall_bands
from voxel_mapper.wall_region_adjacency import review

class WallRegionAdjacencyTests(unittest.TestCase):
    def source(self):
        parents=fixtures.LineworkTests().parents([[(30,20),(30,90)],[(33,20),(33,90)]])
        bands,_=wall_bands(parents,.1)
        faces=[{'id':str(i),'document_sha256':'a'*64,'page':1,'coordinate_frame':'pdf_native_points_y_up',
                'geometry':mapping(g)} for i,g in enumerate([box(0,20,30,90),box(33,20,90,90),box(30,20,33,90)])]
        doc=pymupdf.open();page=doc.new_page(width=120,height=120)
        page.insert_text((5,60),'KITCHEN',fontsize=4);page.insert_text((40,60),'COURTYARD',fontsize=4)
        return doc,page,parents,faces,bands

    def test_opposite_labelled_regions_exclude_wall_strip_and_keep_source(self):
        doc,page,parents,faces,bands=self.source()
        try:
            before=copy.deepcopy([parents,faces,bands])
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                result=review(page,'a'*64,1,parents,faces,bands)
            self.assertEqual(result['counts']['room_to_outdoor_side_evidence'],1)
            sides=result['wall_adjacency'][0]['sides']
            self.assertEqual({r['face_id'] for s in sides for r in s['adjacent_regions']},{'0','1'})
            self.assertTrue(all(s['adjacent_regions'][0]['shared_length_pdf_points']==70 for s in sides))
            self.assertEqual([parents,faces,bands],before)
            unlabelled=doc.new_page(width=120,height=120);unlabelled.insert_text((5,60),'KITCHEN',fontsize=4)
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                partial=review(unlabelled,'a'*64,1,parents,faces,bands)
            self.assertEqual(partial['counts'],{'room_to_unlabelled_side_evidence':1})
            self.assertFalse(partial['wall_adjacency'][0]['exterior_wall_verified'])
            self.assertFalse(result['building_footprint_verified']);self.assertEqual(result['world_geometry_additions'],0)
        finally:doc.close()

    def test_hidden_competing_budget_and_wrong_contract_withhold(self):
        doc,page,parents,faces,bands=self.source()
        try:
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'withheld'}):
                result=review(page,'a'*64,1,parents,faces,bands)
                self.assertEqual(result['counts'],{'region_identity_unresolved':1})
            duplicate={**faces[0],'id':'another'}
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                result=review(page,'a'*64,1,parents,faces+[duplicate],bands)
                self.assertEqual(result['counts'],{'region_identity_unresolved':1})
                limited=review(page,'a'*64,1,parents,faces,bands,max_checks=1)
                self.assertEqual(limited['labels'],[]);self.assertEqual(limited['wall_adjacency'],[])
            bad=copy.deepcopy(bands);bad[0]['source_line_references'][0]['component_contract']='x'
            with self.assertRaises(ValueError):review(page,'a'*64,1,parents,faces,bad)
            with self.assertRaises(ValueError):review(page,'b'*64,1,parents,faces,bands)
        finally:doc.close()
