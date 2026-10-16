"""Native synthetic planning page, independent source geometry and saved material faults."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
import pymupdf
from shapely.geometry import Point, Polygon, shape

from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.horizontal_grid import OSTN15Transform
from voxel_mapper.pilot_access import (SURFACE_POLICY, PATH_STEP_FEATURE, PATH_STEP_POLICY,
    _scene, _mapped_nodes, collision)
from voxel_mapper.pilot_surfaces import recover, _curved_fills, _even_odd_fill
from voxel_mapper.wicker_registration import printed_scale
from voxel_mapper.wicker_surfaces import painted_polygon
from voxel_mapper.wickerman import annotation_evidence
from voxel_mapper.world_pilot import run
import test_pilot_review as fixtures

ROOT = Path(__file__).resolve().parents[1]


class PlanningSurfaceTests(unittest.TestCase):
    def fixture(self, root):
        helper = fixtures.PilotReviewTests()
        path, job, _ = helper.fixture(root)
        pdf_path = root / 'paving.pdf'
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=700, height=600)
            page.draw_polyline([(82, 35), (118, 35), (118, 55), (82, 55), (82, 35)], fill=(1, 1, 1))
            page.insert_text((91, 47), 'Shop', fontsize=7)
            for i in range(5):
                text = str(10 * i)
                page.insert_text((20 + 20 * i - pymupdf.get_text_length(text, fontsize=8) / 2, 570), text, fontsize=8)
            tan = (.8, .7, .6)
            page.draw_rect(pymupdf.Rect(500, 90, 530, 110), fill=tan)
            page.insert_text((540, 102), 'Existing Paving with levels', fontsize=8)
            drawing = page.new_shape()
            drawing.draw_rect(pymupdf.Rect(130, 50, 155, 80))
            drawing.draw_rect(pymupdf.Rect(138, 58, 142, 62))
            drawing.finish(fill=tan, even_odd=True); drawing.commit()
            page.insert_text((134, 72), 'Plaza', fontsize=7)
            for i in range(14):
                page.insert_text((270 + (i % 3) * 50, 160 + (i // 3) * 35),
                                 f'{"HP" if i < 7 else "LP"}{i % 7 + 1} - 181.0', fontsize=8)
            pdf_path.write_bytes(pdf.tobytes())
        with pymupdf.open(pdf_path) as pdf:
            lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])}
                     for block in pdf[0].get_text('dict')['blocks'] for line in block.get('lines', [])]
        scale = printed_scale(lines)
        operation = {'method': 'ostn15-bng-v1', 'path': str(ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid.tif'),
                     'sha256': job['horizontal_operation']['grid']['sha256']}
        coordinate = OSTN15Transform(4326, 27700, operation)
        def native_to_geographic(x, y):
            lon, lat = coordinate.inverse(407563 + (x - 100) * scale, 343584 + (45 - y) * scale)
            return {'lon': lon, 'lat': lat}
        _, levels = annotation_evidence(lines)
        raw = {'elements': [
            {'type': 'way', 'id': 1, 'tags': {'name': 'Wicker Man Shop'},
             'geometry': [native_to_geographic(x, y) for x, y in [(82,35),(118,35),(118,55),(82,55),(82,35)]]},
            {'type': 'way', 'id': 2, 'tags': {'name': 'Wicker Man', 'roller_coaster': 'track'},
             'geometry': [native_to_geographic((l['bbox'][0]+l['bbox'][2])/2, (l['bbox'][1]+l['bbox'][3])/2) for l in levels]}]}
        source = {'document_sha256': helper.pin(pdf_path)['sha256'], 'page': 1, 'drawing_state': 'proposed',
                  'registration_verified': False, 'as_built_verified': False,
                  'title': 'Synthetic paving fixture', 'application_reference': 'TEST/1', 'source_url': 'https://example.test/plan'}
        job['review_component']['access'] = {'policy': 'estimated_each_opening_approach_v2', 'audit_scope': 'whole_pilot'}
        job['review_surfaces'] = {'policy': SURFACE_POLICY, 'source_pdf': helper.pin(pdf_path),
                                 'source_record': helper.write(root / 'paving-source.json', source),
                                 'raw_osm': helper.write(root / 'paving-osm.json', raw), 'max_cells': 1000}
        config_path = root / 'config.json'; config = json.loads(config_path.read_text())
        config['sources'].append({'id': 'osm', 'kind': 'osm', 'url': 'https://example.test/map', 'license': 'CC0'})
        job['config'] = helper.write(config_path, config)
        features = []
        for name, kind, bounds in [('path', 'path', (407578,343570,407581,343579)),
                                   ('road', 'road', (407584,343570,407586,343572))]:
            x0,z0,x1,z1 = bounds
            points = [coordinate.inverse(x,z) for x,z in [(x0,z0),(x1,z0),(x1,z1),(x0,z1),(x0,z0)]]
            features.append({'type': 'Feature', 'id': 'osm/' + name,
                'geometry': {'type': 'Polygon', 'coordinates': [points]},
                'properties': {'source_id': 'osm', 'kind': kind, 'highway': 'footway' if kind=='path' else 'service', 'surface': 'asphalt'}})
        job['features'] = helper.write(root / 'features.json', {'features': features, 'planning_geometry_records': []})
        helper.write(path, job)
        return path, job, raw, operation

    def test_source_to_native_world_preserves_holes_roads_lineage_and_pending_forms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, _, _ = self.fixture(root)
            report = run(job_path, root / 'one')
            paving = report['planning_surfaces_review']
            self.assertEqual(paving['status'], 'native_paving_verified')
            self.assertEqual(paving['labelled_plaza_features'], 1)
            self.assertGreater(paving['added_paving_records'], 0)
            self.assertGreater(paving['mapped_paving_finish_cells'], 0)
            self.assertGreater(paving['features'][0]['excluded_cells']['protected_road_parking_or_structure'], 0)
            self.assertFalse(paving['placement']['scale_adjusted_to_fit_map'])
            self.assertFalse(paving['placement']['registration_verified'])
            self.assertEqual(report['readiness']['planning_components_voxelized'], 0)
            self.assertEqual(paving['training_labels_generated'], 0)
            self.assertIn('planning-surfaces-source.geojson', report['output_sha256'])
            local = json.loads((root / 'one/planning-surfaces-local.geojson').read_text())
            polygon = shape(local['features'][0]['geometry'])
            self.assertEqual(len(polygon.interiors), 1)
            rows = [json.loads(line) for line in (root / 'one/voxels.jsonl').read_text().splitlines()]
            painted = {(r['x'],r['z']) for r in rows if r.get('review_surface_policy') == SURFACE_POLICY}
            hole = Polygon(polygon.interiors[0])
            centres = {(x,z) for x in range(math.floor(hole.bounds[0]),math.ceil(hole.bounds[2]))
                       for z in range(math.floor(hole.bounds[1]),math.ceil(hole.bounds[3])) if hole.contains(Point(x+.5,z+.5))}
            self.assertTrue(centres)
            self.assertFalse(centres & painted)
            forms = json.loads((root / 'one/playtest-results.json').read_text())
            self.assertEqual(forms['world']['sha256'], report['world']['sha256'])
            self.assertTrue(all(check['outcome']=='not_run' for check in forms['checks']))
            self.assertTrue(any(check['id'].startswith('plaza/') for check in forms['checks']))
            with zipfile.ZipFile(root / 'one/park.mcworld') as archive:
                self.assertEqual(json.loads(archive.read('voxel-quality-report.json'))['planning_surfaces_review'], paving)
            run(job_path, root / 'two')
            for name in ('voxels.jsonl','planning-surfaces-review.json','planning-surfaces-source.geojson','planning-surfaces-local.geojson'):
                self.assertEqual((root / 'one' / name).read_bytes(), (root / 'two' / name).read_bytes())

    def test_native_wrong_material_with_unchanged_bearing_rejects_the_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path, _, _, _ = self.fixture(root)
            def wrapped(voxels, output, quality, *args, post_export_check=None, **kwargs):
                def corrupt(path, offset, spawn):
                    row = next(json.loads(line) for line in voxels.read_text().splitlines()
                               if json.loads(line).get('review_surface_policy') == SURFACE_POLICY)
                    level = amulet.load_level(str(path))
                    try:
                        x,y,z=row['x'],row['y'],row['z']; chunk=level.get_chunk(x//16,(-z)//16,'minecraft:overworld')
                        wrong='stone' if row['material']!='stone' else 'terracotta'
                        chunk.blocks[x%16,y+offset,(-z)%16]=chunk.block_palette.get_add_block(material_block(wrong))
                        chunk.changed=True;level.put_chunk(chunk,'minecraft:overworld');level.save()
                    finally:level.close()
                    return post_export_check(path, offset, spawn)
                return export_world(voxels, output, quality, *args, post_export_check=corrupt, **kwargs)
            with patch('voxel_mapper.world_pilot.export_world', side_effect=wrapped):
                with self.assertRaisesRegex(ValueError, 'planning paving material'):
                    run(job_path, root / 'scene')
            self.assertFalse((root / 'scene.partial/park.mcworld').exists())
            self.assertFalse((root / 'scene.partial/bedrock-world').exists())

    def test_source_fit_uses_printed_scale_and_rejects_missing_or_ambiguous_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);_,job,raw,operation=self.fixture(root)
            config=json.loads((root/'config.json').read_text())
            _,placement,_=recover(root/'paving.pdf',raw,operation,config['bbox'])
            self.assertEqual(placement['candidate']['scale_m_per_pdf_point'],placement['printed_scale_m_per_pdf_point'])
            for fault in ('track','duplicate_shop'):
                broken=copy.deepcopy(raw)
                if fault=='track':broken['elements'].pop()
                else:broken['elements'].append(copy.deepcopy(broken['elements'][0]))
                with self.subTest(fault=fault), self.assertRaises(ValueError):
                    recover(root/'paving.pdf',broken,operation,config['bbox'])

    def test_invalid_scope_policy_state_hash_and_budget_do_not_publish_a_world(self):
        for fault in ('normal_job','scope','policy','state','hash','budget'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);path,job,_,_=self.fixture(root);helper=fixtures.PilotReviewTests()
                if fault=='normal_job':job['version']='world-pilot-v1';job.pop('review_component')
                elif fault=='scope':job['review_component']['access']['audit_scope']='component_neighbourhood'
                elif fault=='policy':job['review_surfaces']['accepted']=True
                elif fault=='state':
                    metadata=json.loads((root/'paving-source.json').read_text());metadata['as_built_verified']=True
                    job['review_surfaces']['source_record']=helper.write(root/'paving-source.json',metadata)
                elif fault=='hash':(root/'paving.pdf').write_bytes((root/'paving.pdf').read_bytes()+b'changed')
                else:job['review_surfaces']['max_cells']=1
                helper.write(path,job)
                with self.assertRaises(ValueError):run(path,root/'scene')
                self.assertFalse((root/'scene/park.mcworld').exists())
                self.assertFalse((root/'scene.partial/park.mcworld').exists())

    def test_planning_finish_retains_mapped_and_half_slab_lineage(self):
        path=dict(x=0,y=0,z=0,kind='path',feature='osm/path',material='stone')
        reference={k:path[k] for k in ('feature','x','y','z')}
        finish={**path,'feature':'review/planning-paving/000','material':'cobblestone',
                'source':'provisional-plan-paving','material_origin':'estimated_reconstruction_shell',
                'review_surface_policy':SURFACE_POLICY,'accepted_physical_geometry':False,
                'overlays_mapped_source_cell':reference}
        slab=dict(x=0,y=1,z=0,kind='steps',feature=PATH_STEP_FEATURE,material='stone_slab',
                  material_origin='estimated_reconstruction_shell',display_policy=PATH_STEP_POLICY,
                  accepted_physical_geometry=False,mapped_source_cell=reference)
        records={(0,0,0):finish,(0,1,0):slab}
        self.assertEqual(collision(material_block('cobblestone')),(0,2,2))
        self.assertEqual(_mapped_nodes(_scene(records,(-1,-1,1,1)),{(0,0,0):path},records),{(0,0,3):'osm/path'})
        finish['overlays_mapped_source_cell']={**reference,'feature':'another/path'}
        self.assertEqual(_mapped_nodes(_scene(records,(-1,-1,1,1)),{(0,0,0):path},records),{})

    def test_curved_fills_keep_holes_and_do_not_flatten_collinear_overshoots_to_a_chord(self):
        path={'type':'f','even_odd':True,'items':[
            ['l',[0,0],[10,0]],['c',[10,0],[16,0],[16,10],[10,10]],
            ['l',[10,10],[0,10]],['l',[0,10],[0,0]],['re',[2,2,4,4],1]]}
        flattened,count=_curved_fills([path],.01)
        polygon=painted_polygon(flattened[0])
        self.assertEqual(count,1);self.assertGreater(polygon.area,100);self.assertEqual(len(polygon.interiors),1)
        self.assertFalse(polygon.covers(Point(3,3)))
        backtrack={'type':'f','items':[['c',[0,0],[20,0],[20,0],[1,0]]]}
        flattened,_=_curved_fills([backtrack],.01)
        self.assertGreater(max(item[2][0] for item in flattened[0]['items']),10)
        for tolerance in (0,-1,float('nan')):
            with self.assertRaises(ValueError):_curved_fills([path],tolerance)

    def test_crossing_edges_follow_even_odd_fill_without_snapping_or_buffer_repair(self):
        points=[(0,0),(4,4),(0,4),(4,0),(0,0)]
        path={'type':'f','even_odd':True,'items':[['l',a,b] for a,b in zip(points,points[1:])]}
        result=_even_odd_fill(path)
        self.assertEqual(result.geom_type,'MultiPolygon');self.assertEqual(result.area,8)
        self.assertTrue(result.covers(Point(2,3.5)));self.assertFalse(result.covers(Point(.2,2)))
        self.assertIsNone(_even_odd_fill({**path,'even_odd':False}))
        overlapping={'type':'f','even_odd':True,'items':[['re',[0,0,4,4],1],['re',[2,0,6,4],1]]}
        result=_even_odd_fill(overlapping)
        self.assertEqual(result.area,16);self.assertFalse(result.covers(Point(3,2)))


if __name__=='__main__':unittest.main()
