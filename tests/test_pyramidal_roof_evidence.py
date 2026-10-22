import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from voxel_mapper import pyramidal_roof_topology as topology
from voxel_mapper import pyramidal_roof_evidence as evidence
from voxel_mapper import preshow_level_geometry as parent
from tests import test_preshow_level_geometry as parent_tests
from tests import test_roof_source_topology as topology_tests
from voxel_mapper.roof_source_topology import connected_candidates


class PyramidalRoofTests(unittest.TestCase):
    def graph(self):
        inventory=topology_tests.RoofSourceTopologyTests().inventory()
        corners=[[0.,100.],[100.,100.],[100.,200.],[0.,200.]];center=[50.,150.]
        for i,p in enumerate(corners):
            inventory['source_components'].append({'id':'spoke'+str(i),'geometry':{'type':'LineString','coordinates':[center,p]},
                'rendering_status':'supported_straight_unclipped_polyline','curve_approximation':{'cubic_segments':0}})
            if i==0:continue
            inventory['source_components'].append({'id':'edge'+str(i),'geometry':{'type':'LineString','coordinates':[p,corners[(i+1)%4]]},
                'rendering_status':'supported_straight_unclipped_polyline','curve_approximation':{'cubic_segments':0}})
        return json.loads(json.dumps(connected_candidates(inventory,lambda:None)))

    def fixture(self,root):
        args=parent_tests.PreshowLevelTests().fixture(root);r=parent.build(*args)
        return Path(r['directory']),*args[:-1],root/'pyramid'

    def context(self,candidate):
        return {'id':'context','candidate_id':candidate['id'],'source_horizontal_axis_pdf_native':[1.,0.]}

    def silhouette(self,candidate,threshold=220):
        context=self.context(candidate)
        return {'id':'silhouette'+str(threshold),'candidate_id':candidate['id'],'context_id':'context',
            'source_level_binding_id':'level','source_level_value_m_candidate':100.,'source_level_label':'Level',
            'source_ink_threshold':threshold,'image_left_to_native_orientation':1,
            'image_eaves_above_printed_level_nominal_m':[3.,3.2],
            'apex_above_printed_level_nominal_m':6.,'projection':evidence.cap_projection(candidate,context,.1),
            'nominal_metres_per_pixel':.1,'plan_unit':.1}

    def test_original_closed_spokes_and_shared_cap_retain_whole_tails(self):
        graph=self.graph();before=copy.deepcopy(graph);r=topology.discover(graph,lambda:None)
        self.assertEqual(len(r['candidates']),1);c=r['candidates'][0]
        self.assertFalse(c['source_endpoints_snapped']);self.assertFalse(c['source_closure_inferred'])
        low=next(c for c in graph['candidates'] if c['ridge_source_id']=='r')
        joins=topology.junctions(graph,r['candidates'],{low['id']},lambda:None)
        self.assertEqual(len(joins),1);self.assertEqual(joins[0]['status'],'shared_original_cap_with_boundary_coincident_tails')
        self.assertEqual([t['source_tail_length_nominal_m'] for t in joins[0]['rail_tail_relations']],[.5,.5])
        self.assertEqual(graph,before);self.assertIsNone(joins[0]['new_join_mesh'])

    def test_missing_or_nearly_matching_spokes_and_perimeter_do_not_get_repaired(self):
        for source in ('spoke0','edge1'):
            for mode in ('missing','near'):
                g=self.graph();index=next(i for i,l in enumerate(g['lines']) if l['source_component_id']==source)
                if mode=='missing':g['lines'].pop(index)
                else:g['lines'][index]['source_endpoints_pdf_native'][0][0]+=.00001
                self.assertEqual(topology.discover(g,lambda:None)['candidates'],[])

    def test_duplicate_paint_witnesses_are_retained_and_order_is_stable(self):
        g=self.graph();line=copy.deepcopy(next(l for l in g['lines'] if l['source_component_id']=='spoke0'));line['source_component_id']='repaint';g['lines'].append(line)
        a=topology.discover(g,lambda:None);g['lines'].reverse();b=topology.discover(g,lambda:None)
        self.assertEqual(a['candidates'],b['candidates']);self.assertTrue(any(len(ids)==2 for ids in a['candidates'][0]['source_spoke_ids_per_corner']))

    def test_competing_source_roofs_are_retained_without_nearest_selection(self):
        g=self.graph();extra=copy.deepcopy(g['lines'])
        for l in extra:
            l['source_component_id']='second-'+l['source_component_id']
            for p in l['source_endpoints_pdf_native']:p[0]+=300.
        g['lines'].extend(extra);self.assertEqual(len(topology.discover(g,lambda:None)['candidates']),2)

    def test_duplicate_perimeter_paints_do_not_double_count_tail_coverage(self):
        g=self.graph();line=copy.deepcopy(next(l for l in g['lines'] if l['source_component_id']=='edge3'));line['source_component_id']='edge3-repaint';g['lines'].append(line)
        c=topology.discover(g,lambda:None)['candidates'];low=next(c for c in g['candidates'] if c['ridge_source_id']=='r')
        join=topology.junctions(g,c,{low['id']},lambda:None)[0]
        self.assertEqual(join['status'],'shared_original_cap_with_boundary_coincident_tails')
        self.assertTrue(all(t['unique_boundary_coverage_nominal_m']==.5 for t in join['rail_tail_relations']))

    def test_invalid_scales_lines_and_source_bounds_fail(self):
        for value in (0.,float('nan'),-1.):
            g=self.graph();g['nominal_metres_per_pdf_point']=value
            with self.assertRaises(ValueError):topology.discover(g,lambda:None)
        g=self.graph();g['lines'][0]['source_endpoints_pdf_native'][0][0]=float('nan')
        with self.assertRaises(ValueError):topology.discover(g,lambda:None)
        g=self.graph();g['lines']*=1000
        with self.assertRaises(OverflowError):topology.discover(g,lambda:None)

    def test_literal_columns_keep_gaps_and_dense_source_pixels(self):
        gray=np.full((160,120),255,np.uint8);gray[20:49,10:110]=230;gray[35,10:110]=255
        mask=np.zeros_like(gray,bool);before=gray.copy()
        self.assertEqual(evidence.literal_columns(gray,mask,220,lambda:None),[])
        rows=evidence.literal_columns(gray,mask,235,lambda:None);self.assertEqual(len(rows),100)
        self.assertEqual(rows[0]['unsupported_row_intervals'],[[35,36]]);self.assertFalse(rows[0]['source_gaps_filled'])
        np.testing.assert_array_equal(before,gray)

    def test_dense_column_budget_withholds_instead_of_returning_first_subset(self):
        gray=np.full((240,1200),255,np.uint8)
        for y in range(0,220,24):gray[y:y+18,:]=0
        with self.assertRaises(OverflowError):evidence.literal_columns(gray,np.zeros_like(gray,bool),220,lambda:None)

    def test_horizontal_index_retains_vertical_failures_without_nearest_y(self):
        pair={'id':'pair','inferred_ridge_pixel':[60.,20.],'left_pitch_degrees':30.,'right_pitch_degrees':30.}
        columns=[{'id':str(i),'x':i,'source_y_interval_pixels':[49,75]} for i in range(120)]
        columns.append({'id':'vertical-failure','x':10,'source_y_interval_pixels':[5,30]})
        r,corners=evidence.indexed_endcaps(pair,columns,{'id':'projection','native_runs_m':[5.,5.]},.1,lambda:None)
        self.assertTrue(any(c['status']=='source_corner_held' and c['source_fascia_column_id']=='vertical-failure' for c in corners))
        self.assertTrue(any(c['status']=='conditional_source_endcaps_agree' for c in r))

    def test_corner_extent_holds_extrapolated_edges_and_groups_equal_height_witnesses(self):
        candidate=topology.discover(self.graph(),lambda:None)['candidates'][0];context=self.context(candidate)
        pair={'id':'pair','inferred_ridge_pixel':[60.,20.],'left_pitch_degrees':30.,'right_pitch_degrees':30.,'left_line_id':'l','right_line_id':'r'}
        lines=[{'id':'l','source_x_interval':[30,60],'source_pixels':[{'x':30,'y':37}]},{'id':'r','source_x_interval':[60,90],'source_pixels':[{'x':90,'y':37}]}]
        caps=[{'id':str(x),'x':x,'source_y_interval_pixels':[49,75]} for x in (9,10,109,110)]
        view={'view_id':'east','nominal_metres_per_pixel':.1,'pixel_to_display_matrix':[1,0,0,1,0,0],
            'variants':[{'threshold':220,'gable_intersections':[pair],'lines':lines,'source_fascia_columns':caps}]}
        bindings=[{'id':'level','datum_y_display_points':100.,'label':{'level_label_candidate':'Level','value_m_candidate':100.}}]
        rows,ends,corners,extents=evidence.silhouettes(candidate,context,view,bindings,.1,lambda:None)
        self.assertEqual(rows,[]);self.assertEqual(ends,[]);self.assertEqual(len(extents),2)
        self.assertTrue(all(c['status']=='original_slope_corner_support_held' for c in extents))
        lines[0]['source_pixels']=[{'x':10,'y':49}];lines[1]['source_pixels']=[{'x':110,'y':49}]
        rows,ends,corners,extents=evidence.silhouettes(candidate,context,view,bindings,.1,lambda:None)
        self.assertEqual(len(rows),2);self.assertEqual(len(ends),8)
        self.assertTrue(all(len(row['source_endcap_check_ids'])==4 for row in rows))
        self.assertTrue(all(row['equal_height_witnesses_grouped_without_averaging'] for row in rows))

    def test_source_context_requires_original_finite_reach_unique_target_and_same_view(self):
        g=topology.discover(self.graph(),lambda:None);ref={'source_reference_id':'ref','head_alternative_index':0,'candidate_id':'low',
            'source_reference_status':'visible','diagnostic_aim_segment_pdf_native':[[50.,230.],[50.,190.]]}
        source={'source_topologies':[{'view_id':'roof','candidates':[{'id':'low'}]}],
            'aim_checks':[ref], 'target_links':[{'source_reference_id':'ref','id':'link','status':'unique_source_view_reference_candidate','target_candidates':[{'view_id':'east'}]}]}
        self.assertEqual(evidence.source_contexts(source,[g],lambda:None)[0]['status'],'conditional_pyramid_source_view_context')
        source['target_links'][0]['status']='source_reference_visibility_or_identity_held'
        self.assertEqual(evidence.source_contexts(source,[g],lambda:None)[0]['status'],'pyramid_source_view_context_held')
        source['source_topologies'][0]['view_id']='other-page';self.assertEqual(evidence.source_contexts(source,[g],lambda:None),[])

    def test_cross_view_levels_use_printed_offset_and_retain_both_assignments(self):
        candidate=topology.discover(self.graph(),lambda:None)['candidates'][0];a=self.silhouette(candidate);b=copy.deepcopy(a);b['id']='other';b['source_level_value_m_candidate']=99.;b['apex_above_printed_level_nominal_m']+=1.;b['image_eaves_above_printed_level_nominal_m']=[v+1 for v in b['image_eaves_above_printed_level_nominal_m']]
        r=evidence.comparisons([a],[b],lambda:None);self.assertEqual(len(r),2);self.assertTrue(all(c['status']=='conditional_cross_view_pyramid_heights_agree' for c in r))
        b['apex_above_printed_level_nominal_m']+=2.;self.assertTrue(all(c['status']=='cross_view_pyramid_heights_held' for c in evidence.comparisons([a],[b],lambda:None)))
        self.assertFalse(r[0]['independent_survey_controls']);self.assertTrue(r[0]['supplemental_physical_correspondence_assumed'])

    def test_mesh_keeps_original_apex_corners_and_separate_eave_measurements(self):
        c=topology.discover(self.graph(),lambda:None)['candidates'][0];s=self.silhouette(c);m=evidence.mesh(c,s)
        expected=(np.array(c['source_corners_pdf_native'])-c['source_apex_pdf_native'])*.1
        np.testing.assert_array_equal(np.array(m['vertices'])[:4,:2],expected)
        self.assertEqual(m['vertices'][4],[0.,0.,6.]);self.assertEqual(len(m['triangles']),4)
        self.assertEqual(set(m['source_corner_heights_nominal_m']),{3.,3.2});self.assertTrue(m['linear_eave_height_plane_assumed'])
        self.assertFalse(m['world_placement_eligible'])

    def test_threshold_disagreement_remains_explicit(self):
        c=topology.discover(self.graph(),lambda:None)['candidates'][0];a=self.silhouette(c);a['mesh']=evidence.mesh(c,a)
        b=self.silhouette(c,235);b['mesh']=evidence.mesh(c,b);b['mesh']['vertices'][4][2]+=1.
        self.assertEqual(evidence.threshold_checks([a,b],lambda:None)[0]['status'],'pyramid_threshold_heights_held')

    def test_missing_second_threshold_is_held_instead_of_empty_success(self):
        c=topology.discover(self.graph(),lambda:None)['candidates'][0];a=self.silhouette(c)
        r=evidence.threshold_coverage([a],lambda:None)[0]
        self.assertEqual(r['missing_source_thresholds'],[235]);self.assertEqual(r['status'],'pyramid_cross_threshold_support_missing')
        self.assertFalse(r['physical_acceptance_authorized'])
        b=self.silhouette(c,235)
        self.assertEqual(evidence.threshold_coverage([a,b],lambda:None)[0]['missing_source_thresholds'],[])

    def test_complete_source_replay_cache_and_previous_models_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));original=(args[0]/'preshow-level-geometry.json').read_bytes();r=evidence.build(*args)
            self.assertEqual(r,evidence.build(*args));self.assertEqual((args[0]/'preshow-level-geometry.json').read_bytes(),original)
            self.assertEqual(r['world_geometry_additions'],0);self.assertFalse(r['previous_roof_models_changed'])

    def test_early_and_late_overflow_clear_all_partial_graphs_and_meshes(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args,max_checks=1)
            self.assertEqual(r['status'],'pyramidal_roof_evidence_budget_withheld');self.assertEqual(r['plan_graphs'],[])
            with patch.object(evidence,'threshold_checks',side_effect=OverflowError('late')):r=evidence.build(*args)
            self.assertEqual(r['conditional_pyramid_models'],[]);self.assertEqual(r['source_junctions'],[])

    def test_parent_crop_and_saved_cache_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args);(Path(r['directory'])/'pyramidal-roof-evidence.json').write_text('{}')
            with self.assertRaises(ValueError):evidence.build(*args)
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));next((args[1]/'views').rglob('view.png')).write_bytes(b'changed')
            with self.assertRaises(ValueError):evidence.build(*args)

    def test_parent_crop_changed_during_final_join_comparison_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));original=evidence.threshold_checks
            def change(*values):
                result=original(*values);path=next((args[1]/'views').rglob('view.png'));path.write_bytes(path.read_bytes()+b'changed');return result
            with patch.object(evidence,'threshold_checks',side_effect=change):
                with self.assertRaisesRegex(ValueError,'during build'):evidence.build(*args)

    def test_independent_auditor_replays_unchanged_source_pipeline(self):
        from scripts.audit_pyramidal_roof_evidence import audit
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args)
            receipt=audit(r['directory'],*args[:-1],Path(temp)/'audit.json')
            self.assertEqual(receipt['status'],'passed');self.assertTrue(receipt['fresh_replay_identical'])
