import copy,hashlib,json
import unittest
import pymupdf
from shapely.geometry import box,shape
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.literal_path_edges import extract
from voxel_mapper.wing_partition_review import derive,review
from voxel_mapper.wing_partition_study import apply
from voxel_mapper.architectural_interpretation import wall_bands_from_components


class MixedPartitionTests(unittest.TestCase):
    def source(self,taper=False):
        doc=pymupdf.open();page=doc.new_page(width=700,height=300)
        for x in (75,78):
            s=page.new_shape();s.draw_line((x,30),(x+(.2 if taper and x==78 else 0),95))
            s.draw_bezier((x+(.2 if taper and x==78 else 0),95),(x+10,95),(x+10,110),(x,110));s.finish(color=(0,0,0),closePath=False);s.commit()
        s=page.new_shape();s.draw_bezier((250,30),(250,45),(250,80),(250,95));s.finish(color=(0,0,0),closePath=False);s.commit()
        parents,_=extract_page(page,'f'*64,1,min_line_length_points=.25,isolate_open_stroked_subpaths=True)
        return doc,page,parents

    def test_straight_items_in_curved_paths_are_retained_without_chords(self):
        doc,page,parents=self.source();index,report=extract(page)
        old=derive(parents,[1,0,0,1,0,0],.035,box(0,0,700,300))
        new=derive(parents,[1,0,0,1,0,0],.035,box(0,0,700,300),literal_index=index)
        self.assertEqual(old['segments'],[]);self.assertEqual(len(new['segments']),2);self.assertEqual(len(new['bands']),1)
        self.assertGreater(report['cubic_operators_excluded'],0)
        for s in new['segments']:
            self.assertEqual(s['curve_approximation']['cubic_segments'],0)
            self.assertGreater(s['parent_curve_approximation']['cubic_segments'],0)
            self.assertTrue(all(p['operator']=='l' for p in s['source_segment']['literal_operator_proofs']))
        self.assertFalse(any(shape(s['geometry']).centroid.x==250 for s in new['segments']));doc.close()

    def test_operator_budget_exhaustion_discards_complete_index(self):
        doc,page,_=self.source();index,r=extract(page,max_items=2)
        self.assertEqual(index,{});self.assertEqual(r['status'],'literal_operator_budget_withheld');doc.close()

    def test_tapered_source_sides_are_not_snapped_into_parallel_lines(self):
        doc,page,parents=self.source(taper=True);index,_=extract(page)
        r=derive(parents,[1,0,0,1,0,0],.035,box(0,0,700,300),literal_index=index)
        self.assertEqual(len(r['bands']),1);g=shape(r['bands'][0]['geometry'])
        self.assertEqual(wall_bands_from_components(r['segments'],.035)[0],[])
        self.assertNotEqual(r['bands'][0]['width_range_m'][0],r['bands'][0]['width_range_m'][1])
        self.assertGreater(g.area,0);self.assertEqual(parents,extract_page(page,'f'*64,1,min_line_length_points=.25,isolate_open_stroked_subpaths=True)[0]);doc.close()

    def test_source_order_is_deterministic(self):
        doc,page,parents=self.source();index,_=extract(page);args=([1,0,0,1,0,0],.035,box(0,0,700,300))
        self.assertEqual(derive(parents,*args,literal_index=index),derive(list(reversed(parents)),*args,literal_index=index));doc.close()

    def test_invalid_angle_and_operator_budgets_reject(self):
        for value in (True,float('nan'),.02,0):
            with self.assertRaises(ValueError):wall_bands_from_components([],.035,max_side_angle_sine=value)
        doc,page,_=self.source()
        with self.assertRaises(ValueError):extract(page,max_items=True)
        doc.close()

    def test_default_review_bytes_stay_unchanged_and_literal_receipt_is_separate(self):
        from tests.test_wing_partition_study import PartitionStudyTests
        f=PartitionStudyTests();f.setUp()
        try:
            self.assertEqual(review(f.parent,f.path),f.review)
            mixed=review(f.parent,f.path,recover_mixed_paths=True)
            self.assertNotEqual(mixed['version'],f.review['version']);self.assertIn('literal_operator_review',mixed)
            blocked=review(f.parent,f.path,recover_mixed_paths=True,max_operator_items=1)
            self.assertEqual(blocked['bands'],[]);self.assertEqual(blocked['status'],'literal_operator_budget_withheld')
        finally:f.tearDown()

    def test_repinned_curve_operator_cannot_become_a_straight_side(self):
        from tests.test_wing_partition_study import PartitionStudyTests
        f=PartitionStudyTests();f.setUp()
        try:
            mixed=review(f.parent,f.path,recover_mixed_paths=True);seed=copy.deepcopy(f.seed)
            seed['selected_band_ids']=[mixed['bands'][0]['id']]
            sid=mixed['bands'][0]['source_line_references'][0]['component_id']
            next(s for s in mixed['segments'] if s['id']==sid)['source_segment']['literal_operator_proofs'][0]['operator']='c'
            seed['review_sha256']=hashlib.sha256(json.dumps(mixed,sort_keys=True).encode()).hexdigest()
            with self.assertRaisesRegex(ValueError,'Literal original operator'):apply(f.model,f.cells,f.audit,mixed,seed)
        finally:f.tearDown()

    def test_native_endpoint_gap_keeps_standing_air(self):
        from tests.test_wing_partition_study import PartitionStudyTests
        from voxel_mapper.local_wing_review import build as front_build
        from voxel_mapper.wing_shell_study import build
        from voxel_mapper.wing_block_shapes import occupied_halves
        f=PartitionStudyTests();f.setUp()
        try:
            recipe=copy.deepcopy(f.f.f.f.recipe)
            recipe['documents']['plan']=copy.deepcopy(f.parent['source_frames']['plan']['specification'])
            recipe['plan_trace']['rear_point']=[10,145]
            recipe['openings'][0]['kind']='archway';recipe['openings'][0]['points_pixels']=[[110,200],[170,200],[170,80],[110,80]]
            recipe['openings'][1]['points_pixels']=[[180,175],[230,175],[230,80],[180,80]]
            parent=front_build(recipe,f.f.f.f.paths);shellseed=copy.deepcopy(f.f.seed)
            shellseed['parent_model_sha256']=hashlib.sha256((json.dumps(parent,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
            model,cells,audit=build(parent,shellseed);r=review(parent,f.path,recover_mixed_paths=True)
            band=max(r['bands'],key=lambda b:b['overlap_m']);seed=copy.deepcopy(f.seed)
            seed.update(parent_model_sha256=model['parent_model_sha256'],review_sha256=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(),
                        selected_band_ids=[band['id']],preserve_partition_endpoint_gaps=True)
            m,c,a=apply(model,cells,audit,r,seed);row=a['partition_study']['rows'][0]
            self.assertEqual(row['native_endpoint_gap_columns'],[2]);self.assertTrue(row['native_endpoint_gap_air_verified'])
            half=occupied_halves(c)
            for dx in (0,1):
                for hy in range(4):
                    for dz in (0,1):self.assertNotIn((4+dx,hy,4+dz),half)
        finally:f.tearDown()

if __name__=='__main__':unittest.main()
