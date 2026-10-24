"""Class/source coverage remains diagnostic and counts independent groups."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from voxel_mapper import study_training_coverage as coverage
from voxel_mapper.building_spec import digest
from voxel_mapper.study_dataset import connected_groups


def fixture(root, definitions=None):
    root.mkdir()
    definitions = definitions or [
        ('wickerman-shop', 'a'*64, ['roof', 'roof', 'window']),
        ('prospect-tower', 'b'*64, ['roof', 'rock']),
        ('alton-site-details-demo', 'c'*64, ['rock', 'rock', 'planter']),
    ]
    records, files = [], {}
    stream = BytesIO(); Image.new('L', (32, 32), 127).save(stream, format='PNG'); raw = stream.getvalue()
    pin = hashlib.sha256(raw).hexdigest()
    for number, (building, source, kinds) in enumerate(definitions):
        for index, kind in enumerate(kinds):
            rid = 'record-'+str(number)+'-'+str(index)
            name = 'examples/'+rid+'/input.png'
            path = root/name; path.parent.mkdir(parents=True); path.write_bytes(raw); files[name] = pin
            records.append({'id': rid, 'building_id': building, 'kind': kind,
                'source': {'document_sha256': source, 'page': 1},
                'learning_eligible': True, 'evidence_level': 'synthetic_fixture',
                'input_file': name, 'input_sha256': pin,
                'target_geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,0]]]}})
    groups = connected_groups(records)
    owners = {rid: group['group_id'] for group in groups for rid in group['record_ids']}
    for record in records:
        record['group_id'] = owners[record['id']]
    manifest = {'version': 'retained-study-dataset-v1', 'dataset_kind': 'synthetic_fixture',
        'records': records, 'groups': groups, 'output_sha256': files}
    manifest['id'] = digest(manifest)
    (root/'dataset.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


class StudyTrainingCoverageTests(unittest.TestCase):
    def test_counts_classes_groups_and_unknown_class_folds_without_predicting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; manifest = fixture(root)
            result = coverage.report(root)
            self.assertEqual(result['dataset_id'], manifest['id'])
            self.assertEqual(result['dataset_manifest_sha256'], hashlib.sha256((root/'dataset.json').read_bytes()).hexdigest())
            self.assertEqual(result['summary']['eligible_component_examples'], 8)
            self.assertEqual(result['summary']['source_connected_groups'], 3)
            self.assertEqual(result['classes']['roof']['examples'], 3)
            self.assertEqual(result['classes']['roof']['source_groups'], 2)
            self.assertEqual(result['single_group_classes'], ['planter', 'window'])
            available = result['leave_one_group_out_class_availability']
            self.assertEqual(available['examples_with_unseen_training_class'], 2)
            self.assertEqual(available['examples_with_class_available_in_training'], 6)
            self.assertEqual(sum(c['examples'] for c in available['unseen_class_cases']), 2)
            self.assertEqual(result['id'], digest({k:v for k,v in result.items() if k != 'id'}))
            self.assertFalse(result['production_eligible'])
            self.assertFalse(result['world_placement_eligible'])
            self.assertFalse(result['model_weights_updated'])
            self.assertEqual(result['training_labels_generated'], 0)

    def test_repeated_building_variants_and_shared_pdfs_do_not_inflate_group_count(self):
        definitions = [('wickerman-shop', 'a'*64, ['roof']),
            ('wickerman-shop', 'b'*64, ['roof']), ('wickerman-station', 'b'*64, ['roof']),
            ('prospect-tower', 'c'*64, ['roof'])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; fixture(root, definitions)
            result = coverage.report(root)
            self.assertEqual(result['classes']['roof']['examples'], 4)
            self.assertEqual(result['classes']['roof']['source_groups'], 2)
            self.assertEqual(result['summary']['named_study_building_identities'], 3)
            self.assertEqual(result['classes']['roof']['additional_independent_groups_requested'], 1)

    def test_site_detail_contexts_are_not_counted_as_named_or_additional_buildings(self):
        definitions = [('alton-site-details-demo', 'a'*64, ['rock', 'planter']),
            ('planning-building-demo', 'b'*64, ['building']), ('unknown-object', 'c'*64, ['wall'])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; fixture(root, definitions)
            result = coverage.report(root)
            self.assertEqual(result['summary']['named_study_building_identities'], 0)
            self.assertEqual(result['summary']['additional_reviewed_building_footprint_identities'], 1)
            self.assertEqual(result['summary']['site_detail_context_identities'], 1)
            self.assertEqual(result['summary']['unclassified_identities'], 1)

    def test_requests_are_explicit_acquisition_targets_and_keep_missing_tasks_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; fixture(root)
            result = coverage.report(root, min_groups=4)
            self.assertFalse(result['group_target_is_readiness_guarantee'])
            requests = {r['kind']: r for r in result['prioritized_independent_intake_requests']}
            self.assertEqual(requests['path']['current_source_groups'], 0)
            self.assertEqual(requests['path']['additional_independent_groups_requested'], 4)
            self.assertEqual(requests['window']['additional_independent_groups_requested'], 3)
            self.assertEqual(requests['roof']['additional_independent_groups_requested'], 2)
            self.assertEqual(requests['multi_view_correspondence']['request_type'], 'new_training_task')
            self.assertEqual(result['task_coverage']['missing_path_plaza_classes'], ['path', 'plaza'])
            self.assertEqual(result['task_coverage']['complete_building_generation'], 'not_assessed')

    def test_strict_reader_rejects_changed_source_asset_and_no_report_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; manifest = fixture(root)
            (root/manifest['records'][0]['input_file']).write_bytes(b'changed')
            output = Path(tmp)/'report.json'
            with self.assertRaisesRegex(ValueError, 'asset changed'):
                coverage.write(root, output)
            self.assertFalse(output.exists())

    def test_output_is_portable_self_hashed_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'dataset'; fixture(root)
            output = Path(tmp)/'coverage.json'
            first = coverage.write(root, output)
            raw = output.read_bytes()
            self.assertEqual(json.loads(raw), first)
            self.assertNotIn(str(root), raw.decode())
            self.assertEqual(coverage.report(root), first)
            with self.assertRaises(ValueError):
                coverage.write(root, output)
            self.assertEqual(output.read_bytes(), raw)

    def test_group_target_requires_a_bounded_integer(self):
        for value in (True, 0, 1, 65, 3.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                coverage.report('/does/not/exist', min_groups=value)


if __name__ == '__main__':
    unittest.main()
