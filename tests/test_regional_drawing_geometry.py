import unittest
import pymupdf
from voxel_mapper.drawing_geometry import extract_page

class RegionalGeometryTests(unittest.TestCase):
    def test_region_preserves_whole_primitives_and_identity(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            page.draw_rect((50,50,100,100))
            page.draw_line((20,200),(300,200))
            whole,_=extract_page(page,'a'*64,1)
            for rotation in (0,90,180,270):
                page.set_rotation(rotation)
                rows,report=extract_page(page,'a'*64,1,region_native_points=[10,10,150,390])
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['id'],next(r['id'] for r in whole if r['geometry']['type']=='Polygon'))
                self.assertEqual(rows[0]['geometry'],next(r['geometry'] for r in whole if r['geometry']['type']=='Polygon'))
                self.assertEqual(report['rejections']['complete_primitive_crosses_region_boundary'],1)
                self.assertEqual(page.rotation,rotation)
    def test_local_path_budget_and_global_scan_budget_withhold_whole_region(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            page.draw_rect((50,50,100,100));page.draw_rect((250,250,300,300))
            self.assertEqual(len(extract_page(page,'a'*64,1,max_paths=1,region_native_points=[10,200,150,390])[0]),1)
            rows,report=extract_page(page,'a'*64,1,max_paths=1,region_native_points=[10,10,390,390])
            self.assertEqual(rows,[]);self.assertEqual(report['status'],'region_path_budget_withheld')
            rows,report=extract_page(page,'a'*64,1,max_scan_paths=1,region_native_points=[10,200,150,390])
            self.assertEqual(rows,[]);self.assertEqual(report['status'],'path_budget_withheld')
    def test_compound_primitive_is_not_split_by_region(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);drawing=page.new_shape()
            drawing.draw_line((50,50),(100,50));drawing.draw_line((250,250),(300,250))
            drawing.finish(closePath=False);drawing.commit()
            self.assertFalse(extract_page(page,'a'*64,1,region_native_points=[10,200,150,390])[0])
    def test_region_options_reject_bad_bounds(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            for bounds in ([0,0,0,1],[0,0,float('nan'),1],[-1,0,100,100],[True,0,100,100]):
                with self.assertRaises(ValueError):extract_page(page,'a'*64,1,region_native_points=bounds)

    def test_overlapping_grid_deduplicates_and_hashes_output(self):
        import hashlib
        import json
        from pathlib import Path
        import tempfile
        from voxel_mapper.regional_drawing_geometry import run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'source.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page(width=400,height=400)
                page.draw_rect((185,185,215,215));doc.save(pdf)
            result=run(pdf,root/'out',columns=2,rows=2,overlap_points=30)
            self.assertEqual(result['unique_candidates'],1)
            self.assertEqual(result['overlap_duplicates'],3)
            content=(root/'out/geometry-candidates.jsonl').read_bytes()
            self.assertEqual(result['candidate_file_sha256'],hashlib.sha256(content).hexdigest())
            self.assertFalse(json.loads(content)['physical_identity_verified'])
            self.assertEqual(run(pdf,root/'out',columns=2,rows=2,overlap_points=30)['candidate_file_sha256'],result['candidate_file_sha256'])

    def test_region_retains_clip_scope_from_outside_window(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.draw_line((0,0),(1,1))
            doc.update_stream(page.get_contents()[0],b'q 100 100 50 50 re W n 80 125 m 180 125 l S Q')
            rows,report=extract_page(page,'a'*64,1,region_native_points=[20,20,300,300])
            self.assertFalse(rows)
            self.assertIn('Paint group crosses clipping boundary',report['rejections'])
