"""Full-page source layouts to bounded flat maps with saved-cell evidence."""
import copy
from concurrent.futures import CancelledError
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
import pymupdf
from shapely.geometry import Polygon, box, mapping

from voxel_mapper import architectural_graph, architectural_view_layout, ordinary_surfaces
from voxel_mapper import planning_component_footprints, planning_outline_semantics
from voxel_mapper import planning_surface_footprints, planning_area_layout
from voxel_mapper import planning_area_world_preview as preview
from voxel_mapper.building_spec import digest


@lru_cache(maxsize=2)
def source_layout(wide=False):
    """Real native PDF extraction; no manually supplied view or object boxes."""
    with pymupdf.open() as document:
        page = document.new_page(width=3000 if wide else 1000, height=700)
        for rectangle, text, position in (
            ((100,100,250,200), 'Shop', (120,150)),
            ((250,100,2250 if wide else 550,200), 'Footpath', (350,150)),
            ((2250,100,2450,300) if wide else (550,100,750,300),
             'Plaza', (2300 if wide else 600,220)),
            ((250,400,500,450), 'Path', (350,425))):
            page.draw_rect(rectangle)
            page.insert_text(position, text, fontsize=8)
        page.insert_text((70,600), 'Proposed Ground Floor Plan | 1:200', fontsize=10)
        data = document.tobytes()
        sha = hashlib.sha256(data).hexdigest()
        graph = architectural_graph.build([])
        graph.update(document_sha256=sha, page=1)
        captions = architectural_view_layout.review(page, sha, 1, graph)
        _, _, report = ordinary_surfaces.page_candidates(page, sha, 1)
        inventory = report['source_outline_inventory']
        semantics = planning_outline_semantics.page_candidates(page, sha, 1, inventory)
        components = planning_component_footprints.page_candidates(page, sha, 1, inventory, semantics)
        surfaces = planning_surface_footprints.page_candidates(page, sha, 1, inventory, semantics)
        layout = planning_area_layout.page_layout(page, sha, 1, captions, inventory,
            semantics, components, surfaces)
        planning_area_layout.validate_layout(layout)
        return layout


