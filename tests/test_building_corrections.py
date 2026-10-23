"""Source-linked edits change new geometry without transferring correctness."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.building_corrections import _apply,_benchmarks,geometry_metrics,run
from voxel_mapper.building_spec import FRAME,build,digest
from voxel_mapper.desktop_review import bind_source,load_session,save_review
from voxel_mapper.desktop_review_presets import prepare_demo
from voxel_mapper.reconstruction_benchmark import reference_digest


class BuildingCorrectionTests(unittest.TestCase):
    def fixture(self,root,bad_width=False):
        preset=prepare_demo(root/'demo')
        if bad_width:
            batch_path=Path(preset['batch_path']);queue_path=Path(preset['queue_path'])
            batch=json.loads(batch_path.read_text());candidate=batch['buildings'][0]['candidates'][0]
            for point in candidate['spec']['components'][0]['geometry']['profile']:
                if point[0]==8:point[0]=6
            candidate['candidate_sha256']=digest({k:v for k,v in candidate.items() if k!='candidate_sha256'})
            queue=json.loads(queue_path.read_text());queue['records'][0]['candidate_sha256']=candidate['candidate_sha256']
            queue['content_sha256']=digest({k:v for k,v in queue.items() if k!='content_sha256'})
            batch_path.write_text(json.dumps(batch));queue_path.write_text(json.dumps(queue))
        session=load_session(preset['queue_path'],preset['batch_path'])
        for path in preset['source_paths']:session=bind_source(session,path)
        return session,session['records'][0]

    def annotation(self,row,kind,**values):
        return {'type':kind,'source_sha256':row['source_sha256'][0],'source_page':1,**values}

    def save(self,root,session,row,annotations):
        return save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
            outcome=None,review_basis=None,review_reference='',corrections=annotations,output_directory=root/'saved')

    def test_dimension_scales_new_candidate_and_preserves_original_hole(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));original=copy.deepcopy(row['candidate']['spec'])
            annotation=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=10)
            revised,audit=_apply(original,[annotation])
            self.assertEqual(row['candidate']['spec'],original)
            geometry=revised['components'][0]['geometry']
            self.assertEqual(max(p[0] for p in geometry['profile']),10)
            self.assertEqual(geometry['holes'][0],[[1.25,1],[2.5,1],[2.5,2],[1.25,2]])
            self.assertNotEqual(audit['original_spec_sha256'],audit['corrected_spec_sha256'])
            self.assertFalse(build(revised)['world_placement_eligible'])

    def test_outline_preserves_existing_opening_and_refuses_excluded_hole(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            outline=self.annotation(row,'outline',component_id='front-wall',projection='xz',points_m=[[0,0],[9,0],[9,5],[0,5]])
            revised,_=_apply(spec,[outline])
            self.assertEqual(revised['components'][0]['geometry']['holes'],spec['components'][0]['geometry']['holes'])
            outline['points_m']=[[0,0],[.5,0],[.5,5],[0,5]]
            with self.assertRaisesRegex(ValueError,'invalidate'):_apply(spec,[outline])

    def test_opening_replaces_one_hole_and_protects_a_new_door_notch(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            window=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[1,1],[3,1],[3,2],[1,2]])
            door=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[5,0],[6,0],[6,2],[5,2]])
            revised,_=_apply(spec,[window,door])
            geometry=revised['components'][0]['geometry']
            self.assertEqual(len(geometry['holes']),1)
            self.assertEqual(max(p[0] for p in geometry['holes'][0]),3)
            self.assertTrue(revised['native_air_halves'])
            from voxel_mapper.building_native import compile_spec
            from voxel_mapper.wing_block_shapes import occupied_halves
            cells,audit=compile_spec(revised)
            self.assertTrue(audit['protected_air_verified'])
            self.assertFalse(set(occupied_halves(cells)) & {tuple(p) for p in revised['native_air_halves']})

    def test_overlapping_edit_intent_and_wrong_profile_plane_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            opening=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[1,1],[3,1],[3,2],[1,2]])
            with self.assertRaisesRegex(ValueError,'Overlapping'):_apply(spec,[opening,opening])
            opening['projection']='xy'
            with self.assertRaisesRegex(ValueError,'projection'):_apply(spec,[opening])

    def test_pose_rotates_extrusion_axis_and_preserves_protected_air(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            spec=copy.deepcopy(spec);spec['native_air_halves']=[[2,2,0],[3,2,0]]
            pose=self.annotation(row,'placement',translation_m=[1,.5,2],rotation_degrees=90)
            revised,_=_apply(spec,[pose])
            self.assertEqual(revised['components'][0]['geometry']['axis'],0)
            self.assertEqual(revised['components'][0]['geometry']['interval_m'],[.7,1])
            self.assertEqual(len(revised['native_air_halves']),2)
            from voxel_mapper.building_native import compile_spec
            self.assertTrue(compile_spec(revised)[1]['protected_air_verified'])

    def test_unassigned_mesh_air_guards_and_unrepresentable_pose_remain_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=copy.deepcopy(row['candidate']['spec'])
            spec['native_air_halves']=[[2,2,0]]
            dimension=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=9)
            with self.assertRaisesRegex(ValueError,'unassigned'):_apply(spec,[dimension])
            for pose in (self.annotation(row,'placement',translation_m=[0,0,0],rotation_degrees=20),
                         self.annotation(row,'placement',translation_m=[.1,0,0],rotation_degrees=90)):
                with self.assertRaises(ValueError):_apply(spec,[pose])

    def test_no_op_and_repeated_dimension_edits_do_not_create_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            dimension=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=8)
            with self.assertRaisesRegex(ValueError,'do not change'):_apply(spec,[dimension])
            dimension['value_m']=9
            with self.assertRaisesRegex(ValueError,'Conflicting'):_apply(spec,[dimension,dimension])

    def test_regeneration_measures_actual_geometry_against_fixed_synthetic_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,row=self.fixture(root,bad_width=True)
            annotation=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=8)
            saved=self.save(root,session,row,[annotation])
            reference={'footprint_m':[[0,0],[8,0],[8,.3],[0,.3]],'height_m':4,'position_m':[0,0,0],
                'openings_m':[[[1,1],[2,1],[2,2],[1,2]]]}
            # Resizing scales the existing window as well. Correct it explicitly
            # to the independently specified synthetic drawing coordinates.
            opening=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[1,1],[2,1],[2,2],[1,2]])
            saved2=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
                outcome=None,review_basis=None,review_reference='',corrections=[annotation,opening],output_directory=root/'saved-correct')
            config={'version':'reconstruction-benchmark-v1','dataset_kind':'synthetic','coordinate_frame':FRAME,'units':'metres',
                'cases':[{'id':'fixed-synthetic-elevation','building_id':row['building_id'],'source_sha256':row['source_sha256'],
                    'reference':{'geometry':reference,'geometry_definition':'projected_xy_bounds_origin_v1','component_id':'front-wall','opening_projection':'xz',
                        'review_basis':'independent_review','review_reference':'Independent synthetic fixture constants; no real park claim'},'prediction':None}]}
            config['reference_sha256']=reference_digest(config);path=root/'reference.json';path.write_text(json.dumps(config))
            original_pins={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (session['queue_path'],session['batch_path'],* [v['path'] for v in session['resolved_sources'].values()])}
            result=run(saved2['output_directory'],root/'result',world=False,benchmark_path=path)
            self.assertEqual(result['benchmark']['before']['cases_within_thresholds'],0)
            self.assertEqual(result['benchmark']['after']['cases_within_thresholds'],1)
            self.assertFalse(result['benchmark']['real_world_accuracy_established'])
            self.assertNotEqual(result['original_candidate_sha256'],result['corrected_candidate_sha256'])
            self.assertEqual(result['training_labels_generated'],0)
            self.assertFalse(result['model_promoted'])
            fresh=load_session(result['queue_path'],result['batch_path'])
            self.assertFalse(any(fresh['records'][0]['candidate']['gates'].values()))
            self.assertIsNone(fresh['records'][0]['outcome'])
            for p,pin in original_pins.items():self.assertEqual(hashlib.sha256(Path(p).read_bytes()).hexdigest(),pin)
            with self.assertRaisesRegex(ValueError,'fresh'):run(saved['output_directory'],root/'result',world=False)

    def test_real_native_world_generation_and_readback_preserve_new_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,row=self.fixture(root)
            annotation=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[3,0],[4,0],[4,2],[3,2]])
            saved=self.save(root,session,row,[annotation])
            result=run(saved['output_directory'],root/'worlds',world=True)
            self.assertTrue(Path(result['corrected_world_path']).is_file())
            self.assertIn('all written blocks',result['corrected_native']['world']['round_trip_validation'])
            self.assertTrue(result['corrected_native']['native_audit']['protected_air_verified'])
            self.assertEqual(result['park_world_blocks_added'],0)
            self.assertIsNone(result['corrected_native']['geographic_registration'])

    def test_changed_saved_input_and_cancellation_cannot_publish_success(self):
        from concurrent.futures import CancelledError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,row=self.fixture(root)
            saved=self.save(root,session,row,[self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=9)])
            with self.assertRaises(CancelledError):run(saved['output_directory'],root/'cancelled',world=False,cancelled=lambda:True)
            self.assertFalse((root/'cancelled').exists())
            Path(session['queue_path']).write_text('{}')
            with self.assertRaises(ValueError):run(saved['output_directory'],root/'changed',world=False)
            self.assertFalse((root/'changed'/'report.json').exists())

    def test_floor_outline_and_dimension_order_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=copy.deepcopy(row['candidate']['spec'])
            component=spec['components'][0];component['role']='floor'
            component['geometry']={'kind':'extrusion','axis':2,'interval_m':[-1,0],'profile':[[0,0],[8,0],[8,5],[0,5]],'holes':[]}
            spec['floor_reference']={'elevation_m':0,'surveyed_datum_verified':False}
            outline=self.annotation(row,'outline',component_id='front-wall',projection='xy',points_m=[[0,0],[10,0],[10,5],[0,5]])
            dimension=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=12)
            revised,audit=_apply(spec,[dimension,outline])
            self.assertEqual(max(p[0] for p in revised['components'][0]['geometry']['profile']),12)
            self.assertNotIn('floor_reference',revised)
            self.assertTrue(audit['floor_reference_invalidated'])
            self.assertEqual([a['type'] for a in audit['applied']],['outline','dimension'])

    def test_retained_wicker_mesh_pose_preserves_real_guard_geometry(self):
        from voxel_mapper.building_spec import from_study
        from voxel_mapper.building_native import compile_spec
        path=Path(__file__).resolve().parents[1]/'evidence'/'wicker-shop-projection-model.json'
        model=json.loads(path.read_text());spec=from_study(model,'wicker',hashlib.sha256(path.read_bytes()).hexdigest())
        original=copy.deepcopy(spec)
        pose={'type':'placement','source_sha256':'a'*64,'source_page':1,'translation_m':[1,.5,0],'rotation_degrees':90}
        revised,_=_apply(spec,[pose])
        self.assertEqual(spec,original)
        self.assertEqual(len(revised['native_air_halves']),len(spec['native_air_halves']))
        self.assertTrue(compile_spec(revised)[1]['protected_air_verified'])
        self.assertTrue(all(c['evidence']['class']=='inferred' for c in revised['components']))
        self.assertFalse(build(revised)['world_placement_eligible'])

    def test_corrected_candidate_needs_its_own_independent_decision(self):
        from voxel_mapper.desktop_memory import MemoryStore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,row=self.fixture(root)
            change=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=9)
            original_review=save_review(session,building_id=row['building_id'],candidate_sha256=row['candidate_sha256'],
                outcome='rejected',review_basis='independent_review',review_reference='Synthetic original rejection',
                corrections=[change],output_directory=root/'rejected-original')
            result=run(original_review['output_directory'],root/'regenerated',world=False)
            next_session=load_session(result['queue_path'],result['batch_path'])
            for path in result['source_paths']:next_session=bind_source(next_session,path)
            next_row=next_session['records'][0]
            self.assertNotEqual(next_row['candidate_sha256'],row['candidate_sha256'])
            self.assertIsNone(next_row['outcome'])
            reviewed=save_review(next_session,building_id=next_row['building_id'],candidate_sha256=next_row['candidate_sha256'],
                outcome='accepted',review_basis='independent_review',review_reference='Independent synthetic corrected-candidate review',
                corrections=[],output_directory=root/'reviewed-corrected')
            store=MemoryStore(root/'memory')
            self.assertEqual(store.summary()['feedback_records'],0)
            for report in (original_review,reviewed):
                feedback=json.loads(Path(report['feedback_path']).read_text());store.import_feedback(feedback['records'])
            records=store.feedback()
            self.assertEqual(len(records),2)
            self.assertEqual({r['candidate_sha256']:r['outcome'] for r in records},
                {row['candidate_sha256']:'rejected',next_row['candidate_sha256']:'accepted'})
            self.assertIsNone(store.summary()['active_model'])

    def test_source_changed_during_export_retains_only_partial_results(self):
        from voxel_mapper.building_native import export_preview
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session,row=self.fixture(root)
            change=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=9)
            saved=self.save(root,session,row,[change]);calls=[]
            def changed(spec,output,**kwargs):
                result=export_preview(spec,output,**kwargs);calls.append(output)
                if len(calls)==2:
                    path=Path(session['queue_path']);path.write_bytes(path.read_bytes()+b' ')
                return result
            with patch('voxel_mapper.building_native.export_preview',side_effect=changed):
                with self.assertRaises(ValueError):run(saved['output_directory'],root/'partial',world=False)
            self.assertFalse((root/'partial'/'report.json').exists())

    def test_unsupported_mesh_outline_does_not_publish_a_guessed_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=copy.deepcopy(row['candidate']['spec'])
            spec['components'][0]['geometry']={'kind':'mesh','mesh':build(spec)['components'][0]['mesh']}
            annotation=self.annotation(row,'outline',component_id='front-wall',projection='xz',points_m=[[0,0],[9,0],[9,4],[0,4]])
            with self.assertRaisesRegex(ValueError,'extrusion'):_apply(spec,[annotation])

    def test_opening_comparison_does_not_match_different_facade_planes(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            revised,_=_apply(spec,[self.annotation(row,'placement',translation_m=[0,0,0],rotation_degrees=90)])
            config={'version':'reconstruction-benchmark-v1','dataset_kind':'synthetic','coordinate_frame':FRAME,'units':'metres',
                'cases':[{'id':'plane-check','building_id':row['building_id'],'source_sha256':row['source_sha256'],
                    'reference':{'review_basis':'independent_review','review_reference':'Synthetic comparison-plane fixture',
                        'geometry_definition':'projected_xy_bounds_origin_v1','component_id':'front-wall','opening_projection':'xz',
                        'geometry':{'footprint_m':[[0,0],[8,0],[8,.3],[0,.3]],'height_m':4,'position_m':[0,0,0],
                            'openings_m':[[[1,1],[2,1],[2,2],[1,2]]]}},'prediction':None}]}
            config['reference_sha256']=reference_digest(config)
            before,after=_benchmarks(config,spec,revised,row,None)
            self.assertEqual(before['summary']['cases_within_thresholds'],1)
            self.assertEqual(after['summary']['incomplete_predictions'],1)
            self.assertIsNone(after['cases'][0]['metrics']['openings'])
            self.assertEqual(after['summary']['cases_within_thresholds'],0)
            config['lineage']={'training_buildings':[],'evaluation_buildings':[],
                'training_sources':row['source_sha256'],'evaluation_sources':[]}
            with self.assertRaisesRegex(ValueError,'overlap'):_benchmarks(config,spec,revised,row,None)

    def test_interior_window_remains_component_bound_for_a_later_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            session,row=self.fixture(Path(tmp));spec=row['candidate']['spec']
            window=self.annotation(row,'opening',component_id='front-wall',projection='xz',points_m=[[1,1],[3,1],[3,2],[1,2]])
            revised,_=_apply(spec,[window])
            self.assertNotIn('native_air_halves',revised)
            dimension=self.annotation(row,'dimension',component_id='front-wall',axis='x',value_m=10)
            next_revision,_=_apply(revised,[dimension])
            self.assertEqual(max(p[0] for p in next_revision['components'][0]['geometry']['holes'][0]),3.75)
            from voxel_mapper.building_native import compile_spec
            self.assertTrue(compile_spec(next_revision)[1]['protected_air_verified'])


if __name__=='__main__':unittest.main()
