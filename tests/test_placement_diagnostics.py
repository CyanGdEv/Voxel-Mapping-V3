import json
from pathlib import Path
import tempfile
import unittest
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.placement_diagnostics import diagnose,run


class PlacementDiagnosticTests(unittest.TestCase):
    def row(self,objects=3,attempts=2,hypotheses=None):
        return {'document_sha256':'a'*64,'page':1,'verification_objects':objects,'seed_fit_attempts':attempts,'hypotheses':hypotheses or [],'review_flags':[]}

    def test_search_reasons_distinguish_missing_polygons_seeds_and_agreement(self):
        self.assertEqual(diagnose(self.row(2),{})['reason'],'fewer_than_three_polygon_objects')
        self.assertEqual(diagnose(self.row(3,0),{})['reason'],'no_compatible_boundary_seeds')
        self.assertEqual(diagnose(self.row(),{})['reason'],'no_shared_outline_agreement')
        h={'supports':[1,2,3],'centroid_rms_m':1.2}
        self.assertEqual(diagnose(self.row(hypotheses=[h,h]),{})['reason'],'competing_mapped_placements')
        r=diagnose(self.row(hypotheses=[h]),{'sources':[{'title':'Proposed floor plan','drawing_state':'proposed'}]})
        self.assertIn('non_location_title_hint; review_original_page',r['review_flags']);self.assertIn('source_state_not_confirmed_existing',r['review_flags']);self.assertFalse(r['registration_verified'])

    def test_receipt_pin_and_unique_queue_bind_triage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);feed=root/'sheet-placements.jsonl';feed.write_text(json.dumps(self.row())+'\n');(root/'placement-report.json').write_text(json.dumps({'output_sha256':{'sheet-placements.jsonl':file_hash(feed)}}))
            queue=root/'queue';record={'document_sha256':'a'*64,'page':1,'rank':2,'sources':[]};queue.write_text(json.dumps(record)+'\n')
            r=run(root,queue,root/'triage');self.assertEqual(r['sheets'],1);self.assertEqual(r['reason_counts'],{'no_shared_outline_agreement':1})
            queue.write_text(json.dumps(record)+'\n'+json.dumps(record)+'\n')
            with self.assertRaisesRegex(ValueError,'Duplicate'):run(root,queue,root/'duplicate')
            feed.write_text(feed.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'checksum'):run(root,queue,root/'changed')

if __name__=='__main__':unittest.main()
