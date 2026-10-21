import copy
import json
import unittest
from unittest.mock import patch

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import MultiPolygon, box, mapping, shape

from tests import test_automatic_facade_alignment as fixtures
from voxel_mapper import automatic_facade_alignment as alignment, automatic_wall_returns as returns
from voxel_mapper.automatic_opening_links import affine
from voxel_mapper.clipped_plan_fills import recover
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.reconstruction_evidence_queue import digest


class WallReturnTests(unittest.TestCase):
    def fixture(self, *, reverse=False, extra_left=0, right_gap=0):
        sources,inventories,buildings,levels=fixtures.FacadeAlignmentTests().fixture()
        plan=inventories[0]; frame=buildings['frames'][0]['frame_review']['frames'][0]
        frame['marker_direction_pdf_native']=[0,1]
        a,b=(130,158) if reverse else (40,68)
        geometry=MultiPolygon([box(0,0,a,4),box(b,0,198,4)])
        def fill(identifier,g,seq):
            return {'id':identifier,'fill_color':[.5,.5,.5],'fill_opacity':1.,'paint_seqno':seq,
                    'clip_references':[],'geometry':mapping(g)}
        fills=[fill('paint',geometry,0),fill('left',box(0,4,4,90),1),fill('right',box(198+right_gap,0,202+right_gap,90),2)]
        fills.extend(fill('extra-left-'+str(i),box(0,4,4,90),i+3) for i in range(extra_left))
        plan['plan_gap_review']['page_fill_recovery']['candidates']=fills
        gap={'id':'gap','gap_endpoints_pdf_native':[[a,2],[b,2]]};plan['plan_gap_review']['gaps']=[gap]
        buildings['projected_gaps'][0].update(source_gap_id='gap',nominal_plan_position_interval_m=[a*.05,b*.05])
        fixtures.FacadeAlignmentTests().rebind(sources,inventories,buildings,levels)
        raw=alignment.run(sources,inventories,buildings,levels)
        review=raw['frames'][0]['frame_reviews'][0]
        scale={'status':'peripheral_sheet_layout_evidence_only','source_inventory_sha256':raw['source_inventory_sha256'],
            'source_building_links_sha256':digest(buildings),'source_level_context_sha256':digest(levels),
            'source_facade_alignment_sha256':digest(raw),'pairs':[{'id':'layout',
                'layout_fit':{'subject_to_reference_linear_row_matrix':[[1.,0.],[0.,1.]]}}],
            'diagnostics':[{'pair_id':'layout','source_frame_review_sha256':digest(review)}]}
        return sources,inventories,buildings,levels,raw,scale

    def trace(self,args):
        frame=args[2]['frames'][0]['frame_review']['frames'][0]
        extent=next(e for e in args[4]['frames'][0]['frame_reviews'][0]['plan_extents'] if e['source_kind']=='near_ray_original_paint')
        return returns.review_returns(args[1][0],args[0][0]['views'][0],frame,extent,lambda:None)

    def test_both_original_paint_sides_and_every_vertex_proof_remain_conditional(self):
        args=self.fixture();before=copy.deepcopy(args);result=returns.run(*args)
        self.assertEqual(args,before);self.assertEqual(result['counts']['original_corner_pairs'],2)
        self.assertEqual(result['counts']['layout_widths_compatible'],2)
        self.assertEqual(result['counts']['position_comparisons'],4)
        self.assertEqual(result['counts']['conditional_positions_compatible'],2)
        trace=result['frames'][0]['paint_reviews'][0]
        self.assertEqual({p['paint_side'] for p in trace['corner_pairs']},{'marker_facing','away_from_marker'})
        self.assertEqual(trace['base_profile']['source_part_count'],2)
        for pair in trace['corner_pairs']:
            self.assertFalse(pair['source_geometry_changed']);self.assertFalse(pair['physical_facade_extent_verified'])
            for corner in pair['corners']:
                self.assertTrue(corner['selected_vertex']['supporting_original_edge_indices'])
        for diagnostic in result['diagnostics']:
            for position in diagnostic['position_comparisons']:
                self.assertEqual(len(position['witnesses']),4)
                self.assertFalse(position['origin_fit_to_opening']);self.assertFalse(position['position_alignment_verified'])
        self.assertFalse(result['layout_application_verified']);self.assertEqual(result['world_geometry_additions'],0)

    def test_opposite_position_direction_cannot_move_the_original_corner_origin(self):
        result=returns.run(*self.fixture(reverse=True))
        positions=[p for d in result['diagnostics'] for p in d['position_comparisons']]
        self.assertTrue(all(p['elevation_x_reversed'] for p in positions if p['status']=='all_witness_positions_compatible'))
        self.assertTrue(all(not p['origin_fit_to_opening'] for p in positions))

    def test_near_source_joint_retains_its_real_gap_without_snapping_or_union(self):
        args=self.fixture(right_gap=.1);result=returns.run(*args);trace=result['frames'][0]['paint_reviews'][0]
        right=trace['return_candidates']['right'][0]
        self.assertAlmostEqual(right['source_boundary_distance_pdf_points'],.1)
        self.assertFalse(right['exact_source_contact']);self.assertFalse(right['joint_geometry_repaired'])
        near=next(p for p in trace['corner_pairs'] if p['paint_side']=='marker_facing')
        self.assertAlmostEqual(near['corners'][1]['selected_vertex']['point_pdf_native'][0],202.1)

    def test_missing_wrong_style_distant_and_nonperpendicular_returns_do_not_invent_corners(self):
        for mode in ('missing','style','distance','direction','crossing'):
            args=self.fixture();plan=args[1][0];fills=plan['plan_gap_review']['page_fill_recovery']['candidates']
            if mode=='missing':fills.pop(2)
            elif mode=='style':fills[2]['fill_color']=[.3,.3,.3]
            elif mode=='distance':fills[2]['geometry']=mapping(box(199,0,203,90))
            elif mode=='direction':fills[2]['geometry']=mapping(box(198,0,250,4))
            else:fills[2]['geometry']=mapping(box(198,0,202,200))
            trace=self.trace(args)
            self.assertEqual(trace['corner_pairs'],[])
            self.assertEqual(trace['status'],'both_original_perpendicular_returns_required')

    def test_all_competing_returns_are_retained_before_any_elevation_width_comparison(self):
        result=returns.run(*self.fixture(extra_left=1))
        self.assertEqual(result['counts']['perpendicular_return_candidates'],3)
        self.assertEqual(result['counts']['original_corner_pairs'],4)
        self.assertEqual(result['counts']['layout_width_comparisons'],4)
        self.assertFalse(result['physical_corner_identity_verified'])

    def test_a_bound_without_original_parallel_edge_and_side_support_is_insufficient(self):
        args=self.fixture();trace=self.trace(args);base=trace['base_profile'];right=trace['return_profiles'][-1]
        base['edges']=[];right['edges']=[]
        review=returns.corner([base,right],base,right,'right','marker_facing',lambda:None)
        self.assertEqual(review['status'],'original_corner_vertex_required');self.assertIsNone(review['selected_vertex'])

    def test_original_pdf_rings_holes_and_paint_provenance_are_not_replaced_by_bounds(self):
        with pymupdf.open() as document:
            page=document.new_page(width=260,height=180)
            drawing=page.new_shape();drawing.draw_rect((0,0,40,4));drawing.draw_rect((68,0,198,4))
            drawing.finish(color=None,fill=(.5,.5,.5));drawing.commit()
            page.draw_rect((0,4,4,90),color=None,fill=(.5,.5,.5))
            drawing=page.new_shape();drawing.draw_rect((198,0,202,90));drawing.draw_rect((199,30,201,40))
            drawing.finish(color=None,fill=(.5,.5,.5),even_odd=True);drawing.commit()
            fills=recover(page,'a'*64,1)['candidates'];original=next(f for f in fills if shape(f['geometry']).geom_type=='MultiPolygon')
            matrix=native_inverse(page);geometry=affine_transform(shape(original['geometry']),affine(matrix))
            plan={'nominal_metres_per_pdf_point':.05,'plan_gap_review':{
                'unrotated_mupdf_to_pdf_native_matrix':list(matrix),'page_fill_recovery':{'candidates':fills}}}
            frame={'id':'original-frame','diagnostic_axis':[1,0],'source_native_endpoints':[[0,180],[198,180]],'marker_direction_pdf_native':[0,-1]}
            extent={'id':'original','source_id':original['id'],'source_record_sha256':digest(original),'geometry_pdf_native':mapping(geometry)}
            trace=returns.review_returns(plan,{'geometry':mapping(box(0,0,260,180))},frame,extent,lambda:None)
        self.assertEqual(len(trace['corner_pairs']),2)
        self.assertEqual(sum(p['source_hole_count'] for p in trace['return_profiles']),1)
        for profile in [trace['base_profile'],*trace['return_profiles']]:
            fill=next(f for f in fills if f['id']==profile['source_fill_id'])
            self.assertEqual(profile['source_fill_sha256'],digest(fill))
            for vertex in profile['vertices']:
                g=shape(profile['geometry_pdf_native']);parts=list(g.geoms) if g.geom_type=='MultiPolygon' else [g]
                self.assertEqual(vertex['point_pdf_native'],list(parts[vertex['part_index']].exterior.coords[vertex['exterior_vertex_index']]))

    def test_a_disagreeing_parent_threshold_prevents_any_position_fit(self):
        args=self.fixture();parent=args[3]['views'][0]['families'][0]
        bounds=list(parent['witnesses'][1]['source_bounds_pixels']);bounds[2]=240
        parent['witnesses'][1]['source_bounds_pixels']=bounds
        args[4]['source_level_context_sha256']=digest(args[3])
        args[5]['source_facade_alignment_sha256']=digest(args[4])
        args[5]['source_level_context_sha256']=digest(args[3])
        result=returns.run(*args)
        self.assertTrue(all(c['status']=='extent_width_witnesses_disagree' for d in result['diagnostics'] for c in d['layout_width_comparisons']))
        self.assertEqual(result['counts']['position_comparisons'],0)

    def test_early_late_and_source_candidate_budgets_discard_complete_partial_results(self):
        result=returns.run(*self.fixture(),max_checks=1)
        self.assertEqual(result['status'],'wall_return_budget_withheld');self.assertEqual(result['frames'],[])
        original=returns.corner;calls=[]
        def late(*args):
            calls.append(1)
            if len(calls)==3:raise OverflowError('wall_return_work_budget')
            return original(*args)
        with patch.object(returns,'corner',side_effect=late):result=returns.run(*self.fixture())
        self.assertEqual(result['frames'],[]);self.assertEqual(result['diagnostics'],[])
        result=returns.run(*self.fixture(extra_left=64))
        self.assertEqual(result['reason'],'source_return_candidate_budget');self.assertEqual(result['frames'],[])

    def test_stale_duplicate_partial_and_nonfinite_source_inputs_are_rejected(self):
        args=self.fixture();args[1][0]['changed']=True
        with self.assertRaisesRegex(ValueError,'Matching source scale'):returns.run(*args)
        args=self.fixture();args[0][0]['views'][1]=copy.deepcopy(args[0][0]['views'][0])
        with self.assertRaisesRegex(ValueError,'Matching unique'):returns.run(*args)
        args=self.fixture();args[5]['status']='sheet_scale_budget_withheld'
        self.assertEqual(returns.run(*args)['status'],'complete_facade_and_sheet_scale_required')
        for value in (0,True,100001):
            with self.assertRaises(ValueError):returns.run(*self.fixture(),max_checks=value)
        args=self.fixture();frame=args[2]['frames'][0]['frame_review']['frames'][0]
        frame['diagnostic_axis']=[float('nan'),0]
        fill=args[1][0]['plan_gap_review']['page_fill_recovery']['candidates'][0]
        with self.assertRaises(ValueError):returns.paint_profile(fill,shape(fill['geometry']),frame,.05,lambda:None)

    def test_independent_saved_json_audit_checks_vertices_sides_and_all_position_witnesses(self):
        from collections import Counter
        from scripts.audit_wall_return_corners import verify
        args=self.fixture();result=json.loads(json.dumps(returns.run(*args)));checked=Counter()
        verify(*args,result,checked,100000)
        self.assertEqual(checked['independent_original_return_links'],2)
        self.assertEqual(checked['independent_original_side_corner_choices'],4)
        self.assertEqual(checked['independent_return_extent_witnesses'],4)
        self.assertEqual(checked['independent_return_position_witnesses'],16)


if __name__=='__main__':unittest.main()
