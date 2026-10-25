"""Collections expose source-local layouts without repeating saved PDF analysis."""
from concurrent.futures import CancelledError
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import planning_collection as collection
from voxel_mapper import web_evidence as web,web_planning_pilot as pilot,web_research
from voxel_mapper.generation_cycles import file_hash
from tests.test_web_evidence import PUBLIC,Response,Session,resolver


def fixture(cache):
    with pymupdf.open() as document:
        page=document.new_page(width=600,height=500)
        page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
        page.insert_text((30,190),'Proposed Ground Floor Plan | 1:100',fontsize=10)
        data=document.tobytes()
    index=b'<html><main>APP/1 <a href="/plan-0.pdf">Drawing 0</a></main></html>'
    for value,body in ((PUBLIC,index),(PUBLIC+'plan-0.pdf',data)):
        web.fetch(value,cache,['example.org'],session=Session([Response(body)]),resolver=resolver)
    return {'version':collection.VERSION,'pilot':{'version':pilot.VERSION,'area_id':'synthetic collection',
        'application_reference':'APP/1','research':{'version':web_research.VERSION,
            'urls':[PUBLIC],'allowed_hosts':['example.org'],'offline':True,'refresh':False}}}


class PlanningCollectionAreaLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache';self.storage=self.root/'state'
        self.config=fixture(self.cache)

    def run_job(self,name='output',**kwargs):
        return collection.run(self.config,self.root/name,self.cache,self.storage,**kwargs)

    def test_new_geometry_and_material_dependencies_change_saved_collection_scope(self):
        original=collection.collection_key(self.config);fingerprint=pilot.planning._implementation
        for module in (pilot.planning.planning_surface_footprints,pilot.planning.planning_area_layout,
                       pilot.planning.paving_palette):
            with self.subTest(module=module.__name__):
                def changed(value):
                    return {'basis':'module_file_bytes','sha256':'f'*64} if value is module else fingerprint(value)
                with patch.object(pilot.planning,'_implementation',side_effect=changed):
                    self.assertNotEqual(collection.collection_key(self.config),original)
        contract=collection.contract(self.config)
        self.assertEqual(contract['surface_footprint_limits'],pilot.planning.planning_surface_footprints.LIMITS)
        self.assertEqual(contract['surface_footprint_search_margin_points'],
            pilot.planning.planning_surface_footprints.SEARCH_MARGIN_POINTS)
        self.assertEqual(contract['area_layout_limits'],pilot.planning.planning_area_layout.LIMITS)

    def test_changed_bounded_analysis_defaults_cannot_reuse_an_earlier_collection(self):
        original=collection.collection_key(self.config)
        for module in (pilot.planning.planning_surface_footprints,pilot.planning.planning_area_layout):
            with self.subTest(module=module.__name__):
                limits=deepcopy(module.LIMITS);key=next(iter(limits));limits[key]=max(1,limits[key]-1)
                with patch.object(module,'LIMITS',limits):
                    self.assertNotEqual(collection.collection_key(self.config),original)

    def test_job_exports_layout_review_counts_and_hashed_source_local_geometry(self):
        result=self.run_job();output=self.root/'output'
        self.assertGreaterEqual(result['summary']['surface_boundary_candidates'],1)
        self.assertGreaterEqual(result['summary']['nominal_area_layout_candidates'],1)
        self.assertGreaterEqual(result['summary']['nominal_area_path_plaza_candidates'],1)
        self.assertEqual(result['summary']['registered_area_layouts'],0)
        self.assertEqual(result['area_layout_review'],'area-layouts.json')
        review=json.loads((output/result['area_layout_review']).read_text())
        self.assertEqual(len(review['pages']),1)
        self.assertEqual(result['area_layout_files'],review['page_layout_files'])
        self.assertEqual(len(result['area_layout_files']),1)
        for entry in result['area_layout_files']:
            self.assertEqual(file_hash(output/entry['file']),entry['sha256'])
            self.assertEqual(file_hash(output/entry['geojson_file']),entry['geojson_sha256'])
            self.assertEqual(result['output_sha256'][entry['file']],entry['sha256'])
        for name in collection.AREA_LAYOUT_COUNTERS:
            self.assertEqual(result['summary'][name],review['summary'][name])
        batch=json.loads((output/'batches/batch-0001/report.json').read_text())
        for name in collection.SURFACE_BOUNDARY_COUNTERS:
            self.assertEqual(result['summary'][name],batch['summary'][name])
        html=(output/'review.html').read_text()
        self.assertIn('area-layouts.html',html);self.assertIn('geographic registration remain unresolved',html)
        layout_html=(output/'area-layouts.html').read_text()
        self.assertIn('<svg',layout_html)
        self.assertTrue(any(name.endswith('.geojson') for name in result['output_sha256']))
        for name,pin in result['output_sha256'].items():
            self.assertEqual(file_hash(output/name),pin,name)
        self.assertFalse(result['world_placement_eligible']);self.assertFalse(result['model_weights_updated'])
        self.assertEqual(result['training_labels_generated'],0);self.assertEqual(result['world_geometry_additions'],0)

    def test_restart_rebuilds_same_layout_review_from_verified_saved_evidence(self):
        first=self.run_job('first')
        def forbidden(*args,**kwargs):raise AssertionError('Saved PDF analysis was repeated')
        second=self.run_job('second',run_batch=forbidden)
        self.assertEqual(second['summary']['new_batches'],0)
        for name in collection.SURFACE_BOUNDARY_COUNTERS+collection.AREA_LAYOUT_COUNTERS:
            self.assertEqual(second['summary'][name],first['summary'][name])
        self.assertEqual((self.root/'first/area-layouts.json').read_bytes(),
                         (self.root/'second/area-layouts.json').read_bytes())

    def test_cancelled_layout_export_keeps_batch_for_restart_without_analysis(self):
        original=pilot.planning.planning_area_layout.write_review
        def cancelled_export(root,pages,**kwargs):
            if Path(root)==self.root/'cancelled':raise CancelledError('layout export cancelled')
            return original(root,pages,**kwargs)
        with patch.object(pilot.planning.planning_area_layout,'write_review',side_effect=cancelled_export):
            with self.assertRaises(CancelledError):self.run_job('cancelled')
        self.assertFalse((self.root/'cancelled/report.json').exists())
        def forbidden(*args,**kwargs):raise AssertionError('Completed source batch was repeated')
        result=self.run_job('resumed',run_batch=forbidden)
        self.assertEqual(result['summary']['new_batches'],0)
        self.assertGreaterEqual(result['summary']['nominal_area_layout_candidates'],1)

    def test_global_export_budget_still_applies_after_area_review(self):
        # A review writer can grow output after the verified batch-copy phase;
        # the collection must withhold its completion receipt in that case.
        original=pilot.planning.planning_area_layout.write_review
        def oversized(root,pages,**kwargs):
            result=original(root,pages,**kwargs)
            if Path(root)==self.root/'bounded':
                (Path(root)/'area-layout-extra.bin').write_bytes(b'x'*2_000_000)
            return result
        self.config['limits']={'max_output_bytes':2_000_000}
        with patch.object(pilot.planning.planning_area_layout,'write_review',side_effect=oversized):
            with self.assertRaises(pilot.planning.PilotBudgetExceeded):self.run_job('bounded')
        self.assertFalse((self.root/'bounded/report.json').exists())
        self.assertTrue((self.storage/'batches/batch-0001/report.json').is_file())


if __name__=='__main__':unittest.main()
