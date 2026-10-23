import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from voxel_mapper import source_gradient_fascia as fascia
from voxel_mapper import pyramid_fascia_evidence as evidence
from voxel_mapper import pyramidal_roof_evidence as parent
from voxel_mapper.pyramidal_roof_topology import discover
from tests import test_pyramidal_roof_evidence as parent_tests


class SourceGradientFasciaTests(unittest.TestCase):
    def image(self):
        gray=np.full((100,120),225,np.uint8);gray[40:66,50]=150
        return gray,np.zeros_like(gray,bool)

    def fixture(self,root):
        args=parent_tests.PyramidalRoofTests().fixture(root);result=parent.build(*args)
        return Path(result['directory']),*args[:-1],root/'contrast-fascia'

    def candidate(self):return discover(parent_tests.PyramidalRoofTests().graph(),lambda:None)['candidates'][0]

    def configurations(self):
        candidate=self.candidate();models=[]
        for threshold in (220,235):
            for contrast in (32,64):
                s=parent_tests.PyramidalRoofTests().silhouette(candidate,threshold);s.update(id=f'{threshold}-{contrast}',source_gradient_contrast=contrast)
                s['mesh']=parent.mesh(candidate,s);s['observed_fascia_mesh']={'observed_corner_depths_nominal_m':[.5,.6]};models.append(s)
        return models

    def test_flat_background_merging_ink_does_not_hide_original_contrast_edge(self):
        gray,mask=self.image();before=gray.copy()
        self.assertEqual(parent.literal_columns(gray,mask,235,lambda:None),[])
        for threshold in (220,235):
            for contrast in (32,64):
                r=fascia.columns(gray,mask,threshold,contrast,lambda:None)
                self.assertEqual(len(r['source_fascia_columns']),1);column=r['source_fascia_columns'][0]
                self.assertEqual(column['source_y_interval_pixels'],[40,65]);self.assertFalse(column['source_pixels_clipped_to_prediction'])
        np.testing.assert_array_equal(before,gray)

    def test_neighbour_receipts_and_single_dark_pixel_centres_are_original(self):
        gray,mask=self.image();column=fascia.columns(gray,mask,235,64,lambda:None)['source_fascia_columns'][0]
        self.assertEqual(len(column['source_pixels']),26)
        self.assertTrue(all(p['gray']==150 and p['left_original_gray']==p['right_original_gray']==225 and p['maximum_original_neighbour_difference']==75 for p in column['source_pixels']))

    def test_flat_ink_and_bright_low_contrast_never_become_supported_edges(self):
        gray=np.full((100,120),225,np.uint8);mask=np.zeros_like(gray,bool)
        self.assertEqual(fascia.columns(gray,mask,235,32,lambda:None)['source_fascia_columns'],[])
        gray[40:66,50]=210
        self.assertEqual(fascia.columns(gray,mask,235,32,lambda:None)['source_fascia_columns'],[])

    def test_original_row_gaps_are_retained_and_large_gaps_are_not_filled(self):
        gray,mask=self.image();gray[52,50]=225
        column=fascia.columns(gray,mask,235,64,lambda:None)['source_fascia_columns'][0]
        self.assertEqual(column['unsupported_row_intervals'],[[52,53]]);self.assertFalse(column['source_gaps_filled'])
        gray[50:56,50]=225;self.assertEqual(fascia.columns(gray,mask,235,64,lambda:None)['source_fascia_columns'],[])

    def test_excluded_centres_or_contrast_neighbours_cannot_supply_evidence(self):
        for x in (49,50,51):
            gray,mask=self.image();mask[40:66,x]=True
            self.assertEqual(fascia.columns(gray,mask,235,64,lambda:None)['source_fascia_columns'],[])

    def test_cropped_raster_edges_are_not_invented_contrast_witnesses(self):
        gray,mask=self.image();gray[:,50]=225;gray[:26,50]=150;gray[40:66,0]=150
        self.assertEqual(fascia.columns(gray,mask,235,64,lambda:None)['source_fascia_columns'],[])

    def test_invalid_raster_masks_and_configuration_are_rejected(self):
        gray,mask=self.image()
        for image,excluded,t,c in ((gray.astype(float),mask,220,32),(gray,mask.astype('uint8'),220,32),(gray,mask[:10],220,32),(gray,mask,250,32),(gray,mask,220,16)):
            with self.assertRaises(ValueError):fascia.columns(image,excluded,t,c,lambda:None)

    def test_source_column_budget_and_charged_work_stop_without_partial_return(self):
        gray=np.full((100,3000),225,np.uint8)
        for y in (5,35,65):gray[y:y+20,1::2]=150
        with self.assertRaises(OverflowError):fascia.columns(gray,np.zeros_like(gray,bool),235,64,lambda:None)
        gray,mask=self.image();count=0
        def charge():
            nonlocal count
            count+=1
            if count>10:raise OverflowError('bounded')
        with self.assertRaises(OverflowError):fascia.columns(gray,mask,235,64,charge)

    def test_finite_aim_identifies_only_its_first_original_perimeter_edge(self):
        c=self.candidate();r=fascia.observed_edges(c,{'diagnostic_aim_segment_pdf_native':[[50.,230.],[50.,90.]]},[],lambda:None)
        self.assertEqual(r['status'],'conditional_original_observed_edge');self.assertEqual(len(r['intersections']),2)
        self.assertEqual(r['first_edge_candidates'][0]['source_edge_index'],2);self.assertFalse(r['diagnostic_reach_changed'])

    def test_vertex_entry_inside_start_and_missing_ray_remain_held(self):
        for segment in ([[50.,150.],[50.,230.]],[[150.,250.],[50.,150.]],[[150.,230.],[150.,150.]]):
            r=fascia.observed_edges(self.candidate(),{'diagnostic_aim_segment_pdf_native':segment},[],lambda:None)
            self.assertEqual(r['status'],'observed_edge_ambiguous_or_missing')

    def test_observed_strip_preserves_separate_depths_and_only_one_plan_edge(self):
        c=self.candidate();s=parent_tests.PyramidalRoofTests().silhouette(c);s['source_level_pixel']=100.
        m={'mesh':parent.mesh(c,s)};columns=[{'id':'left','source_y_interval_pixels':[70,80]},{'id':'right','source_y_interval_pixels':[68,83]}]
        strip=fascia.fascia_mesh(c,m,s,{'source_fascia_column_ids':['left','right']},columns,2,.1)
        np.testing.assert_allclose(strip['observed_corner_depths_nominal_m'],[1.5,1.0],atol=1e-12)
        self.assertEqual(strip['vertices'][0],m['mesh']['vertices'][2]);self.assertEqual(strip['vertices'][3],m['mesh']['vertices'][3])
        self.assertEqual(strip['triangles'],[[0,1,2],[0,2,3]]);self.assertFalse(strip['depth_transferred_to_other_edges']);self.assertIsNone(strip['wall_mesh'])

    def test_four_configurations_need_actual_comparisons_and_preserve_disagreement(self):
        models=self.configurations();coverage,checks=evidence.stability(models,lambda:None)
        self.assertEqual(len(checks),6);self.assertEqual(coverage[0]['status'],'four_source_configurations_support_inspection')
        self.assertFalse(coverage[0]['physical_acceptance_authorized'])
        models[-1]['mesh']['vertices'][4][2]+=1.
        self.assertEqual(evidence.stability(models,lambda:None)[0][0]['status'],'source_configuration_support_held')

    def test_missing_contrast_or_observed_strip_never_passes_stability(self):
        models=self.configurations();coverage,_=evidence.stability(models[:-1],lambda:None)
        self.assertEqual(coverage[0]['missing_configurations'],['235/64'])
        models[-1]['observed_fascia_mesh']=None
        self.assertEqual(evidence.stability(models,lambda:None)[0][0]['status'],'source_configuration_support_held')

    def test_complete_replay_keeps_parent_bytes_and_source_holds_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));path=args[0]/'pyramidal-roof-evidence.json';before=path.read_bytes();r=evidence.build(*args)
            self.assertEqual(r,evidence.build(*args));self.assertEqual(path.read_bytes(),before)
            self.assertEqual(r['world_geometry_additions'],0);self.assertFalse(r['wall_closure_authorized']);self.assertFalse(r['previous_source_holds_overridden'])

    def test_early_and_late_stage_overflow_clear_all_partial_results(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp))
            for target in ('stability','open_joins'):
                if target=='stability':manager=patch.object(evidence,'stability',side_effect=OverflowError('early'))
                else:manager=patch.object(evidence,'open_joins',side_effect=OverflowError('late'))
                with manager:r=evidence.build(*args[:-1],Path(temp)/('out-'+target))
                self.assertEqual(r['status'],'source_gradient_fascia_budget_withheld');self.assertTrue(all(v==0 for v in r['counts'].values()))

    def test_saved_output_cache_and_original_parent_crop_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args);(Path(r['directory'])/'pyramid-fascia-evidence.json').write_text('{}')
            with self.assertRaises(ValueError):evidence.build(*args)
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));next((args[2]/'views').rglob('view.png')).write_bytes(b'changed')
            with self.assertRaises(ValueError):evidence.build(*args)

    def test_crop_changed_during_final_comparison_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));original=evidence.stability
            def change(*values):
                r=original(*values);p=next((args[2]/'views').rglob('view.png'));p.write_bytes(p.read_bytes()+b'changed');return r
            with patch.object(evidence,'stability',side_effect=change):
                with self.assertRaises(ValueError):evidence.build(*args)

    def test_independent_audit_replays_the_unchanged_parent_chain(self):
        from scripts.audit_pyramid_fascia_evidence import audit
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));result=evidence.build(*args)
            receipt=audit(result['directory'],*args[:-1],Path(temp)/'audit.json')
            self.assertEqual(receipt['status'],'passed');self.assertTrue(receipt['fresh_replay_identical'])
