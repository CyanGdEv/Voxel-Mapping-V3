import copy
import json
from pathlib import Path
import unittest
from shapely.geometry import LineString,mapping
from voxel_mapper.native_opening_inventory import frame_candidates,associate,reconcile_seed,label_identity,run


def edges(bounds=(10,10,30,40)):
    x0,y0,x1,y1=bounds
    pairs=[[(x0,y0),(x1,y0)],[(x1,y0),(x1,y1)],[(x1,y1),(x0,y1)],[(x0,y1),(x0,y0)]]
    return [{'id':str(i),'document_sha256':'a'*64,'page':1,'coordinate_frame':'pdf_native_points_y_up',
             'geometry':mapping(LineString(pair)),'paint_references':[{'stroke_style':{'dashes_pdf':'[] 0'}}]}
            for i,pair in enumerate(pairs)]


def frames(records,**options):
    return frame_candidates(records,[0,0,100,100],[1,0,0,1,0,0],.1,**options)


def label(name='w.3.01',bounds=(16,42,24,45),visible=True):
    return {**label_identity(name),'bounds_pixels':list(bounds),
            'glyph_screen':{'status':'raster_consistent_candidate' if visible else 'withheld'}}


class NativeOpeningTests(unittest.TestCase):
    def test_exact_cycle_has_original_interval_proofs_but_no_aperture_authority(self):
        report=frames(edges());self.assertEqual(len(report['frames']),1)
        frame=report['frames'][0];self.assertEqual(frame['nominal_width_m'],2)
        self.assertEqual({s['side'] for s in frame['source_side_support']},{'left','right','top','bottom'})
        for side in frame['source_side_support']:
            self.assertEqual(side['source_intervals'][0]['interval_fractions'],[0,1])
        self.assertFalse(frame['physical_boundary_verified'])
        self.assertFalse(associate([label()],report['frames'])['labels'][0]['complete_aperture_verified'])

    def test_gap_is_not_bridged_even_when_tiny(self):
        rows=edges();rows[0]['geometry']=mapping(LineString([(10,10),(29.999999,10)]))
        self.assertEqual(frames(rows)['frames'],[])

    def test_continuous_original_intervals_can_support_one_side(self):
        rows=edges();rows[0]['geometry']=mapping(LineString([(10,10),(20,10)]))
        other=copy.deepcopy(rows[0]);other['id']='extra';other['geometry']=mapping(LineString([(20,10),(30,10)]))
        result=frames(rows+[other])['frames'][0]
        self.assertEqual(len(next(s for s in result['source_side_support'] if s['side']=='top')['source_intervals']),2)

    def test_dashed_curved_and_truncated_components_cannot_close_frame(self):
        for change in [{'paint_reference_truncated':True},{'curve_approximation':{'cubic_segments':1}},
                       {'paint_references':[{'stroke_style':{'dashes_pdf':'[1 2] 0'}}]}]:
            rows=edges();rows[0].update(change);self.assertEqual(frames(rows)['frames'],[])

    def test_budget_exhaustion_withholds_all_frames_and_all_associations(self):
        self.assertEqual(frames(edges(),max_checks=3)['status'],'frame_discovery_budget_withheld')
        self.assertEqual(frames(edges(),max_checks=3)['frames'],[])
        f=frames(edges())['frames']
        self.assertEqual(associate([label(),label('w.3.02')],f,max_checks=1)['labels'],[])

    def test_nested_alternatives_retained_without_largest_selection(self):
        rows=edges()+[{**r,'id':'inner'+r['id']} for r in edges((12,12,28,40))]
        fs=frames(rows)['frames'];result=associate([label()],fs)['labels'][0]
        self.assertGreater(len(result['frame_candidates']),1)
        self.assertGreater(len(result['nested_source_frames']),0)
        self.assertEqual(result['status'],'competing_source_frame_layout_candidates')

    def test_hidden_labels_have_no_links_and_repeated_ids_are_explicit(self):
        fs=frames(edges())['frames']
        self.assertEqual(associate([label(visible=False)],fs)['labels'][0]['frame_candidates'],[])
        self.assertTrue(all(r['status']=='repeated_source_label_identity' for r in associate([label(),label()],fs)['labels']))

    def test_seed_disagreement_and_untraced_label_are_reported_without_rewrite(self):
        seed=[{'id':'w3.06-a','kind':'window','points_pixels':[[10,10],[30,10],[30,40],[10,40]]}]
        original=copy.deepcopy(seed)
        report=reconcile_seed(seed,[label('w.3.05'),label('w.3.13',(60,60,70,65))])
        self.assertEqual(report['rows'][0]['status'],'source_label_disagreement')
        self.assertEqual(report['source_labels_without_seed_trace'],['w.3.13'])
        self.assertEqual(seed,original);self.assertFalse(report['automatic_seed_rewrite'])

    def test_mixed_source_and_invalid_transform_rejected(self):
        rows=edges();rows[0]['page']=2
        with self.assertRaisesRegex(ValueError,'One original'):frames(rows)
        with self.assertRaisesRegex(ValueError,'Finite ordered'):
            frame_candidates(edges(),[0,0,100,100],[1,0,0,1,float('nan'),0],.1)

    def test_label_syntax_does_not_accept_incidental_prose(self):
        self.assertEqual(label_identity(' w . 3 . 05 ')['canonical_id'],'w.3.05')
        self.assertEqual(label_identity('a r c h w a y 3')['kind'],'archway')
        self.assertIsNone(label_identity('opening w.3.05 proposed'))

    def test_rotated_native_segments_retain_original_coordinates(self):
        rows=edges();before=copy.deepcopy(rows)
        result=frame_candidates(rows,[0,0,100,100],[0,-1,1,0,0,100],.1)
        self.assertEqual(result['frames'][0]['bounds_pixels'],[10,70,40,90])
        self.assertEqual(rows,before)

    def test_invalid_seed_polygon_rejected_before_layout_association(self):
        seed=[{'id':'w3.01','kind':'window','points_pixels':[[10,10],[30,10],[30,float('nan')]]}]
        with self.assertRaisesRegex(ValueError,'finite'):reconcile_seed(seed,[label()])

    def test_source_pins_replay_and_receipt_mutation(self):
        from tests.test_local_wing_review import WingReviewTests
        fixture=WingReviewTests();fixture.setUp()
        try:
            path=fixture.root/'recipe.json';path.write_text(json.dumps(fixture.recipe));out=fixture.root/'inventory'
            first=run(path,fixture.paths['elevation'],out)
            self.assertTrue(run(path,fixture.paths['elevation'],out)['reused'])
            Path(first['inventory_path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'fresh output'):run(path,fixture.paths['elevation'],out)
            fixture.recipe['documents']['elevation']['state']='proposed';path.write_text(json.dumps(fixture.recipe))
            with self.assertRaisesRegex(ValueError,'existing'):run(path,fixture.paths['elevation'],out)
            fixture.recipe['documents']['elevation']['state']='existing';path.write_text(json.dumps(fixture.recipe))
            fixture.paths['elevation'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):run(path,fixture.paths['elevation'],out)
        finally:fixture.tearDown()
