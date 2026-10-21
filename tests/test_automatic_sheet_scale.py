import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.geometry import MultiPoint, box, shape

from tests import test_automatic_facade_alignment as facade_fixtures
from voxel_mapper import automatic_facade_alignment, automatic_sheet_scale as scale
from voxel_mapper.reconstruction_evidence_queue import digest


class AutomaticSheetScaleTests(unittest.TestCase):
    def document(self, subject, *, factor=.9, duplicate=False, hidden=False, displaced=False, project='1234'):
        document=pymupdf.open();page=document.new_page(width=1000,height=800)
        for i in range(12):
            x,y=40+(i%4)*150,30+(i//4)*45
            if subject:x,y=x*factor+15,y*factor+20
            if subject and displaced and i==0:x+=1
            page.insert_text((x,y),'Furniture '+chr(65+i),fontsize=10*(factor if subject else 1),
                             render_mode=3 if subject and hidden and i==0 else 0)
        if subject and duplicate:page.insert_text((650,400),'Furniture A',fontsize=10)
        page.insert_text((820,740),project+('-21' if subject else '-48'),fontsize=11)
        if subject:
            for y,text in [(400,'5000'),(440,'5 m'),(480,'Shop Level + 182.50'),(520,'182500'),(560,'GIA 170m2')]:
                page.insert_text((400,y),text,fontsize=10)
        return document

    def pages(self, **options):
        subject=self.document(True,**options);reference=self.document(False)
        source={'document_sha256':'a'*64,'page':1,'views':[]};other={'document_sha256':'b'*64,'page':1,'views':[]}
        return subject,reference,source,other

    def test_original_text_discovery_selects_fixed_roles_before_fit_and_preserves_source(self):
        subject,reference,source,other=self.pages()
        try:
            before=subject.tobytes(no_new_id=True)
            a=scale.page_review(subject[0],source,lambda:None);b=scale.page_review(reference[0],other,lambda:None)
            result=scale.compare_pages(a,b,lambda:None)
            self.assertEqual(result['status'],'supported_furniture_layout_correspondence_only')
            self.assertEqual([r['role'] for r in result['terms']],['holdout','fit','fit']*4)
            self.assertAlmostEqual(result['layout_fit']['apparent_subject_layout_scale'],.9,places=5)
            self.assertEqual(result['layout_fit']['holdout_anchor_count'],4)
            self.assertEqual(subject.tobytes(no_new_id=True),before)
            self.assertFalse(result['physical_scale_verified']);self.assertFalse(result['geometry_correction_applied'])
        finally:subject.close();reference.close()

    def test_interior_duplicates_and_hidden_text_are_excluded_before_roles_without_outlier_selection(self):
        for option in ('duplicate','hidden'):
            subject,reference,source,other=self.pages(**{option:True})
            try:
                result=scale.compare_pages(scale.page_review(subject[0],source,lambda:None),scale.page_review(reference[0],other,lambda:None),lambda:None)
                self.assertEqual(result['excluded_before_role_assignment'],['Furniture A'])
                self.assertEqual(result['status'],'twelve_to_sixty_four_unique_visible_peripheral_terms_required')
                self.assertEqual(result['terms'],[])
            finally:subject.close();reference.close()

    def test_displaced_holdout_is_not_dropped_to_rescue_the_fit(self):
        subject,reference,source,other=self.pages(displaced=True)
        try:
            result=scale.compare_pages(scale.page_review(subject[0],source,lambda:None),scale.page_review(reference[0],other,lambda:None),lambda:None)
            self.assertEqual(result['status'],'withheld_layout_correspondence')
            self.assertEqual(result['layout_fit']['holdout_anchor_count'],4)
            self.assertGreater(result['layout_fit']['holdout_max_residual_pdf_points'],.25)
        finally:subject.close();reference.close()

    def test_length_text_numbers_levels_and_areas_never_become_figured_facade_dimensions(self):
        with self.document(True) as document:
            result=scale.page_review(document[0],{'document_sha256':'a'*64,'page':1,'views':[]},lambda:None)
        self.assertEqual({r['text'] for r in result['dimension_text']},{'5000','5 m','182500'})
        self.assertTrue(all(not r['component_dimension_verified'] for r in result['dimension_text']))
        self.assertTrue(all(not r['whole_automatic_view_ids'] for r in result['dimension_text']))
        self.assertFalse(result['figured_facade_dimensions_verified'])

    def test_different_project_and_nonstandard_page_units_do_not_support_a_layout(self):
        subject,reference,source,other=self.pages(project='5678')
        try:
            a=scale.page_review(subject[0],source,lambda:None);b=scale.page_review(reference[0],other,lambda:None)
            self.assertEqual(scale.compare_pages(a,b,lambda:None)['status'],'independent_visible_same_project_sheets_required')
            subject.xref_set_key(subject[0].xref,'UserUnit','2')
            self.assertFalse(scale.page_review(subject[0],source,lambda:None)['standard_page_frame'])
        finally:subject.close();reference.close()

    def fixture(self, root, factor=.9):
        sources,inventories,buildings,levels=facade_fixtures.FacadeAlignmentTests().fixture()
        alignment=automatic_facade_alignment.run(sources,inventories,buildings,levels)
        (root/'files').mkdir()
        documents=[]
        for subject in (True,False):
            with self.document(subject,factor=factor) as document:data=document.tobytes()
            sha=hashlib.sha256(data).hexdigest();(root/'files'/(sha+'.pdf')).write_bytes(data);documents.append(sha)
        sources[0].update(document_sha256=documents[0],page=1)
        for view in sources[0]['views']:
            view['printed_claim']={'view_kind':'plan' if view['id']=='p' else 'elevation'}
            next(v for v in inventories if v['view_id']==view['id'])['source_view_sha256']=digest(view)
        roof={'id':'roof','geometry':box(0,0,1000,800).__geo_interface__,
              'printed_claim':{'view_kind':'plan','plan_level_or_form':'roof'},'nominal_metres_per_pdf_point':.05}
        sources.append({'document_sha256':documents[1],'page':1,'views':[roof]})
        inventories.append({'view_id':'roof','source_view_sha256':digest(roof)})
        pins={v['view_id']:digest(v) for v in inventories}
        buildings['source_inventory_sha256']=pins;levels['source_inventory_sha256']=pins
        levels['source_building_links_sha256']=digest(buildings)
        alignment.update(source_inventory_sha256=pins,source_building_links_sha256=digest(buildings),source_level_context_sha256=digest(levels))
        return SimpleNamespace(root=root),sources,inventories,buildings,levels,alignment

    def test_automatic_pipeline_retains_raw_comparisons_and_limits_layout_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=self.fixture(Path(temporary));before=copy.deepcopy(args[1:]);result=scale.run(*args)
            self.assertEqual(args[1:],before)
            self.assertEqual(result['counts']['supported_layout_pairs'],1)
            self.assertEqual(result['counts']['diagnostic_extent_comparisons'],2)
            self.assertEqual(result['counts']['diagnostic_widths_compatible'],0)
            self.assertEqual(result['counts']['evidence_requirements'],2)
            for diagnostic in result['diagnostics']:
                self.assertTrue(all(e['requires_artwork_extrapolation'] for e in diagnostic['extents']))
                self.assertTrue(all(not c['layout_application_verified'] for c in diagnostic['width_comparisons']))
            self.assertEqual(result['world_geometry_additions'],0);self.assertFalse(result['position_alignment_verified'])

    def test_even_compatible_layout_diagnostics_require_independent_physical_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=scale.run(*self.fixture(Path(temporary),factor=1.))
            self.assertEqual(result['counts']['diagnostic_widths_compatible'],2)
            self.assertTrue(all(not r['automatic_geometry_authorized'] for r in result['evidence_requirements']))
            self.assertFalse(result['physical_scale_verified']);self.assertFalse(result['layout_application_verified'])

    def test_inverse_layout_projects_original_vertices_without_replacing_holes_or_parts(self):
        fixture=facade_fixtures.FacadeAlignmentTests().fixture();original=automatic_facade_alignment.run(*fixture)
        extents=original['frames'][0]['frame_reviews'][0]['plan_extents'];before=copy.deepcopy(extents)
        frame=fixture[2]['frames'][0]['frame_review']['frames'][0]
        for extent in extents:
            result=scale.diagnostic_extent(extent,frame,np.eye(2)/.9,.05,MultiPoint([(0,0),(1,0),(0,1)]).convex_hull,lambda:None)
            self.assertAlmostEqual(result['nominal_plan_position_interval_m'][1]-result['nominal_plan_position_interval_m'][0],11.)
            self.assertEqual(result['source_geometry_sha256'],digest(extent['geometry_pdf_native']))
            for proof in result['diagnostic_extreme_vertices']:
                geometry=shape(extent['geometry_pdf_native']);part=list(geometry.geoms)[proof['part_index']] if geometry.geom_type=='MultiPolygon' else geometry
                self.assertEqual(list(part.exterior.coords[proof['exterior_vertex_index']]),proof['point_pdf_native'])
        self.assertEqual(extents,before)

    def test_early_and_late_budget_failure_discards_all_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=self.fixture(Path(temporary));result=scale.run(*args,max_checks=1)
            self.assertEqual(result['status'],'sheet_scale_budget_withheld');self.assertEqual(result['pages'],[])
            original=scale.diagnostic_extent;calls=[]
            def late(*args):
                calls.append(1)
                if len(calls)==2:raise OverflowError('sheet_scale_work_budget')
                return original(*args)
            with patch.object(scale,'diagnostic_extent',side_effect=late):result=scale.run(*args)
            self.assertEqual(result['diagnostics'],[]);self.assertEqual(result['pairs'],[])
            self.assertEqual(result['evidence_requirements'],[]);self.assertEqual(result['pages'],[])

    def test_stale_duplicate_and_incomplete_inputs_cannot_reuse_a_scale_relation(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=self.fixture(Path(temporary));args[2][0]['changed']=True
            with self.assertRaisesRegex(ValueError,'Matching source inventory'):scale.run(*args)
            args[2][0].pop('changed');args[1][0]['views'].append(copy.deepcopy(args[1][0]['views'][0]))
            with self.assertRaisesRegex(ValueError,'Matching unique automatic'):scale.run(*args)
            args[1][0]['views'].pop();args[5]['status']='facade_alignment_budget_withheld'
            self.assertEqual(scale.run(*args)['status'],'complete_source_facade_alignment_required')
            for value in (0,True,100001):
                with self.assertRaises(ValueError):scale.run(*args,max_checks=value)

    def test_saved_json_and_independent_original_source_audit_reproduce_layout_and_widths(self):
        from collections import Counter
        from scripts.audit_drawing_view_components import verify_sheet_scale
        with tempfile.TemporaryDirectory() as temporary:
            args=self.fixture(Path(temporary));result=json.loads(json.dumps(scale.run(*args)));checked=Counter()
            verify_sheet_scale(*args,result,checked,100000)
            self.assertEqual(checked['independent_layout_fit_anchors'],8)
            self.assertEqual(checked['independent_layout_holdout_anchors'],4)
            self.assertEqual(checked['independent_layout_threshold_widths'],4)


if __name__=='__main__':unittest.main()
