"""Independent placement evidence is replayed, not inferred from stored summaries."""
from copy import deepcopy
import json
import unittest

from voxel_mapper.reconstruction.model import Source, Feature, EvidenceMissing
from voxel_mapper.reconstruction.registration import (
    review_registration, require_accepted_review, apply_registration, registration_domain,
)


class RegistrationReplayTests(unittest.TestCase):
    def fixture(self, origin=(100, 200), scale=1):
        def pair(name, point):
            x, z = point
            return {'id': name, 'local': list(point),
                    'target': [origin[0] - scale * z, origin[1] + scale * x]}
        controls = [pair(str(i), p) for i, p in enumerate([(0, 0), (10, 0), (0, 10)])]
        checks = [pair('q' + str(i), p) for i, p in enumerate([(8, 8), (3, 6)])]
        return controls, checks, review_registration(controls, checks, expected_scale=scale)

    def test_unmodified_serialized_review_replays_at_metric_and_pdf_scales(self):
        for scale in (1, 100 * .0254 / 72):
            with self.subTest(scale=scale):
                _, _, report = self.fixture(scale=scale)
                report = json.loads(json.dumps(report))
                require_accepted_review(report)
                point = apply_registration([[5, 5]], report)[0]
                self.assertAlmostEqual(point[0], 100 - 5 * scale)
                self.assertAlmostEqual(point[1], 200 + 5 * scale)

    def test_four_metre_shift_is_rejected_despite_old_accepted_status_and_zero_summary(self):
        _, _, report = self.fixture()
        report['translation_m'][0] += 4
        self.assertEqual(report['status'], 'accepted_horizontal_fit')
        self.assertLess(report['checkpoint_error']['max_m'], 1e-8)
        with self.assertRaises(ValueError):
            apply_registration([[5, 5]], report)
        with self.assertRaises(ValueError):
            registration_domain(report)

    def test_sub_tolerance_shift_at_bng_origin_still_requires_a_matching_pose(self):
        _, _, report = self.fixture(origin=(407500, 343500))
        report['translation_m'][0] += .2  # Below the one-metre limit, above numerical replay noise.
        with self.assertRaisesRegex(ValueError, 'differs from replayed'):
            require_accepted_review(report)

    def test_serialized_pose_must_satisfy_even_a_tolerance_smaller_than_replay_epsilon(self):
        controls, checks, _ = self.fixture()
        report = review_registration(controls, checks, tolerance_m=1e-9)
        report['translation_m'][0] += 5e-8
        with self.assertRaisesRegex(ValueError, 'exceeds control/checkpoint tolerance'):
            require_accepted_review(report)

    def test_changed_checkpoint_and_control_coordinates_invalidate_saved_review(self):
        for group in ('checkpoint_pairs', 'control_pairs'):
            with self.subTest(group=group):
                _, _, report = self.fixture()
                report[group][0]['target'][0] += 4
                with self.assertRaises(ValueError):
                    require_accepted_review(report)

    def test_failed_checkpoint_evidence_cannot_be_promoted_by_editing_status(self):
        controls, checks, _ = self.fixture()
        checks[0]['target'][0] += 4
        report = review_registration(controls, checks)
        self.assertEqual(report['status'], 'withheld')
        report.update(status='accepted_horizontal_fit', reasons=[], checkpoint_error={'rms_m': 0, 'max_m': 0})
        with self.assertRaises(ValueError):
            require_accepted_review(report)

    def test_matrix_shapes_reflection_shear_and_nonfinite_values_fail(self):
        for field, value in [('matrix', [[0, -1], [-1, 0]]), ('matrix', [[.02, -1], [1, 0]]),
                             ('matrix', [[0, -1]]), ('matrix', [[0, -1], [True, 0]]),
                             ('translation_m', [float('nan'), 200]), ('translation_m', ['100', 200])]:
            with self.subTest(field=field, value=value):
                _, _, report = self.fixture()
                report[field] = value
                with self.assertRaises(ValueError):
                    require_accepted_review(report)

    def test_summary_and_identity_changes_are_not_treated_as_new_evidence(self):
        for fault in ('control_error', 'checkpoint_error', 'scale', 'rotation_degrees', 'controls', 'checkpoints'):
            with self.subTest(fault=fault):
                _, _, report = self.fixture()
                if fault.endswith('_error'):
                    report[fault]['max_m'] = .25
                elif fault in ('controls', 'checkpoints'):
                    report[fault][0] += '-changed'
                else:
                    report[fault] += .25
                with self.assertRaises(ValueError):
                    require_accepted_review(report)

    def test_original_inputs_are_snapshotted_including_nested_provenance(self):
        controls, checks, _ = self.fixture()
        controls[0]['provenance'] = {'source': ['original']}
        report = review_registration(controls, checks)
        before = deepcopy(report)
        controls[0]['target'][0] += 20
        controls[0]['provenance']['source'][0] = 'changed'
        checks[0]['target'][1] += 20
        self.assertEqual(report, before)
        require_accepted_review(report)

    def test_legacy_or_incomplete_saved_review_needs_fresh_evidence_replay(self):
        for key in ('version', 'fit_parameters', 'control_pairs', 'checkpoint_pairs'):
            with self.subTest(key=key):
                _, _, report = self.fixture()
                report.pop(key)
                with self.assertRaises(ValueError):
                    require_accepted_review(report)

    def test_changed_expected_scale_and_non_numeric_point_evidence_fail(self):
        _, _, report = self.fixture()
        report['fit_parameters']['expected_scale'] = 2
        with self.assertRaises(ValueError):
            require_accepted_review(report)
        controls, checks, _ = self.fixture()
        for value in (True, '0', float('nan')):
            controls[0]['local'][0] = value
            with self.assertRaises(ValueError):
                review_registration(controls, checks)

    def test_world_feature_with_stale_pose_is_withheld_inside_the_original_domain(self):
        _, _, report = self.fixture()
        report['translation_m'][0] += 4
        source = Source('plan', 'planning', 'fixture://plan', 'test', 'EPSG:27700',
                        registration_status='accepted', metadata={'horizontal_registration_review': report})
        feature = Feature('point', 'marker', {'type': 'Point', 'coordinates': [99, 205]}, 'plan')
        with self.assertRaises(EvidenceMissing):
            feature.validate({'plan': source}, None)
