import copy
import json
from pathlib import Path
import unittest
from shapely.geometry import LineString,box,mapping
from voxel_mapper.wing_outline_review import compare,junctions,run


class OutlineTests(unittest.TestCase):
    def test_complete_cycles_retain_panes_and_surrounds_without_selection(self):
        seed=[{'id':'window','points_pixels':[(10,10),(30,10),(30,30),(10,30)]}]
        frames=[{'id':'outer','geometry_pixels':mapping(box(9,9,31,31))},
                {'id':'pane','geometry_pixels':mapping(box(10,10,20,30))}]
        result=compare(seed,frames)
        self.assertEqual(result['rows'][0]['status'],'competing_source_cycles')
        self.assertEqual(len(result['rows'][0]['candidates']),2)
        self.assertFalse(result['rows'][0]['mesh_update_authorized'])
        self.assertEqual(result,compare(seed,list(reversed(frames))))

    def test_late_comparison_budget_discards_earlier_rows(self):
        rows=[{'id':str(i),'points_pixels':[(10,10),(30,10),(30,30),(10,30)]} for i in range(2)]
        result=compare(rows,[{'id':'a','geometry_pixels':mapping(box(10,10,30,30))}],max_checks=1)
        self.assertEqual(result['status'],'outline_comparison_budget_withheld');self.assertEqual(result['rows'],[])
        with self.assertRaises(ValueError):compare([{'id':'a','points_pixels':[(0,0),(float('nan'),0),(1,1)]}],[])

    def records(self):
        return [{'id':'a','document_sha256':'a'*64,'page':1,'coordinate_frame':'pdf_native_points_y_up',
                 'geometry':mapping(LineString([(0,1),(4,1)])),
                 'paint_references':[{'stroke_style':{'dashes_pdf':'[] 0'}}]}]

    def review(self,records=None,**kwargs):
        return junctions(self.records() if records is None else records,[1,0,0,1,0,0],
                         {'facade_endpoints':[(0,0),(0,20)],'rear_point':(10,10)},**kwargs)

    def test_partial_offset_junction_is_proximity_only_and_preserves_source(self):
        records=self.records();original=copy.deepcopy(records);r=self.review(records)
        self.assertEqual(records,original)
        self.assertAlmostEqual(r['rows'][0]['proximity_fraction'],.4)
        self.assertEqual(r['rows'][1]['proximity_fraction'],0)
        self.assertFalse(r['rows'][0]['end_wall_exterior_identity_verified'])
        self.assertFalse(r['mesh_update_authorized'])
        self.assertEqual(r['rows'][0]['source_segment_proofs'][0]['native_endpoints'],[[0,1],[4,1]])

    def test_full_drawing_support_still_does_not_prove_exterior_or_height(self):
        records=self.records();records[0]['geometry']=mapping(LineString([(0,0),(10,0)]))
        row=self.review(records)['rows'][0]
        self.assertEqual(row['proximity_fraction'],1)
        self.assertFalse(row['end_wall_height_verified']);self.assertFalse(row['mesh_update_authorized'])

    def test_dashed_curved_and_wrong_source_junctions_remain_withheld(self):
        for change in ({'curve_approximation':{'cubic_segments':1}},
                       {'paint_references':[{'stroke_style':{'dashes_pdf':'[2 2] 0'}}]}):
            records=self.records();records[0].update(change);self.assertEqual(self.review(records)['rows'][0]['proximity_fraction'],0)
        records=self.records();records.append({**records[0],'id':'other','page':2})
        with self.assertRaises(ValueError):self.review(records)

    def test_junction_budget_discards_partial_proofs(self):
        result=self.review(max_checks=2)
        self.assertEqual(result['status'],'junction_budget_withheld');self.assertEqual(result['rows'],[])
        with self.assertRaises(ValueError):self.review(max_checks=True)

    def test_source_and_receipt_tampering_reject_replay(self):
        from tests.test_local_wing_review import WingReviewTests
        f=WingReviewTests();f.setUp()
        try:
            seed=f.root/'seed.json';seed.write_text(json.dumps(f.recipe));output=f.root/'review'
            result=run(seed,f.paths,output);self.assertFalse(result['reused']);self.assertTrue(run(seed,f.paths,output)['reused'])
            for field,value,message in [('state','proposed','Existing'),('caption','Different view','caption'),
                                        ('render_samples_sha256','0'*64,'raster')]:
                altered=copy.deepcopy(f.recipe);altered['documents']['plan'][field]=value
                seed.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError,message):run(seed,f.paths,f.root/field)
            seed.write_text(json.dumps(f.recipe))
            Path(result['outline_path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'receipt changed'):run(seed,f.paths,output)
            f.paths['plan'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):run(seed,f.paths,f.root/'fresh')
        finally:f.tearDown()

if __name__=='__main__':unittest.main()