def request(root, layout=None):
    layout = copy.deepcopy(source_layout() if layout is None else layout)
    path = root/'area-layout.json'
    path.write_text(json.dumps(layout, indent=2, allow_nan=False), encoding='utf-8')
    return {'version': preview.VERSION, 'layout_path': str(path),
        'layout_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, layout


def block(level, x, y, z):
    chunk = level.get_chunk(x//16, z//16, 'minecraft:overworld')
    return chunk.block_palette[int(chunk.blocks[x%16, y, z%16])]


class PlanningAreaWorldPreviewTests(unittest.TestCase):
    def test_original_page_layout_becomes_flat_native_plan_with_gaps_and_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, layout = request(root)
            source = Path(config['layout_path']).read_bytes()
            output = root/'preview'
            report = preview.run(config, output)
            self.assertEqual(Path(config['layout_path']).read_bytes(), source)
            self.assertEqual(report['source_layout_id'], layout['id'])
            self.assertEqual(report['reconstructed_buildings'], 0)
            self.assertEqual(report['building_heights_reconstructed'], 0)
            self.assertFalse(report['world_placement_eligible'])
            self.assertEqual(report['park_world_blocks_added'], 0)
            self.assertEqual(len(report['candidate_display_counts']), 4)
            self.assertEqual(report['saved_grid_paving_connectivity']['component_count'], 2)
            self.assertFalse(report['saved_grid_paving_connectivity']['all_display_paving_connected'])
            self.assertFalse(report['saved_grid_paving_connectivity']['physical_traversability_verified'])
            self.assertTrue(report['saved_grid_paving_connectivity']['saved_paving_membership_verified'])
            self.assertTrue(report['spawn_validation']['verified'])
            self.assertTrue(report['archive_validation']['saved_world_reopened'])
            self.assertEqual(json.loads((output/'quality-report.json').read_text()), report)
            for name, sha in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(), sha)
            self.assertIn('footprint markers', (output/'index.html').read_text())
            package = output/report['file']
            extracted = root/'extracted'
            with zipfile.ZipFile(package) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('preview-source-area-layout.json', archive.namelist())
                self.assertEqual(json.loads(archive.read('preview-source-area-layout.json')), layout)
                archive.extractall(extracted)
            level = amulet.load_level(str(extracted))
            try:
                offset = report['world']['vertical_offset_blocks']
                # Independently selected source-space sample cells. The source
                # Y cell [d,d+1] reflects to Minecraft Z [-d-1,-d].
                marker = block(level, 10, offset, -39)
                self.assertEqual(marker.base_name, 'concrete')
                self.assertEqual(str(marker.properties['color']), 'yellow')
                self.assertEqual(block(level, 10, offset+1, -39).base_name, 'air')
                self.assertNotEqual(block(level, 25, offset, -39).base_name, 'grass_block')
                # The 14-metre source gap between the detached path and the
                # connected path/plaza stays grass; no connection is invented.
                self.assertEqual(block(level, 25, offset, -26).base_name, 'grass_block')
                spawn = report['world']['spawn']
                self.assertEqual(block(level, spawn[0], spawn[1]-1, spawn[2]).base_name, 'grass_block')
                self.assertEqual(block(level, spawn[0], spawn[1], spawn[2]).base_name, 'air')
            finally:
                level.close()

    def test_source_pin_and_resigned_nominal_geometry_substitution_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root)
            with self.assertRaises(ValueError):
                preview.run({**config, 'layout_sha256': '0'*64}, root/'bad-pin')
            changed = copy.deepcopy(source_layout())
            changed['candidates'][0]['geometry_nominal_local']['coordinates'][0][0][0] += 1
            changed['id'] = digest({key: value for key, value in changed.items() if key != 'id'})
            config, _ = request(root, changed)
            with self.assertRaises(ValueError):
                preview.run(config, root/'substitution')
            self.assertFalse((root/'bad-pin').exists())
            self.assertFalse((root/'substitution').exists())

    def test_holes_narrow_paths_and_point_contacts_are_not_filled_or_joined(self):
        # Independent exact shapes inspect the sampler directly, so the expected
        # answer does not depend on the layout proposal's graph or counters.
        rows = [
            {'id': 'ring', 'role': 'path', 'height_m': None, 'surface': 'asphalt',
             'geometry_nominal_local': mapping(Polygon([(0,0),(6,0),(6,6),(0,6)],
                 [[(2,2),(4,2),(4,4),(2,4)]]))},
            {'id': 'narrow', 'role': 'path', 'height_m': None, 'surface': 'stone',
             'geometry_nominal_local': mapping(box(8.05,0,8.15,4))},
            {'id': 'diagonal', 'role': 'plaza', 'height_m': None, 'surface': 'asphalt',
             'geometry_nominal_local': mapping(box(6,6,8,8))}]
        sampled = preview._rasterize({'candidates': rows}, lambda: False)
        self.assertNotIn((2,2), sampled['materials'])
        self.assertNotIn((3,3), sampled['materials'])
        self.assertEqual(sum((x,z) in sampled['paving'] for x in range(6) for z in range(6)), 32)
        self.assertEqual(sampled['grid_connectivity']['component_count'], 2)
        self.assertEqual(next(row['display_cells'] for row in sampled['candidate_counts']
            if row['candidate_id'] == 'narrow'), 0)

    def test_conflicting_roles_or_finishes_and_large_domains_are_rejected(self):
        def row(identifier, role, polygon, surface=None):
            return {'id': identifier, 'role': role, 'height_m': None, 'surface': surface,
                'geometry_nominal_local': mapping(polygon)}
        for rows in (
            [row('b', 'building', box(0,0,4,4)), row('p', 'path', box(2,2,6,6), 'stone')],
            [row('p', 'path', box(0,0,4,4), 'stone'), row('q', 'plaza', box(2,2,6,6), 'asphalt')],
            [row('wide', 'path', box(0,0,600,2), 'stone')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                preview._rasterize({'candidates': rows}, lambda: False)

    def test_cancellation_and_native_failure_do_not_publish_partial_worlds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root)
            with self.assertRaises(CancelledError):
                preview.run(config, root/'cancelled', cancelled=lambda: True)
            self.assertFalse((root/'cancelled').exists())
            with patch('voxel_mapper.bedrock.export_world', side_effect=ValueError('simulated native failure')):
                with self.assertRaisesRegex(ValueError, 'simulated native failure'):
                    preview.run(config, root/'failed')
            self.assertFalse((root/'failed').exists())
            self.assertFalse(any(path.name.startswith('planning-area-world-') for path in root.iterdir()))

    def test_existing_output_and_malformed_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root)
            output = root/'existing'
            output.mkdir()
            sentinel = output/'keep.txt'
            sentinel.write_text('keep', encoding='utf-8')
            with self.assertRaises(ValueError):
                preview.run(config, output)
            self.assertEqual(sentinel.read_text(), 'keep')
            for bad in ({**config, 'unknown': True}, {**config, 'layout_path': ''},
                        {**config, 'layout_sha256': True}, {**config, 'version': 'old'}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    preview.validate(bad)

    def test_source_change_during_native_export_prevents_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root)
            source = Path(config['layout_path'])
            output = root/'changed-source'
            def update(event):
                if event['progress'] == .25:
                    source.write_bytes(source.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError, 'changed during world export'):
                preview.run(config, output, progress=update)
            self.assertFalse(output.exists())
            self.assertFalse(any(path.name.startswith('planning-area-world-') for path in root.iterdir()))


if __name__ == '__main__':
    unittest.main()
