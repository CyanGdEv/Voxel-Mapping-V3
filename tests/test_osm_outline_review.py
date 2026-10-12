import copy
import unittest
from shapely.affinity import scale,translate
from shapely.geometry import mapping
from voxel_mapper.mapped_alignment_checks import check
from voxel_mapper.osm_outline_review import review
from tests import test_mapped_alignment_checks as heldout


class OutlineReviewTests(unittest.TestCase):
    def fixture(self):
        objects,refs,fits=heldout.HeldOutMapTests().fixture()
        objects[-1]['geometry']=scale(objects[-1]['geometry'],2,2)
        sources=[{'id':o['candidate_id'],'geometry':mapping(o['geometry']),'extraction_kind':'drawing_geometry',
            'extraction_contract':'test','paint_references':[{'ordinal':i}],
            'regional_window_references':[{'region_native_points':[-100,-100,500,500]}]} for i,o in enumerate(objects)]
        checks=check(objects,refs,fits,expected_scale=.1)
        return objects,refs,checks,sources

    def test_complete_closed_boundary_does_not_certify_identity_or_repair(self):
        objects,refs,checks,sources=self.fixture();original=copy.deepcopy(checks)
        refs[-1]['source_metadata']={'timestamp':'2020-01-01T00:00:00Z','version':'7'}
        result=review(objects,refs,checks,sources)
        row=next(r for r in result['reviews'] if r['candidate_id']=='4')
        self.assertEqual(row['source_trace']['status'],'native_closed_boundary_retained')
        self.assertGreater(row['source_trace']['regional_boundary_margins_pdf_points'][0],0)
        self.assertFalse(row['source_trace']['physical_outline_completeness_verified'])
        self.assertEqual(row['osm_element_metadata']['version'],'7')
        self.assertFalse(row['source_date_difference_verified'])
        self.assertEqual(row['status'],'no_compatible_retained_alternative')
        self.assertEqual(result['geometry_replacements'],0)
        self.assertEqual(checks,original)

    def test_true_alternate_outline_is_hint_under_unchanged_held_out_fit(self):
        objects,refs,checks,sources=self.fixture()
        correct=heldout.HeldOutMapTests().fixture()[0][-1]['geometry']
        objects.append({'candidate_id':'complete','geometry':correct})
        sources.append({'id':'complete','geometry':mapping(correct),'extraction_kind':'drawing_geometry','paint_references':[{'ordinal':99}]})
        result=review(objects,refs,checks,sources)
        row=next(r for r in result['reviews'] if r['candidate_id']=='4')
        self.assertEqual(row['status'],'alternative_outline_hint')
        alternate=row['alternative_source_outlines'][0]
        self.assertEqual(alternate['candidate_id'],'complete')
        self.assertLess(alternate['metrics']['boundary_error_m'],1e-8)
        self.assertFalse(alternate['already_used_in_held_out_fit'])
        self.assertTrue(row['held_out_fit_unchanged'])
        self.assertFalse(result['registration_verified'])

    def test_nearby_shifted_and_repeated_outlines_are_not_silently_selected(self):
        objects,refs,checks,sources=self.fixture();correct=heldout.HeldOutMapTests().fixture()[0][-1]['geometry']
        objects.append({'candidate_id':'wrong','geometry':translate(correct,20,0)})
        row=next(r for r in review(objects,refs,checks,sources)['reviews'] if r['candidate_id']=='4')
        self.assertEqual(row['status'],'no_compatible_retained_alternative')
        objects.extend([{'candidate_id':cid,'geometry':correct} for cid in ('a','b')])
        row=next(r for r in review(objects,refs,checks,sources)['reviews'] if r['candidate_id']=='4')
        self.assertEqual(row['status'],'ambiguous_alternative_outline_hints')
        self.assertEqual(row['alternative_source_outlines_count'],2)

    def test_alternate_map_outline_remains_an_unverified_hint(self):
        from voxel_mapper.mapped_sheet_placement import placed
        objects,refs,checks,sources=self.fixture()
        row=next(r for r in checks['hypotheses'][0]['held_out_checks'] if r['candidate_id']=='4')
        refs.append({'id':'alternate-map','geometry':placed(objects[-1]['geometry'],row['held_out_fit'])})
        result=review(objects,refs,checks,sources)
        investigation=next(r for r in result['reviews'] if r['candidate_id']=='4')
        self.assertEqual(investigation['alternative_map_outlines'][0]['reference_id'],'alternate-map')
        self.assertFalse(investigation['alternative_map_outlines'][0]['physical_identity_verified'])
        self.assertEqual(result['geometry_replacements'],0)

    def test_neighbor_and_failed_check_budgets_are_explicit(self):
        objects,refs,checks,sources=self.fixture()
        result=review(objects,refs,checks,sources,max_neighbors=1,max_failed=1)
        self.assertEqual(result['reviewed_failed_checks'],1)
        self.assertEqual(result['deferred_failed_checks'],result['failed_checks']-1)
        self.assertIn('neighbor_budget_withheld',result['review_statuses'])
        for value in (True,0,129):
            with self.assertRaises(ValueError):review(objects,refs,checks,sources,max_neighbors=value)

    def test_unchecked_fit_cannot_create_an_outline_replacement(self):
        objects,refs,fits=heldout.HeldOutMapTests().fixture();fits[0]['supports']=fits[0]['supports'][:3]
        result=review(objects,refs,check(objects,refs,fits,expected_scale=.1),[])
        self.assertEqual(result['failed_checks'],0)
        self.assertEqual(result['geometry_replacements'],0)

if __name__=='__main__':unittest.main()
