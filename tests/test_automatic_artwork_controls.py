import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box, mapping

from voxel_mapper import automatic_artwork_controls as artwork
from voxel_mapper.reconstruction_evidence_queue import digest


class ArtworkControlTests(unittest.TestCase):
    def controls(self):
        points=[[200,200],[200,800],[800,800],[800,200],[500,500],[1100,800]]
        def page(factor):
            rows=[]
            for i,p in enumerate(points):
                rows.append({'id':str(factor)+'-'+str(i),'key':['P',30 if i<3 else 42,i+1],
                    'center_pdf_native':[factor*p[0]+40,factor*p[1]+60],
                    'sheet_trace_index':2*i,'outside_trace_indices':[2*i+1],
                    'status':'original_numbered_artwork_reference_candidate',
                    'font_sizes_points':[8*factor,8*factor],'radius_page_points':10*factor})
            return {'markers':rows}
        return page(.9),page(1.)

    def fixture(self, root):
        points=[[180,180],[180,780],[780,780],[780,180],[480,480],[1100,780]]
        sources=[];inventories=[];scale_pages=[]
        (root/'files').mkdir()
        for index,factor in enumerate((.9,1.)):
            with pymupdf.open() as document:
                page=document.new_page(width=1400,height=1100)
                for i,(x,y) in enumerate(points):
                    x=x*factor+40;y=y*factor+40;r=10*factor
                    page.draw_circle((x,y),r,width=.25)
                    page.insert_text((x-3.4*factor,y+2*factor),str(30 if i<3 else 42),fontsize=6*factor)
                    page.insert_text((x+r+2*factor,y+r+6*factor),str(i+1),fontsize=5*factor)
                data=document.tobytes()
            sha=hashlib.sha256(data).hexdigest();(root/'files'/(sha+'.pdf')).write_bytes(data)
            view={'id':'plan'+str(index),'document_sha256':sha,'page':1,'geometry':mapping(box(0,0,1400,1100)),
                'printed_claim':{'view_kind':'plan','plan_level_or_form':'groundfloor' if index==0 else 'roof'}}
            sources.append({'document_sha256':sha,'page':1,'views':[view]})
            inventories.append({'view_id':view['id'],'source_view_sha256':digest(view),'nominal_metres_per_pdf_point':.035})
            scale_pages.append({'document_sha256':sha,'page':1,'standard_page_frame':True,
                'sheet_identity':{'project':'P'},'header_glyph_screen':{'status':'raster_consistent_candidate'}})
        elevation={'id':'elevation','document_sha256':sources[0]['document_sha256'],'page':1,
            'geometry':mapping(box(0,0,1,1)),'printed_claim':{'view_kind':'elevation'}}
        sources[0]['views'].append(elevation)
        inventories.append({'view_id':'elevation','source_view_sha256':digest(elevation),'nominal_metres_per_pdf_point':.035})
        for page,source in zip(scale_pages,sources):page['source_page_views_sha256']=digest(source)
        pins={v['view_id']:digest(v) for v in inventories}
        buildings={'source_inventory_sha256':pins,'frames':[{'id':'B','plan_view_id':'plan0',
            'target_view_key_candidate':['P',26,1],'target_elevation_view_ids':['elevation'],
            'frame_review':{'frames':[{'id':'F','diagnostic_axis':[1.,0.]}]}}]}
        parent={'id':'parent','residual_family_id':'parent-source','witnesses':[
            {'source_bounds_pixels':[0,0,111,200],'variant_index':0,'pair_index':1}]}
        levels={'source_inventory_sha256':pins,'source_building_links_sha256':digest(buildings),'views':[{'view_id':'elevation','families':[parent],
            'pixel_edge_to_source_display_matrix':[1.,0.,0.,1.,0.,0.]}]}
        scale={'source_inventory_sha256':pins,'source_building_links_sha256':digest(buildings),'source_level_context_sha256':digest(levels),
            'source_facade_alignment_sha256':'alignment',
            'pages':scale_pages,'pairs':[{'id':'old-pair','subject_page_key':[sources[0]['document_sha256'],1],
                'reference_page_key':[sources[1]['document_sha256'],1]}]}
        returns={'source_inventory_sha256':pins,'source_sheet_scale_sha256':digest(scale),
            'source_building_links_sha256':digest(buildings),'source_level_context_sha256':digest(levels),
            'source_facade_alignment_sha256':'alignment','diagnostics':[{
            'pair_id':'old-pair','facade_record_id':'B','frame_id':'F','source_corner_pair_id':'C','source_corner_pair_sha256':'corners',
            'source_points_pdf_native':[[400.,100.],[500.,100.]],'raw_width_comparisons':[{'parent_family_review_id':'parent'}]}]}
        return SimpleNamespace(root=root),sources,inventories,buildings,levels,scale,returns

    def test_non_target_similarity_has_fixed_roles_and_all_independent_holdouts(self):
        a,b=self.controls();before=copy.deepcopy((a,b));result=artwork.compare(a,b,set(),lambda:None)
        self.assertEqual((a,b),before);self.assertEqual(result['status'],'supported_non_target_artwork_layout_only')
        self.assertEqual([r['role'] for r in result['controls']],['holdout','fit']*3)
        self.assertAlmostEqual(result['apparent_subject_artwork_scale'],.9)
        self.assertEqual(result['fit_control_count'],3);self.assertEqual(result['holdout_control_count'],3)
        m=result['reference_to_subject_linear_row_matrix'];self.assertAlmostEqual(m[0][0],m[1][1]);self.assertAlmostEqual(m[0][1],-m[1][0])
        self.assertFalse(result['physical_scale_verified']);self.assertFalse(result['geometry_correction_applied'])

    def test_displaced_holdout_is_not_removed_or_reassigned(self):
        a,b=self.controls();a['markers'][0]['center_pdf_native'][0]+=5
        result=artwork.compare(a,b,set(),lambda:None)
        self.assertEqual(result['status'],'original_artwork_fit_or_holdouts_disagree')
        self.assertEqual(len(result['controls']),6);self.assertEqual(result['controls'][0]['role'],'holdout')

    def test_target_markers_are_excluded_before_role_assignment_even_if_they_fit(self):
        a,b=self.controls()
        for page in (a,b):
            for i in range(4):page['markers'].append({**copy.deepcopy(page['markers'][i]),'id':'target'+str(i),'key':['P',26,i+1]})
        result=artwork.compare(a,b,{('P',26)},lambda:None)
        self.assertEqual(result['status'],'supported_non_target_artwork_layout_only');self.assertEqual(len(result['controls']),6)
        self.assertEqual(len(result['excluded_controls']),4)
        self.assertTrue(all(r['key'][1]!=26 for r in result['controls']))

    def test_hidden_and_distinct_duplicate_markers_are_excluded_but_coincident_paints_survive(self):
        a,b=self.controls();a['markers'].append({**copy.deepcopy(a['markers'][0]),'id':'repeat'})
        result=artwork.compare(a,b,set(),lambda:None);self.assertEqual(len(result['controls'][0]['subject_marker_ids']),2)
        a['markers'][-1]['center_pdf_native'][0]+=.1
        result=artwork.compare(a,b,set(),lambda:None);self.assertEqual(len(result['controls']),5)
        self.assertEqual(result['excluded_controls'][0]['reason'],'nonunique_printed_reference_occurrences')
        b['markers'][1]['status']='whole_visible_unique_plan_reference_required'
        result=artwork.compare(a,b,set(),lambda:None);self.assertEqual(result['status'],'five_to_sixty_four_non_target_controls_required')

    def test_collinear_one_sheet_and_poorly_spread_controls_are_held(self):
        a,b=self.controls()
        for page in (a,b):
            for i,m in enumerate(page['markers']):m['center_pdf_native']=[100+i*10.,100.]
        self.assertEqual(artwork.compare(a,b,set(),lambda:None)['status'],'noncollinear_artwork_controls_required')
        a,b=self.controls()
        for page in (a,b):
            for m in page['markers']:m['key'][1]=30
        self.assertEqual(artwork.compare(a,b,set(),lambda:None)['status'],'two_independent_non_target_reference_sheets_required')
        a,b=self.controls()
        for page in (a,b):
            for m in page['markers']:m['radius_page_points']=1000
        self.assertEqual(artwork.compare(a,b,set(),lambda:None)['status'],'well_separated_original_fit_controls_required')

    def test_shear_reflection_font_radius_and_nonfinite_inputs_do_not_become_scale_acceptance(self):
        for mode in ('shear','reflection','font','radius','nonfinite'):
            a,b=self.controls()
            for row in a['markers']:
                if mode=='shear':row['center_pdf_native'][0]+=.1*row['center_pdf_native'][1]
                elif mode=='reflection':row['center_pdf_native'][0]*=-1
                elif mode=='font':row['font_sizes_points'][0]*=1.1
                elif mode=='radius':row['radius_page_points']*=1.1
                else:row['center_pdf_native'][0]=float('nan')
            if mode=='nonfinite':
                with self.assertRaises(ValueError):artwork.compare(a,b,set(),lambda:None)
            else:self.assertNotEqual(artwork.compare(a,b,set(),lambda:None)['status'],'supported_non_target_artwork_layout_only')

    def test_original_pdf_controls_and_corner_spans_retain_extrapolation_and_no_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));before=copy.deepcopy(args[1:]);result=artwork.run(*args)
            self.assertEqual(args[1:],before);self.assertEqual(result['counts']['supported_artwork_pairs'],1)
            self.assertEqual(result['counts']['corner_span_diagnostics'],1)
            self.assertEqual(result['counts']['widths_compatible'],1)
            self.assertTrue(result['diagnostics'][0]['outside_all_control_hull'])
            self.assertFalse(result['diagnostics'][0]['source_geometry_changed'])
            self.assertFalse(result['target_artwork_application_verified']);self.assertEqual(result['world_geometry_additions'],0)
            self.assertNotIn('position_comparisons',result['diagnostics'][0])

    def test_whole_view_competitors_and_hidden_pdf_labels_cannot_supply_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));source=args[1][0]
            competitor=copy.deepcopy(source['views'][0]);competitor['id']='competitor';source['views'].append(competitor)
            with pymupdf.open(next((Path(tmp)/'files').glob('*.pdf'))) as document:
                review=artwork.page_controls(document[0],source,'P',lambda:None)
            self.assertTrue(all(m['status']!='original_numbered_artwork_reference_candidate' for m in review['markers']))
            source['views'].pop()
            with pymupdf.open(Path(tmp)/'files'/(source['document_sha256']+'.pdf')) as document:
                page=document[0];traces=[{**t,'opacity':0.} for t in page.get_texttrace()]
                with patch.object(page,'get_texttrace',return_value=traces):review=artwork.page_controls(page,source,'P',lambda:None)
            self.assertTrue(all(m['status']!='original_numbered_artwork_reference_candidate' for m in review['markers']))

    def test_early_late_and_page_pair_budget_holds_discard_every_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));result=artwork.run(*args,max_checks=1)
            self.assertEqual(result['status'],'artwork_control_budget_withheld');self.assertEqual(result['pages'],[])
            with patch.object(artwork,'compare',side_effect=OverflowError('late_control_budget')):result=artwork.run(*args)
            self.assertEqual(result['pages'],[]);self.assertEqual(result['pairs'],[]);self.assertEqual(result['diagnostics'],[])
            args[5]['pairs']*=9;args[6]['source_sheet_scale_sha256']=digest(args[5]);result=artwork.run(*args)
            self.assertEqual(result['reason'],'artwork_page_pair_budget');self.assertEqual(result['pages'],[])

    def test_stale_duplicate_changed_pdf_and_invalid_work_inputs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));args[2][0]['changed']=True
            with self.assertRaisesRegex(ValueError,'Matching original artwork'):artwork.run(*args)
            args[2][0].pop('changed');args[1][0]['views'].append(copy.deepcopy(args[1][0]['views'][0]))
            with self.assertRaisesRegex(ValueError,'Matching unique original'):artwork.run(*args)
            args[1][0]['views'].pop();p=Path(tmp)/'files'/(args[1][0]['document_sha256']+'.pdf');p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'PDF checksum'):artwork.run(*args)
            for limit in (0,True,100001):
                with self.assertRaises(ValueError):artwork.run(*args,max_checks=limit)

        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));competitor=copy.deepcopy(args[1][0]['views'][0]);competitor['id']='deferred-view'
            args[1][0]['views'].append(competitor)
            with self.assertRaisesRegex(ValueError,'Complete original artwork page views'):artwork.run(*args)

    def test_saved_json_independent_audit_checks_original_controls_and_holdouts(self):
        from collections import Counter
        from scripts.audit_artwork_scale_controls import verify
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));result=json.loads(json.dumps(artwork.run(*args)));checked=Counter()
            verify(*args,result,checked,100000)
            self.assertEqual(checked['independent_artwork_holdouts'],3)
            self.assertEqual(checked['independent_artwork_corner_spans'],1)
            self.assertEqual(checked['original_artwork_circles'],12)
            broken=copy.deepcopy(result);broken['pairs'][0]['controls'][0]['subject_center'][0]+=2
            with self.assertRaises(AssertionError):verify(*args,broken,Counter(),100000)


if __name__=='__main__':unittest.main()
