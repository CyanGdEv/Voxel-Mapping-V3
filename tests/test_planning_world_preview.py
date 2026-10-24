"""Independent source-pin, packaged Bedrock geometry and spawn checks."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet

from voxel_mapper import planning_design_massing as massing
from voxel_mapper import planning_world_preview as preview
from voxel_mapper.building_spec import digest
from tests.test_planning_design_massing import source, signed


def raw_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resign(review):
    review['id'] = digest({key: value for key, value in review.items() if key != 'id'})
    return review


def request(root, review=None, **settings):
    review = massing.review_pages([source()]) if review is None else review
    path = root/'design-massing.json'
    path.write_text(json.dumps(review, indent=2, allow_nan=False), encoding='utf-8')
    return {'version': preview.VERSION, 'review_path': str(path.resolve()),
            'review_sha256': raw_sha(path), **settings}, review


def block(level, x, y, z):
    chunk = level.get_chunk(x//16, z//16, 'minecraft:overworld')
    return chunk.block_palette[int(chunk.blocks[x % 16, y, z % 16])]


def runs(values):
    groups = []
    for value in sorted(values):
        if not groups or value != groups[-1][-1]+1:
            groups.append([])
        groups[-1].append(value)
    return groups


class PlanningWorldPreviewTests(unittest.TestCase):
    def test_packaged_rivals_reopen_with_safe_spawn_and_distinct_source_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, review = request(root)
            before = copy.deepcopy(config)
            source_bytes = (root/'design-massing.json').read_bytes()
            output = root/'export'
            report = preview.run(config, output)
            self.assertEqual(config, before)
            self.assertEqual((root/'design-massing.json').read_bytes(), source_bytes)
            self.assertEqual(report['status'], 'conditional_world_previews_exported')
            self.assertFalse(report['world_placement_eligible'])
            self.assertEqual(len(report['worlds']), 2)
            self.assertEqual(json.loads((output/'quality-report.json').read_text()), report)
            html = (output/'index.html').read_text(encoding='utf-8')
            alternatives = {row['spacing_interpretation']: row for row in review['alternatives']}
            measured_gaps = {}
            for entry in report['worlds']:
                meaning = entry['spacing_interpretation']
                alternative = alternatives[meaning]
                package = output/entry['file']
                self.assertEqual(package.parent, output)
                self.assertEqual(package.suffix, '.mcworld')
                self.assertIn(package.name, html)
                self.assertEqual(entry['source_spec_sha256'], alternative['spec_sha256'])
                self.assertEqual(entry['spec_sha256'], alternative['spec_sha256'])
                self.assertFalse(entry['world_placement_eligible'])
                self.assertTrue(entry['spawn_validation']['verified'])
                self.assertTrue(entry['archive_validation']['crc_verified'])
                self.assertTrue(entry['archive_validation']['saved_world_reopened'])
                self.assertTrue((output/entry['audit_file']).is_file())
                self.assertEqual(raw_sha(package), entry['world']['sha256'])
                self.assertIn('all written blocks', entry['world']['round_trip_validation'])
                self.assertEqual(entry['world']['blocks_per_metre'], 1)
                self.assertFalse(entry['native_audit']['world_placement_eligible'])
                low, high = entry['native_bounds_xyz']
                self.assertEqual(low[0], 0)
                self.assertEqual(high[0], 35)
                extracted = root/('extracted-'+meaning)
                with zipfile.ZipFile(package) as archive:
                    self.assertIsNone(archive.testzip())
                    names = archive.namelist()
                    self.assertIn('level.dat', names)
                    self.assertTrue(any(name.startswith('db/') for name in names))
                    self.assertFalse(any(Path(name).name == 'LOCK' for name in names))
                    self.assertTrue(all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in names))
                    coordinates = json.loads(archive.read('voxel-georeferencing.json'))
                    self.assertIsNone(coordinates['crs'])
                    self.assertIn('local', json.dumps(coordinates).lower())
                    self.assertNotIn('negative north', json.dumps(coordinates).lower())
                    archive.extractall(extracted)
                level = amulet.load_level(str(extracted))
                try:
                    tag = level.level_wrapper.root_tag.compound
                    spawn = [int(tag['Spawn'+axis]) for axis in 'XYZ']
                    self.assertEqual(spawn, entry['world']['spawn'])
                    x, y, z = spawn
                    self.assertNotEqual(block(level, x, y-1, z).base_name, 'air')
                    self.assertEqual(block(level, x, y, z).base_name, 'air')
                    self.assertEqual(block(level, x, y+1, z).base_name, 'air')
                    # Spawn is outside the envelope, supported by display terrain.
                    self.assertEqual(block(level, x, y-1, z).base_name, 'grass_block')
                    self.assertTrue(x < low[0] or x > high[0] or -z < low[2] or -z > high[2])
                    # Source horizontal X and depth remain one metre per block.
                    # Native height aliasing is separately reported, not treated
                    # as an exact 2.5 m physical-height reconstruction.
                    offset = entry['world']['vertical_offset_blocks']
                    surface_y = high[1]+offset
                    occupied_depths = {depth for depth in range(low[2], high[2]+1)
                        if block(level, 18, surface_y, -depth).base_name != 'air'}
                    row_runs = runs(occupied_depths)
                    self.assertEqual(len(row_runs), 2)
                    measured_gaps[meaning] = row_runs[1][0]-row_runs[0][-1]-1
                    self.assertEqual(block(level, 36, surface_y, -1).base_name, 'air')
                    self.assertEqual(block(level, 18, surface_y, -row_runs[0][0]).base_name, 'stone_bricks')
                    # Compilation samples the envelope surfaces; the interior
                    # source-zero column remains empty rather than being filled.
                    self.assertEqual(block(level, 18, offset, -1).base_name, 'air')
                finally:
                    level.close()
            self.assertGreater(measured_gaps['clear_gap'], measured_gaps['row_centre_separation'])
            self.assertEqual({entry['file'] for entry in report['worlds']},
                {'preview-000-clear-gap.mcworld', 'preview-001-row-centre-separation.mcworld'})

    def test_wrong_review_bytes_pin_and_stale_review_are_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, review = request(root)
            bad_pin = {**config, 'review_sha256': '0'*64}
            with self.assertRaises(ValueError):
                preview.run(bad_pin, root/'bad-pin')
            self.assertFalse((root/'bad-pin').exists())
            stale = copy.deepcopy(review)
            stale['version'] = 'planning-design-massing-v0'
            config, _ = request(root, resign(stale))
            with self.assertRaises(ValueError):
                preview.run(config, root/'stale')
            self.assertFalse((root/'stale').exists())

    def test_signed_review_does_not_allow_altered_geometry_or_source_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tamper in ('spec_pin', 'geometry', 'claim_pin'):
                with self.subTest(tamper=tamper):
                    review = massing.review_pages([source()])
                    alternative = review['alternatives'][0]
                    if tamper == 'spec_pin':
                        alternative['spec_sha256'] = 'f'*64
                    elif tamper == 'geometry':
                        alternative['spec']['components'][0]['geometry']['interval_m'][1] = 7.
                        alternative['spec_sha256'] = digest(alternative['spec'])
                    else:
                        alternative['source_claim_sha256'] = 'f'*64
                    config, _ = request(root, resign(review))
                    output = root/tamper
                    with self.assertRaises(ValueError):
                        preview.run(config, output)
                    self.assertFalse(output.exists())

    def test_selection_requires_complete_spacing_rivals_and_exact_known_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, review = request(root)
            ids = [row['id'] for row in review['alternatives']]
            for selection in ([ids[0]], ['f'*64], [ids[0], ids[0]], []):
                with self.subTest(selection=selection):
                    output = root/('invalid-'+str(len(selection))+'-'+str(len(list(root.iterdir()))))
                    with self.assertRaises(ValueError):
                        preview.run({**config, 'alternative_ids': selection}, output)
                    self.assertFalse(output.exists())
            valid = preview.validate({**config, 'alternative_ids': ids})
            self.assertIsNotNone(valid)

    def test_more_than_eight_worlds_is_rejected_without_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = []
            for number in range(5):
                page = source(length=35.85+number)
                page['document_sha256'] = hashlib.sha256(str(number).encode()).hexdigest()
                pages.append(signed(page))
            config, review = request(root, massing.review_pages(pages))
            self.assertEqual(len(review['alternatives']), 10)
            with self.assertRaises(ValueError):
                preview.run(config, root/'too-many')
            self.assertFalse((root/'too-many').exists())

    def test_cancelled_build_does_not_publish_worlds_or_partial_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _ = request(root)
            output = root/'cancelled'
            with self.assertRaises(CancelledError):
                preview.run(config, output, cancelled=lambda: True)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name+'.partial').exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _ = request(root)
            output = root/'existing'
            output.mkdir()
            sentinel = output/'keep.txt'
            sentinel.write_text('existing user files', encoding='utf-8')
            with self.assertRaises(ValueError):
                preview.run(config, output)
            self.assertEqual(sentinel.read_text(), 'existing user files')
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_failure_after_first_saved_world_removes_every_unpublished_artifact(self):
        from voxel_mapper import bedrock
        export_world = bedrock.export_world
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise ValueError('Injected second-world failure')
            return export_world(*args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _ = request(root)
            output = root/'failed'
            with patch('voxel_mapper.bedrock.export_world', side_effect=fail_second):
                with self.assertRaisesRegex(ValueError, 'Injected second-world failure'):
                    preview.run(config, output)
            self.assertEqual(len(calls), 2)
            self.assertFalse(output.exists())
            self.assertEqual([p.name for p in root.iterdir()], ['design-massing.json'])

    def test_cancellation_after_native_world_write_removes_every_unpublished_artifact(self):
        from voxel_mapper import bedrock
        export_world = bedrock.export_world
        state = {'cancelled': False}
        def cancel_after_write(*args, **kwargs):
            result = export_world(*args, **kwargs)
            state['cancelled'] = True
            return result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, _ = request(root)
            output = root/'cancelled-mid-job'
            with patch('voxel_mapper.bedrock.export_world', side_effect=cancel_after_write) as writer:
                with self.assertRaises(CancelledError):
                    preview.run(config, output, cancelled=lambda: state['cancelled'])
            self.assertEqual(writer.call_count, 1)
            self.assertFalse(output.exists())
            self.assertEqual([p.name for p in root.iterdir()], ['design-massing.json'])


if __name__ == '__main__':
    unittest.main()
