import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import drawing_caption_inventory as captions
from voxel_mapper import drawing_side_references as side


class DrawingCaptionInventoryTests(unittest.TestCase):
    def page(self, document, header='2967-42', caption='Elevation 9 to the North'):
        page = document.new_page(width=500, height=500)
        page.insert_text((330, 450), header, fontsize=10)
        page.insert_text((40, 250), caption, fontsize=10)
        return page

    def fixture(self, root):
        sources = root / 'sources'; sources.mkdir(); entries = []
        for target in (False, True):
            with pymupdf.open() as doc:
                if target:
                    self.page(doc, '2967-30', 'Elevation 8 to the West')
                else:
                    page = doc.new_page(width=500, height=500)
                    page.insert_text((330, 450), '2967-48', fontsize=10)
                    page.draw_circle((200, 200), 17)
                    page.draw_line((212.02, 187.98), (224., 200.))
                    page.draw_line((224., 200.), (212.02, 212.02))
                    page.insert_text((194, 203), '30', fontsize=8)
                    page.insert_text((231, 203), '8', fontsize=8)
                raw = doc.tobytes()
            sha = hashlib.sha256(raw).hexdigest(); (sources / (sha + '.pdf')).write_bytes(raw)
            entries.append({'sha256': sha})
        with pymupdf.open(sources / (entries[0]['sha256'] + '.pdf')) as doc:
            review = side.page_references(doc[0])
        self.assertEqual(len(review['references']), 1)
        self.assertEqual(review['references'][0]['target_view_key_candidate'], ['2967', 30, 8])
        parent = root / 'references.json'
        parent.write_text(json.dumps({'status': 'roof_reference_evidence_only', 'target_links': [],
            'roof_page_references': [{'document_sha256': entries[0]['sha256'], 'page': 1, 'side_reference_review': review}]}))
        catalogue = root / 'catalogue.json'; catalogue.write_text(json.dumps({'entries': entries}))
        return parent, catalogue, sources, root / 'output'

    def test_caption_needs_neither_crop_nor_scale_to_be_found(self):
        with pymupdf.open() as doc:
            page = self.page(doc); row = captions.inventory(page, 'a'*64, lambda: None)['captions'][0]
            self.assertEqual(row['source_caption_key_candidate'], ['2967', 42, 9])
            self.assertEqual(row['status'], 'source_caption_candidate')
            self.assertFalse(row['artwork_assignment_verified']); self.assertFalse(row['scale_application_verified'])

    def test_failed_caption_or_header_visibility_remains_held(self):
        for hidden in ('Elevation 9', '2967-42'):
            with pymupdf.open() as doc:
                page = self.page(doc)
                def screen(page, span):
                    text = ''.join(chr(c[0]) for c in span['chars'])
                    return {'status': 'withheld' if text.startswith(hidden) else 'raster_consistent_candidate'}
                with patch.object(captions.glyph_visibility, 'screen_span', side_effect=screen):
                    row = captions.inventory(page, 'a'*64, lambda: None)['captions'][0]
                self.assertNotIn('source_caption_key_candidate', row)

    def test_overpainted_caption_is_not_a_visible_target(self):
        with pymupdf.open() as doc:
            page = self.page(doc); page.draw_rect((30, 235, 280, 255), color=None, fill=(1, 1, 1))
            row = captions.inventory(page, 'a'*64, lambda: None)['captions'][0]
            self.assertNotIn('source_caption_key_candidate', row)

    def test_conflicting_or_absent_sheet_identity_is_held(self):
        for conflicting in (False, True):
            with pymupdf.open() as doc:
                page = self.page(doc, header='2967-42' if conflicting else 'notes')
                if conflicting: page.insert_text((330, 470), '2967-30', fontsize=10)
                row = captions.inventory(page, 'a'*64, lambda: None)['captions'][0]
                self.assertNotIn('source_caption_key_candidate', row)

    def test_noncaption_prose_and_numbers_do_not_supply_targets(self):
        with pymupdf.open() as doc:
            page = self.page(doc, caption='See Elevation 9 to the North')
            self.assertEqual(captions.inventory(page, 'a'*64, lambda: None)['captions'], [])

    def test_rotation_and_original_source_are_preserved(self):
        with pymupdf.open() as doc:
            page = self.page(doc); page.set_rotation(90)
            before = copy.deepcopy(page.get_texttrace()); row = captions.inventory(page, 'a'*64, lambda: None)
            self.assertEqual(page.rotation, 90); self.assertEqual(page.get_texttrace(), before)
            self.assertEqual(row['captions'][0]['title_bbox_pdf_unrotated'], list(before[1]['bbox']))

    def test_exact_key_join_never_chooses_nearest_or_other_project(self):
        ref = {'id': 'r', 'target_view_key_candidate': ['2967', 42, 9]}
        targets = [{'id': 'other-project', 'source_caption_key_candidate': ['2968', 42, 9]},
                   {'id': 'other-view', 'source_caption_key_candidate': ['2967', 42, 10]}]
        self.assertEqual(captions.link([ref], targets, [], lambda: None)[0]['status'], 'source_caption_missing')
        targets.append({'id': 'exact', 'source_caption_key_candidate': ref['target_view_key_candidate']})
        row = captions.link([ref], targets, [], lambda: None)[0]
        self.assertEqual(row['caption_candidates'], ['exact']); self.assertFalse(row['geometry_export_authorized'])

    def test_competing_witnesses_and_held_reference_never_resolve(self):
        ref = {'id': 'r', 'target_view_key_candidate': ['2967', 42, 9]}
        target = {'id': 'a', 'source_caption_key_candidate': ref['target_view_key_candidate']}
        row = captions.link([ref], [target, {**target, 'id': 'b'}], [], lambda: None)[0]
        self.assertEqual(row['status'], 'competing_source_caption_candidates')
        self.assertEqual(captions.link([{'id': 'r'}], [target], [], lambda: None)[0]['caption_candidates'], [])

    def test_previous_measurement_status_is_retained_without_promotion(self):
        ref = {'id': 'r', 'target_view_key_candidate': ['2967', 42, 9]}
        previous = {'source_reference_id': 'r', 'status': 'missing_source_view_target'}
        target = {'id': 'a', 'source_caption_key_candidate': ref['target_view_key_candidate']}
        row = captions.link([ref], [target], [previous], lambda: None)[0]
        self.assertEqual(row['previous_measurement_link'], previous)
        self.assertEqual(row['next_requirement'], 'artwork_assignment_and_scale')
        self.assertFalse(row['artwork_assignment_verified'])

    def test_complete_build_replays_and_keeps_parent_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); before = args[0].read_bytes(); result = captions.build(*args)
            self.assertEqual(result, captions.build(*args)); self.assertEqual(args[0].read_bytes(), before)
            self.assertEqual(result['counts']['unique_caption_links'], 1)
            self.assertFalse(result['previous_source_holds_overridden']); self.assertEqual(result['world_geometry_additions'], 0)

    def test_work_exhaustion_at_marker_or_join_stage_clears_all_partial_results(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); result = captions.build(*args, max_checks=1)
            self.assertEqual(result['status'], 'source_caption_coverage_budget_withheld')
            with patch.object(captions, 'link', side_effect=OverflowError('late')):
                result = captions.build(*args)
            self.assertEqual(result['pages'], []); self.assertEqual(result['reference_links'], [])
            self.assertEqual(result['source_references'], [])

    def test_pdf_parent_markers_and_cached_report_tampering_are_rejected(self):
        for mode in ('pdf', 'parent', 'cache'):
            with tempfile.TemporaryDirectory() as temp:
                args = self.fixture(Path(temp))
                if mode == 'pdf': next(args[2].glob('*.pdf')).write_bytes(b'changed')
                elif mode == 'parent':
                    parent = json.loads(args[0].read_text()); parent['roof_page_references'][0]['side_reference_review']['references'][0]['circle_path_index'] += 1
                    args[0].write_text(json.dumps(parent))
                else:
                    result = captions.build(*args); (Path(result['directory']) / 'drawing-caption-coverage.json').write_text('{}')
                with self.assertRaises(ValueError): captions.build(*args)

    def test_inputs_changed_during_link_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp)); original = captions.link
            def changed(*values):
                result = original(*values); args[0].write_text('{}'); return result
            with patch.object(captions, 'link', side_effect=changed), self.assertRaises(ValueError): captions.build(*args)

    def test_invalid_budgets_and_catalogue_hashes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.fixture(Path(temp))
            for limit in (True, 0, 100001):
                with self.assertRaises(ValueError): captions.build(*args, max_checks=limit)
            args[1].write_text(json.dumps({'entries': [{'sha256': '../escape'}]}))
            with self.assertRaises(ValueError): captions.build(*args)

    def test_independent_audit_of_original_caption_and_reference_keys(self):
        from scripts.audit_drawing_caption_coverage import audit
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); args = self.fixture(root); report = captions.build(*args)
            receipt = audit(report['directory'], *args[:3], root / 'audit.json')
            self.assertEqual(receipt['status'], 'passed')
            self.assertEqual(receipt['checked']['independent_exact_caption_joins'], 1)
