import copy
import unittest
from shapely.geometry import box,Polygon,mapping
from unittest.mock import patch
import test_wall_region_adjacency as fixtures
from voxel_mapper.wall_region_adjacency import review as adjacency_review
from voxel_mapper.wall_perimeter_coverage import review

class WallPerimeterCoverageTests(unittest.TestCase):
    def test_trace_preserves_source_rings_and_reports_unpaired_boundaries(self):
        doc,page,parents,faces,bands=fixtures.WallRegionAdjacencyTests().source()
        try:
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                adjacency=adjacency_review(page,'a'*64,1,parents,faces,bands)
            before=copy.deepcopy([parents,faces,bands,adjacency])
            result=review(parents,faces,bands,adjacency)
            self.assertEqual(result['counts']['retained_region_traces'],2)
            room=next(r for r in result['region_traces'] if r['face_id']=='0')
            self.assertEqual(room['boundary_length_pdf_points'],200)
            self.assertEqual(room['paired_length_pdf_points'],70)
            self.assertEqual(room['source_region_geometry'],faces[0]['geometry'])
            self.assertFalse(room['complete_paired_boundary_candidate']);self.assertFalse(result['footprint_export_ready'])
            self.assertEqual([parents,faces,bands,adjacency],before)
            self.assertEqual(result['world_geometry_additions'],0)
            holed=copy.deepcopy(faces)
            holed[0]['geometry']=mapping(Polygon(box(0,20,30,90).exterior.coords,[box(20,25,25,30).exterior.coords]))
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                hole_adjacency=adjacency_review(page,'a'*64,1,parents,holed,bands)
            hole_trace=next(r for r in review(parents,holed,bands,hole_adjacency)['region_traces'] if r['face_id']=='0')
            self.assertEqual(hole_trace['hole_count'],1)
            self.assertEqual(sum(s['ring_role']=='protected_hole_ring' for s in hole_trace['segments']),4)
            self.assertEqual(hole_trace['source_region_geometry'],holed[0]['geometry'])
        finally:doc.close()

    def test_budget_discards_partial_traces_and_wrong_source_rejects(self):
        doc,page,parents,faces,bands=fixtures.WallRegionAdjacencyTests().source()
        try:
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                adjacency=adjacency_review(page,'a'*64,1,parents,faces,bands)
            limited=review(parents,faces,bands,adjacency,max_checks=1)
            self.assertEqual(limited['region_traces'],[]);self.assertEqual(limited['status'],'perimeter_budget_withheld')
            changed=copy.deepcopy(faces);changed[0]['geometry']={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}
            with self.assertRaises(ValueError):review(parents,changed,bands,adjacency)
            with self.assertRaises(ValueError):review(parents,faces,bands,adjacency,max_checks=True)
        finally:doc.close()

    def test_changed_side_and_forged_seed_reject(self):
        doc,page,parents,faces,bands=fixtures.WallRegionAdjacencyTests().source()
        try:
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                adjacency=adjacency_review(page,'a'*64,1,parents,faces,bands)
            changed=copy.deepcopy(adjacency)
            changed['wall_adjacency'][0]['sides'][0]['band_side_support']=mapping(box(0,0,10,10))
            with self.assertRaises(ValueError):review(parents,faces,bands,changed)
            changed=copy.deepcopy(adjacency)
            changed['wall_adjacency'][0]['sides'][0]['adjacent_regions'][0]['region_claim_indices']=[]
            with self.assertRaises(ValueError):review(parents,faces,bands,changed)
            changed=copy.deepcopy(adjacency)
            changed['wall_adjacency']=[]
            with self.assertRaises(ValueError):review(parents,faces,bands,changed)
            changed=copy.deepcopy(adjacency)
            changed['labels'][0]['glyph_screen']['status']='hidden'
            with self.assertRaises(ValueError):review(parents,faces,bands,changed)
        finally:doc.close()

    def test_overlapping_support_is_counted_once(self):
        doc,page,parents,faces,bands=fixtures.WallRegionAdjacencyTests().source()
        try:
            duplicate=copy.deepcopy(bands[0]);duplicate['id']='duplicate-band'
            doubled=bands+[duplicate]
            with patch('voxel_mapper.wall_region_adjacency.screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                adjacency=adjacency_review(page,'a'*64,1,parents,faces,doubled)
            result=review(parents,faces,doubled,adjacency)
            room=next(r for r in result['region_traces'] if r['face_id']=='0')
            self.assertEqual(room['paired_length_pdf_points'],70)
            self.assertEqual(len(room['seed_wall_band_ids']),2)
            exhausted=review(parents,faces,doubled,adjacency,max_checks=result['checks']-1)
            self.assertEqual(exhausted['region_traces'],[])
            self.assertEqual(exhausted['counts']['retained_region_traces'],0)
        finally:doc.close()
