"""Complete larger source plans, seam preservation and bounded atomic export."""
import copy
from concurrent.futures import CancelledError
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
from shapely.geometry import Point, Polygon, box, mapping

from voxel_mapper import planning_area_world_preview as preview
from test_planning_area_world_preview import source_layout, request, block


def row(identifier, geometry, role='path', surface='asphalt'):
    return {'id': identifier, 'role': role, 'height_m': None, 'surface': surface,
        'geometry_nominal_local': mapping(geometry)}


class TiledAreaWorldPreviewTests(unittest.TestCase):
    def test_original_wide_pdf_exports_one_world_with_connected_paving_across_seam(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, layout = request(root, source_layout(wide=True))
            original = Path(config['layout_path']).read_bytes()
            report = preview.run(config, root/'world')
            partition = report['platform_partition']
            self.assertEqual(partition['section_count'], 2)
            self.assertFalse(partition['cropped'])
            self.assertFalse(partition['rescaled'])
            self.assertEqual(len(report['candidate_display_counts']), 4)
            saved = report['saved_grid_paving_connectivity']
            self.assertEqual(saved['component_count'], 2)
            self.assertEqual(saved['saved_platform_cells'], partition['platform_cells'])
            self.assertTrue(all(tile['verified'] for tile in saved['saved_sections']))
            self.assertEqual(Path(config['layout_path']).read_bytes(), original)
            extracted = root/'extracted'
            with zipfile.ZipFile(root/'world'/'area-plan.mcworld') as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(json.loads(archive.read('preview-source-area-layout.json')), layout)
                archive.extractall(extracted)
            level = amulet.load_level(str(extracted))
            try:
                offset = report['world']['vertical_offset_blocks']
                seam = partition['sections'][1]['bounds_source_local_xy'][0]
                # Independently calculated from the original PDF: at 1:200,
                # y=550pt y-up is 38.8055m. Both seam cells lie on the path.
                for x in (seam-1, seam):
                    self.assertNotEqual(block(level, x, offset, -39).base_name, 'grass_block')
                    self.assertEqual(block(level, x, offset+1, -39).base_name, 'air')
                    # A source gap above the detached path remains grass.
                    self.assertEqual(block(level, x, offset, -26).base_name, 'grass_block')
                # Distant plaza is retained at its original nominal position.
                self.assertNotEqual(block(level, 165, offset, -36).base_name, 'grass_block')
            finally:
                level.close()

    def test_negative_coordinates_holes_and_diagonal_contacts_cross_sections_unchanged(self):
        polygon = Polygon([(-70,-12),(100,-12),(100,-6),(-70,-6)],
            [[(52,-11),(58,-11),(58,-7),(52,-7)]])
        detached = box(100,-6,102,-4)
        layout = {'candidates': [row('ring', polygon), row('touch', detached)]}
        before = copy.deepcopy(layout)
        sampled = preview._rasterize(layout, lambda: False)
        # Independent whole-domain oracle; no section scheduler is reused.
        expected = {(x,z) for x in range(-70,102) for z in range(-12,-4)
            if polygon.covers(Point(x+.5,z+.5)) or detached.covers(Point(x+.5,z+.5))}
        self.assertEqual(set(sampled['materials']), expected)
        self.assertEqual(sampled['grid_connectivity']['component_count'], 2)
        self.assertEqual(layout, before)
        self.assertEqual(len(sampled['tiles']), 2)
        self.assertEqual(sum(t['display_cells'] for t in sampled['tiles']), len(expected))
        covered = []
        for tile in sampled['tiles']:
            a,b,c,d = tile['bounds_source_local_xy']
            covered.extend((x,z) for x in range(a,c) for z in range(b,d))
        a,b,c,d = sampled['platform_bounds']
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(set(covered), {(x,z) for x in range(a,c) for z in range(b,d)})

    def test_legacy_requests_keep_the_original_single_platform_limit(self):
        layout = {'candidates': [row('wide', box(0,0,130,2))]}
        with self.assertRaisesRegex(ValueError, '128 by 128'):
            preview._rasterize(layout, lambda: False, version=preview.LEGACY_VERSION)
        self.assertEqual(len(preview._rasterize(layout, lambda: False)['tiles']), 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root)
            config['version'] = preview.LEGACY_VERSION
            result = preview.run(config, root/'legacy')
            self.assertEqual(result['version'], preview.LEGACY_VERSION)
            self.assertEqual(result['limits']['max_sections'], 1)
            self.assertEqual(result['saved_grid_paving_connectivity']['paving_cells'], 394)

    def test_four_sections_partition_both_axes_with_one_global_write_account(self):
        sampled = preview._rasterize({'candidates': [row('plaza', box(0,0,132,132))]}, lambda: False)
        self.assertEqual(len(sampled['tiles']), 4)
        self.assertEqual(sampled['platform_cells'], 140*140)
        self.assertEqual(len(sampled['paving']), 132*132)
        self.assertEqual(sampled['grid_connectivity']['component_count'], 1)
        self.assertEqual(sampled['native_write_attempts'], 4*140*140+132*132)
        self.assertEqual(sum(t['native_write_attempts'] for t in sampled['tiles']),
            sampled['native_write_attempts'])
        self.assertTrue(all(t['platform_cells']<=16384 for t in sampled['tiles']))

    def test_total_writes_section_count_sampling_and_points_remain_bounded(self):
        cases = [
            ([row('many', box(0,0,150,150))], {}, 'write budget'),
            ([row('strip', box(0,0,600,1))], {}, 'section count'),
            ([row('features', box(0,0,150,150))], {'MAX_WORLD_BLOCKS': 105000}, 'write budget'),
            ([row('sample', box(0,0,130,2))], {'MAX_GRID_CHECKS': 100}, 'sampling work'),
            ([row('points', box(0,0,130,2))], {'MAX_POINTS': 4}, 'source point')]
        for rows, limits, error in cases:
            with self.subTest(error=error, limits=limits), (patch.multiple(preview, **limits) if limits else nullcontext()):
                with self.assertRaisesRegex(ValueError, error):
                    preview._rasterize({'candidates': rows}, lambda: False)

    def test_cancellation_after_preparing_second_section_cleans_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root, source_layout(wide=True))
            stop = False
            def progress(event):
                nonlocal stop
                if event['message'] == 'Prepared complete plan section 2':
                    stop = True
            with patch('voxel_mapper.bedrock.export_world') as export:
                with self.assertRaises(CancelledError):
                    preview.run(config, root/'cancelled', cancelled=lambda: stop, progress=progress)
                export.assert_not_called()
            self.assertFalse((root/'cancelled').exists())
            self.assertFalse(any(p.name.startswith('planning-area-world-') for p in root.iterdir()))

    def test_saved_grass_corruption_in_second_section_is_rejected(self):
        from amulet.level.formats.leveldb_world import LevelDBFormat
        from voxel_mapper.bedrock import material_block
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = request(root, source_layout(wide=True))
            original_check = preview._saved_grid_check
            def corrupt(path, offset, sampled, cancelled):
                a,b,_,_ = sampled['tiles'][1]['bounds_source_local_xy']
                wrapper = LevelDBFormat(str(path))
                wrapper.open()
                try:
                    x,z = a,-b-1
                    chunk = wrapper.load_chunk(x//16,z//16,preview.DIMENSION)
                    chunk.blocks[x%16,offset,z%16] = chunk.block_palette.get_add_block(material_block('stone'))
                    chunk.changed = True
                    wrapper.commit_chunk(chunk,preview.DIMENSION)
                    wrapper.save()
                finally:
                    wrapper.close()
                return original_check(path, offset, sampled, cancelled)
            with patch.object(preview, '_saved_grid_check', side_effect=corrupt):
                with self.assertRaisesRegex(ValueError, 'differ from source rasterization'):
                    preview.run(config, root/'corrupt')
            self.assertFalse((root/'corrupt').exists())
            self.assertFalse(any(p.name.startswith('planning-area-world-') for p in root.iterdir()))


if __name__ == '__main__':
    unittest.main()
