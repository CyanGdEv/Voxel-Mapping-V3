import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf

from voxel_mapper import automatic_facade_preview as preview
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


class FacadePreviewTests(unittest.TestCase):
    def artwork(self):
        def marker(key, point):
            return {'id':str(key)+str(point),'key':['P',26,key], 'center_pdf_native':point,
                    'sheet_trace_index':key*2,'outside_trace_indices':[key*2+1],
                    'status':'original_numbered_artwork_reference_candidate', 'font_sizes_points':[8.,8.], 'radius_page_points':10.}
        a={'document_sha256':'a','page':1,'markers':[marker(1,[10.,20.]),marker(2,[30.,40.])]}
        b={'document_sha256':'b','page':1,'markers':[marker(1,[10.,20.]),marker(2,[30.,40.])]}
        pair={'id':'pair','status':'supported_non_target_artwork_layout_only','controls':[{'key':['P',30,1]}],
              'subject_page_key':['a',1],'reference_page_key':['b',1], 'reference_to_subject_linear_row_matrix':[[1.,0.],[0.,1.]],
              'subject_to_reference_linear_row_matrix':[[1.,0.],[0.,1.]],'reference_to_subject_translation':[0.,0.], 'apparent_subject_artwork_scale':1.}
        return {'excluded_target_sheet_keys':[['P',26]],'pages':[a,b],'pairs':[pair]}

    def test_target_check_never_refits_and_displacement_stays_a_failure(self):
        a=self.artwork();a['pages'][0]['markers'][0]['center_pdf_native'][0]+=2
        before=copy.deepcopy(a);rows=preview.target_checks(a,lambda:None)
        self.assertEqual(a,before);self.assertEqual(rows[0]['status'],'fixed_layout_target_annotation_mismatch')
        self.assertEqual(rows[0]['residual_pdf_points'],2.);self.assertTrue(all(not r['fit_used'] for r in rows))
        self.assertEqual(rows[1]['status'],'fixed_non_target_layout_agrees_at_target_annotation')
        a['pairs'][0]['controls'][0]['key']=['P',26,1]
        with self.assertRaisesRegex(ValueError,'entered'):preview.target_checks(a,lambda:None)

    def test_hidden_missing_duplicate_and_inconsistent_size_targets_are_not_used(self):
        for mode in ('hidden','missing','duplicate','font','radius'):
            with self.subTest(mode=mode):
                a=self.artwork();m=a['pages'][1]['markers'][0]
                if mode=='hidden':m['status']='whole_visible_unique_plan_reference_required'
                if mode=='missing':a['pages'][1]['markers'].pop(0)
                if mode=='duplicate':a['pages'][1]['markers'].append({**copy.deepcopy(m),'center_pdf_native':[11.,20.]})
                if mode=='font':m['font_sizes_points']=[9.,8.]
                if mode=='radius':m['radius_page_points']=11.
                row=preview.target_checks(a,lambda:None)[0]
                self.assertNotEqual(row['status'],'fixed_non_target_layout_agrees_at_target_annotation')
                if mode in ('hidden','missing','duplicate'):self.assertNotIn('residual_pdf_points',row)

    def test_coincident_target_paints_keep_all_receipts(self):
        a=self.artwork();a['pages'][0]['markers'].append(copy.deepcopy(a['pages'][0]['markers'][0]))
        row=preview.target_checks(a,lambda:None)[0]
        self.assertEqual(len(row['subject_marker_ids']),2);self.assertFalse(row['physical_scale_verified'])

    def band(self, gray):return preview.bottom_bands(gray,[10.,10.,40.,80.],[2.,0.,0.],.1,lambda:None)

    def test_base_band_detected_but_not_assigned_as_threshold_or_trimmed_to_level(self):
        gray=np.full((200,120),255,np.uint8);gray[140:144,20:80]=0
        row=self.band(gray);self.assertEqual(row['status'],'cross_threshold_source_base_band_candidate')
        self.assertEqual(row['candidate_bottom_display_interval'],[70.,72.]);self.assertEqual(len(row['bands']),2)
        self.assertIsNone(row['selected_physical_bottom_m']);self.assertFalse(row['physical_threshold_verified'])

    def test_missing_partial_multiple_or_search_edge_bands_stay_unresolved(self):
        for mode in ('none','partial','multiple','edge'):
            gray=np.full((200,120),255,np.uint8)
            if mode=='partial':gray[140:144,35:45]=0
            if mode=='multiple':gray[140:144,:]=0;gray[150:152,:]=0
            if mode=='edge':gray[90:94,:]=0
            row=self.band(gray);self.assertIsNone(row['candidate_bottom_display_interval'])
            self.assertEqual(row['status'],'source_base_band_missing_or_ambiguous')
        self.assertEqual(self.band(np.full((100,120),255,np.uint8))['status'],'bottom_band_search_crosses_source_crop')

    def test_mesh_is_source_relative_context_with_unknown_thickness_and_no_aperture(self):
        mesh=preview.context_mesh([0,10,100,100],[20,30,30,100],[1.,0.,0.,1.,0.,0.],.1,80.)
        self.assertEqual(mesh['context_vertices'][0],[0.,0.,-2.]);self.assertEqual(mesh['opening_outline_vertices'][0],[2.,0.,-2.])
        self.assertEqual(mesh['opening_outline_vertices'][3],[2.,0.,5.]);self.assertEqual(mesh['aperture_triangles'],[])
        for key in ('wall_thickness_m','physical_opening_bottom_m','physical_opening_height_m','physical_wall_height_m'):self.assertIsNone(mesh[key])
        with self.assertRaises(ValueError):preview.context_mesh([0,10,100,100],[20,30,30,100],[1.,.1,0.,1.,0.,0.],.1,80.)
        with self.assertRaises(ValueError):preview.context_mesh([0,10,100,100],[20,30,130,100],[1.,0.,0.,1.,0.,0.],.1,80.)

    def fixture(self, root):
        components=root/'components';views=root/'views';corpus=root/'corpus';(corpus/'files').mkdir(parents=True)
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=200)
            page.draw_line((20,30),(20,80));page.draw_line((30,30),(30,80));page.draw_line((20,30),(30,30))
            page.draw_line((0,80),(100,80),width=1.)
            raw=doc.tobytes()
        sha=hashlib.sha256(raw).hexdigest();(corpus/'files'/(sha+'.pdf')).write_bytes(raw)
        source={'document_sha256':sha,'page':1,'views':[{'id':'floor'},{'id':'roof'},{'id':'elevation'}]}
        gap={'id':'gap','gap_endpoints_pdf_native':[[20.,50.],[30.,50.]]}
        inventories=[{'view_id':v['id'],'source_view_sha256':digest(v), 'nominal_metres_per_pdf_point':.1,
                      'printed_claim':{'printed_state':'unspecified'},'caption':v['id'],'plan_gap_review':{'gaps':[gap]}} for v in source['views']]
        ipins={i['view_id']:digest(i) for i in inventories}
        buildings={'source_inventory_sha256':ipins,'frames':[{'id':'record','plan_view_id':'floor','target_elevation_view_ids':['elevation'],'target_view_key_candidate':['P',26,1]}]}
        parent={'id':'parent','residual_family_id':'parent','witnesses':[{'source_bounds_pixels':[0,10,100,100],'variant_index':0,'pair_index':0}]}
        child={'id':'child','witnesses':[{'source_bounds_pixels':[20,30,30,100],'variant_index':0,'pair_index':1}]}
        level={'view_id':'elevation','pixel_edge_to_source_display_matrix':[1.,0.,0.,1.,0.,0.], 'relative_reference':{'datum_y_display_points':80.},'families':[parent,child]}
        levels={'source_inventory_sha256':ipins,'source_building_links_sha256':digest(buildings),'views':[level]}
        alignment={'source_inventory_sha256':ipins};scale={'source_inventory_sha256':ipins}
        prior={'id':'prior','parent_family_review_id':'parent','child_family_review_id':'child','source_gap_projection':{'source_gap_sha256':digest(gap)}}
        old={'source_corner_pair_id':'corner','facade_record_id':'record','position_comparisons':[prior]}
        returns={'source_inventory_sha256':ipins,'diagnostics':[old]}
        symbols={'source_inventory_sha256':ipins,'conditional_position_links':[{'source_position_comparison_id':'prior','source_position_comparison_sha256':digest(prior)}]}
        artwork=self.artwork();artwork['pages']=artwork['pages'][:1];artwork['pages'][0].update(document_sha256=sha,source_page_views_sha256=digest(source))
        artwork['pairs'][0].update(subject_page_key=[sha,1],reference_page_key=[sha,1])
        artwork.update(source_inventory_sha256=ipins,diagnostics=[{'pair_id':'pair','source_return_diagnostic_sha256':digest(old),
          'source_axis_pdf_native':[1.,0.],'source_points_pdf_native':[[0.,50.],[100.,50.]],'nominal_metres_per_pdf_point':.1,
          'source_corner_pair_id':'corner','nominal_span_m':10.,'outside_all_control_hull':True,
          'width_comparisons':[{'status':'all_witness_extent_widths_compatible','parent_family_review_id':'parent'}]}])
        reviews=dict(building_facade_links=buildings,elevation_level_context=levels,facade_alignment=alignment,sheet_scale_evidence=scale,
          wall_return_corners=returns,door_symbol_evidence=symbols,artwork_scale_controls=artwork)
        report={'contract':{'version':'automatic-view-component-inventory-v11'},'results':[],'output_sha256':{}}
        for inv in inventories:
            name=inv['view_id']+'.json';atomic_json(components/name,inv);report['results'].append({'view_id':inv['view_id'],'file':name});report['output_sha256'][name]=file_hash(components/name)
        for key,value in reviews.items():
            name=key+'.json';atomic_json(components/name,value);report[key]={'file':name};report['output_sha256'][name]=file_hash(components/name)
        atomic_json(views/'view-candidates.json',{'pages':[source]})
        atomic_json(views/'view-report.json',{'contract':{'source_sha256':[sha]},'output_sha256':{'view-candidates.json':file_hash(views/'view-candidates.json')}})
        report['contract'].update(view_report_sha256=file_hash(views/'view-report.json'),view_candidates_sha256=file_hash(views/'view-candidates.json'))
        atomic_json(components/'component-report.json',report)
        return components,views,corpus,root/'output'

    def test_original_pdf_end_to_end_both_parities_and_deterministic_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));result=preview.build(*args)
            self.assertEqual(result['counts']['source_linked_alternatives'],1);self.assertEqual(result['counts']['positions_compatible'],1)
            self.assertEqual(len(result['position_checks']),2);self.assertTrue(result['previews'][0]['outside_non_target_control_hull'])
            self.assertEqual(result['counts']['base_band_candidate_crops'],1)
            self.assertEqual(result,preview.build(*args));self.assertFalse(result['world_placement_eligible'])
            self.assertEqual(result['accepted_physical_components'],0)

    def test_early_and_late_budget_holds_discard_all_partial_geometry_and_crops(self):
        for limit in (1,5,20):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));r=preview.build(*args,max_checks=limit)
                self.assertEqual(r['status'],'facade_preview_budget_withheld');self.assertEqual(r['previews'],[])
                self.assertEqual(r['target_marker_checks'],[]);self.assertEqual(r['position_checks'],[]);self.assertEqual(r['source_crop_receipts'],[])
                self.assertFalse(list(Path(r['directory']).rglob('*.png')))
        for value in (0,True,100001):
            with self.assertRaises(ValueError):preview.build('','','','',max_checks=value)

    def test_changed_pdf_artifact_missing_pin_or_stale_chain_fails_before_output(self):
        for mode in ('pdf','artifact','pin','chain','duplicate'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));c,v,corpus,out=args;r=json.loads((c/'component-report.json').read_text())
                if mode=='pdf':
                    p=next((corpus/'files').glob('*.pdf'));p.write_bytes(p.read_bytes()+b' ')
                if mode=='artifact':(c/'floor.json').write_text('{}')
                if mode=='pin':r['output_sha256'].pop('floor.json');atomic_json(c/'component-report.json',r)
                if mode=='chain':
                    path=c/'door_symbol_evidence.json';d=json.loads(path.read_text());d['source_inventory_sha256']={};atomic_json(path,d)
                    r['output_sha256'][path.name]=file_hash(path);atomic_json(c/'component-report.json',r)
                if mode=='duplicate':
                    r['results'].append(r['results'][0]);atomic_json(c/'component-report.json',r)
                with self.assertRaises(ValueError):preview.build(*args)
                self.assertFalse(out.exists())

    def test_tampered_cached_preview_or_source_crop_is_rejected(self):
        for mode in ('json','png'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));r=preview.build(*args);root=Path(r['directory'])
                if mode=='json':(root/'facade-preview.json').write_text('{}')
                else:next(root.rglob('*.png')).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'Existing'):preview.build(*args)


if __name__=='__main__':unittest.main()
