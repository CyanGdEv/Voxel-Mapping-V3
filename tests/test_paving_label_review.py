import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper import paving_label_review as review
from voxel_mapper import paving_masks as masks
from voxel_mapper.generation_cycles import atomic_json
from test_paving_masks import fixture


class PavingLabelReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.items, self.annotations = fixture(self.root)
        self.dataset = self.root/'dataset'
        masks.build(self.items, self.annotations, self.dataset)

    def ready(self):
        data = review.payload(self.dataset); data['reviewer'] = 'Synthetic test reviewer'
        data['attestation'] = True
        data['decisions'] = {c: {t['id']: 'keep' for t in ts} for c, ts in data['annotations']['crops'].items()}
        return data

    def apply(self, data, name='result'):
        path = self.root/'review.json'; atomic_json(path, data)
        return review.apply(self.dataset, path, self.root/name)

    def test_source_only_page_is_offline_and_escapes_trace_text(self):
        # Regenerate a valid source dataset with a malicious literal reason.
        a = json.loads(self.annotations.read_text()); a['crops']['crop'][0]['reason'] = '</script><script>alert(1)</script>'
        atomic_json(self.annotations, a); masks.build(self.items, self.annotations, self.root/'escaped')
        page = self.root/'review.html'; result = review.create(self.root/'escaped', page)
        text = page.read_text()
        self.assertIn('data:image/png;base64,', text); self.assertIn('\\u003c/script>', text)
        self.assertNotIn('/* REVIEW_DATA */', text); self.assertNotIn('fetch(', text)
        self.assertEqual(result['traces'], 3); self.assertFalse(result['human_labels_verified'])

    def test_unknown_review_creates_fresh_masks_without_mutating_source(self):
        original = (self.dataset/'dataset.json').read_bytes(); data = self.ready()
        data['annotations']['crops']['crop'][0]['label'] = 'unknown'
        data['decisions']['crop']['walk'] = 'unknown'
        report = self.apply(data)
        self.assertGreater(report['changes'][0]['labelled_to_unknown_pixels'], 0)
        self.assertFalse(report['human_labels_verified']); self.assertFalse(report['training_run'])
        self.assertEqual((self.dataset/'dataset.json').read_bytes(), original)
        result = masks.validate(self.root/'result')
        old = masks.validate(self.dataset)
        self.assertEqual(result['records'][0]['source_sha256'], old['records'][0]['source_sha256'])
        self.assertEqual(result['records'][0]['crop_pixels'], old['records'][0]['crop_pixels'])

    def test_unchanged_review_has_zero_changes_and_remains_provisional(self):
        report = self.apply(self.ready())
        self.assertEqual(report['changes'][0]['changed_pixels'], 0)
        self.assertFalse(report['review_identity_independently_verified'])

    def test_changed_keep_missing_decision_false_attestation_and_source_swap_rejected(self):
        variants = []
        d = self.ready(); d['annotations']['crops']['crop'][0]['outer'][0][0] += 1; variants.append(d)
        d = self.ready(); del d['decisions']['crop']['walk']; variants.append(d)
        d = self.ready(); d['attestation'] = False; variants.append(d)
        d = self.ready(); d['source_pins']['crop']['image_sha256'] = '0'*64; variants.append(d)
        d = self.ready(); d['annotations']['boundary_ignore_pixels'] = 0; variants.append(d)
        d = self.ready(); d['reviewer'] = ''; variants.append(d)
        d = self.ready(); d['annotations']['crops']['crop'][0]['outer'][0][0] = 1000; variants.append(d)
        d = self.ready(); d['decisions']['crop']['walk'] = 'unknown'; variants.append(d)
        for i, data in enumerate(variants):
            with self.subTest(i=i), self.assertRaises((ValueError, KeyError)):
                self.apply(data, 'invalid'+str(i))
            self.assertFalse((self.root/('invalid'+str(i))).exists())

    def test_added_trace_requires_explicit_decision_and_valid_polygon(self):
        data = self.ready(); new = {'id': 'new_roof', 'label': 'non_paving',
            'outer': [[0, 0], [5, 0], [5, 5], [0, 5]], 'reason': 'Synthetic roof correction'}
        data['annotations']['crops']['crop'].append(new)
        data['decisions']['crop']['new_roof'] = 'correct'
        report = self.apply(data)
        self.assertGreater(report['changes'][0]['unknown_to_labelled_pixels'], 0)

    def test_reserved_test_refused_for_both_create_and_apply(self):
        reserved = self.root/'reserved'; masks.build(self.items, self.annotations, reserved, reserved_test=True)
        with self.assertRaisesRegex(ValueError, 'Reserved test'):
            review.create(reserved, self.root/'bad.html')
        receipt = self.root/'review.json'; atomic_json(receipt, self.ready())
        with self.assertRaisesRegex(ValueError, 'Reserved test'):
            review.apply(reserved, receipt, self.root/'bad')


if __name__ == '__main__':
    unittest.main()
