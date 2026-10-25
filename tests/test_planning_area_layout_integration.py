"""Actual planning jobs retain shared source-local building and path hypotheses."""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper import planning_area_pilot as pilot
from voxel_mapper import web_planning_pilot as bridge
from voxel_mapper import web_evidence as web,web_research
from tests.test_web_evidence import PUBLIC,Response,Session,resolver


def fixture(root,*,role='floor-plan'):
    with pymupdf.open() as document:
        page=document.new_page(width=800,height=600)
        page.draw_rect((100,100,220,180));page.insert_text((120,135),'Container',fontsize=10)
        page.draw_rect((220,100,400,180));page.insert_text((270,135),'Footpath',fontsize=10)
        page.insert_text((100,400),'Proposed Ground Floor Plan | 1:100',fontsize=10)
        data=document.tobytes()
    (root/'source.pdf').write_bytes(data);sha=hashlib.sha256(data).hexdigest()
    return {'version':pilot.VERSION,'area_id':'source-local area integration',
        'application_references':['APP/1'],'development_exposure':'previously_inspected',
        'documents':[{'file':'source.pdf','sha256':sha,'title':'Source-local plan',
            'role':role,'drawing_state':'proposed','application_reference':'APP/1'}]}


def web_fixture(cache,caption):
    with pymupdf.open() as document:
        page=document.new_page(width=600,height=500)
        page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
        page.insert_text((30,190),caption,fontsize=10);data=document.tobytes()
    index=b'<html><main>APP/1 <a href="/drawing">Proposed Floor Plan</a></main></html>'
    for value,body in ((PUBLIC,index),(PUBLIC+'drawing',data)):
        web.fetch(value,cache,['example.org'],session=Session([Response(body)]),resolver=resolver)
    return {'version':bridge.VERSION,'area_id':'synthetic area layout web job','application_reference':'APP/1',
        'research':{'version':web_research.VERSION,'urls':[PUBLIC],'allowed_hosts':['example.org'],'offline':True}}


class PlanningAreaLayoutIntegrationTests(unittest.TestCase):
    def test_actual_pilot_exposes_shared_frame_candidates_and_pinned_plan_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);before=(root/'source.pdf').read_bytes();output=root/'output'
            result=pilot.run(config,lambda path:root/path,output)
            self.assertEqual(result['summary']['completed_pages'],1)
            self.assertGreaterEqual(result['summary']['surface_boundary_candidates'],1)
            self.assertGreaterEqual(result['summary']['nominal_area_building_candidates'],1)
            self.assertGreaterEqual(result['summary']['nominal_area_path_plaza_candidates'],1)
            evidence=json.loads((output/result['pages'][0]['evidence_file']).read_text())
            self.assertIsNotNone(evidence['surface_footprints']);layout=evidence['area_layout']
            self.assertTrue(layout['analysis_complete']);self.assertIsNotNone(layout['shared_frame'])
            a,b,c,d,e,f=layout['shared_frame']['native_to_nominal_local_affine']
            for candidate in layout['candidates']:
                native=shape(candidate['geometry_pdf_native'])
                expected=affine_transform(native,[a,c,b,d,e,f])
                self.assertLess(expected.symmetric_difference(shape(candidate['geometry_nominal_local'])).area,1e-8)
                self.assertIsNone(candidate['height_m']);self.assertFalse(candidate['world_placement_eligible'])
            self.assertEqual(result['summary']['nominal_area_boundary_contacts'],1)
            contact=next(row for row in layout['relations'] if row['kind']=='boundary_contact')
            self.assertAlmostEqual(contact['boundary_contact_length_m'],80*100*.0254/72)
            self.assertEqual(contact['gap_m'],0);self.assertIsNone(contact['traversable'])
            self.assertEqual(result['summary']['registered_area_layouts'],0)
            self.assertEqual(result['summary']['reconstructed_buildings'],0)
            self.assertEqual(result['summary']['registered_path_networks'],0)
            self.assertEqual(result['training_labels_generated'],0);self.assertFalse(result['world_placement_eligible'])
            self.assertEqual(result['area_layout_review'],'area-layouts.json')
            self.assertEqual(len(result['area_layout_files']),1)
            entry=result['area_layout_files'][0]
            self.assertEqual(json.loads((output/entry['file']).read_text()),layout)
            for field,pin_field in (('file','sha256'),('geojson_file','geojson_sha256')):
                self.assertEqual(hashlib.sha256((output/entry[field]).read_bytes()).hexdigest(),entry[pin_field])
                self.assertEqual(result['output_sha256'][entry[field]],entry[pin_field])
            self.assertIn('<svg',(output/'area-layouts.html').read_text())
            self.assertIn('area-layouts.html',(output/'review.html').read_text())
            self.assertEqual((root/'source.pdf').read_bytes(),before)
            for relative,pin in result['output_sha256'].items():
                self.assertEqual(hashlib.sha256((output/relative).read_bytes()).hexdigest(),pin)
            implementations=result['contract']['implementations']
            for module in (pilot.planning_surface_footprints,pilot.planning_area_layout,pilot.paving_palette):
                self.assertEqual(implementations[module.__name__],pilot._implementation(module))
            self.assertEqual(result['contract']['surface_footprint_limits'],pilot.planning_surface_footprints.LIMITS)
            self.assertEqual(result['contract']['area_layout_limits'],pilot.planning_area_layout.LIMITS)

    def test_non_plan_roles_do_not_run_new_horizontal_geometry_stages(self):
        for role in ('elevation','section','detail','location-plan','roof-plan'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);config=fixture(root,role=role)
                with (patch.object(pilot.planning_surface_footprints,'page_candidates',side_effect=AssertionError('Not a ground surface plan')),
                      patch.object(pilot.planning_area_layout,'page_layout',side_effect=AssertionError('Not a shared ground plan'))):
                    report=pilot.run(config,lambda path:root/path,root/'output')
                self.assertEqual(report['summary']['completed_pages'],1)
                self.assertEqual(report['summary']['surface_boundary_candidates'],0)
                self.assertEqual(report['summary']['nominal_area_layout_candidates'],0)
                self.assertEqual(report['area_layout_files'],[])

    def test_incomplete_source_inventory_skips_surface_scan_and_retains_layout_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root)
            incomplete={'source_outline_inventory':{'inventory_complete':False,'status':'source_inventory_withheld','records':[]}}
            with (patch.object(pilot.ordinary_surfaces,'page_candidates',return_value=([],[],incomplete)),
                  patch.object(pilot.planning_surface_footprints,'page_candidates',side_effect=AssertionError('Incomplete source inventory'))):
                report=pilot.run(config,lambda path:root/path,root/'output')
            self.assertEqual(report['summary']['completed_pages'],1)
            evidence=json.loads((root/'output'/report['pages'][0]['evidence_file']).read_text())
            self.assertIsNone(evidence['surface_footprints'])
            self.assertFalse(evidence['area_layout']['analysis_complete'])
            self.assertEqual(evidence['area_layout']['candidates'],[])
            self.assertIn('nominal_area_layout_unresolved',report['page_blocker_counts'])
            self.assertEqual(len(report['area_layout_files']),1)
            self.assertEqual(report['area_layout_files'][0]['candidate_count'],0)
            self.assertEqual(report['area_layout_files'][0]['status'],'area_layout_withheld')
            self.assertNotIn('geojson_file',report['area_layout_files'][0])

    def test_new_layout_stage_cancellation_cannot_publish_completed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root)
            with patch.object(pilot.planning_area_layout,'page_layout',side_effect=CancelledError()),self.assertRaises(CancelledError):
                pilot.run(config,lambda path:root/path,root/'output')
            self.assertFalse((root/'output/report.json').exists())

    def test_late_plan_review_growth_is_charged_to_existing_output_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);config['options']={'max_output_bytes':1500000,'render_edge_pixels':200}
            original=pilot.planning_area_layout.write_review
            def oversized(directory,*args,**kwargs):
                result=original(directory,*args,**kwargs)
                (Path(directory)/'extra-plan-review.bin').write_bytes(b'x'*1500001)
                return result
            with patch.object(pilot.planning_area_layout,'write_review',side_effect=oversized),self.assertRaises(pilot.PilotBudgetExceeded):
                pilot.run(config,lambda path:root/path,root/'output')
            self.assertFalse((root/'output/report.json').exists())

    def test_web_job_exposes_plan_counts_links_and_root_relative_file_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';config=web_fixture(cache,'Proposed Ground Floor Plan | 1:100')
            output=root/'output';result=bridge.run(config,output,cache)
            self.assertEqual(result['summary']['completed_pages'],1)
            self.assertGreater(result['summary']['surface_boundary_candidates'],0)
            self.assertGreater(result['summary']['nominal_area_path_plaza_candidates'],0)
            self.assertEqual(result['area_layout_review'],'analysis/area-layouts.json')
            self.assertEqual(len(result['area_layout_files']),1)
            self.assertIn('analysis/area-layouts.html',(output/'review.html').read_text())
            for entry in result['area_layout_files']:
                self.assertTrue(entry['file'].startswith('analysis/'))
                self.assertEqual(result['output_sha256'][entry['file']],entry['sha256'])
                self.assertEqual(result['output_sha256'][entry['geojson_file']],entry['geojson_sha256'])
            self.assertEqual(result['world_geometry_additions'],0);self.assertFalse(result['world_placement_eligible'])

    def test_web_job_retains_missing_scale_page_without_claiming_usable_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';config=web_fixture(cache,'Proposed Ground Floor Plan')
            output=root/'output';result=bridge.run(config,output,cache)
            self.assertEqual(result['summary']['completed_pages'],1)
            self.assertEqual(result['summary']['nominal_area_layout_candidates'],0)
            self.assertEqual(len(result['area_layout_files']),1)
            entry=result['area_layout_files'][0]
            self.assertEqual(entry['candidate_count'],0);self.assertNotIn('geojson_file',entry)
            self.assertEqual(result['output_sha256'][entry['file']],entry['sha256'])
            layout=json.loads((output/entry['file']).read_text())
            self.assertFalse(layout['analysis_complete']);self.assertIsNone(layout['shared_frame'])


if __name__=='__main__':unittest.main()
