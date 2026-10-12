from io import BytesIO
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pypdf.errors import PdfReadError
import pymupdf
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,TextStringObject,ArrayObject,FloatObject,DictionaryObject
from tests import test_architectural_view_layout as layout_fixtures
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.architectural_graph import build
from voxel_mapper.architectural_view_layout import review as layout_review
from voxel_mapper.architectural_view_boundaries import review


class ViewBoundaryTests(unittest.TestCase):
    def fixture(self,root,viewports=None):
        doc,page,_,_=layout_fixtures.ViewLayoutTests().source();page.draw_line((250,80),(250,350))
        writer=PdfWriter();writer.add_page(PdfReader(BytesIO(doc.tobytes())).pages[0]);doc.close()
        if viewports is not None:
            objects=[]
            for name,bounds in viewports:
                obj=DictionaryObject({NameObject('/Type'):NameObject('/Viewport'),NameObject('/Name'):TextStringObject(name),
                    NameObject('/BBox'):ArrayObject([FloatObject(v) for v in bounds])})
                objects.append(writer._add_object(obj))
            writer.pages[0][NameObject('/VP')]=ArrayObject(objects)
        output=BytesIO();writer.write(output);data=output.getvalue();sha=hashlib.sha256(data).hexdigest()
        path=root/'source.pdf';path.write_bytes(data)
        document=pymupdf.open(path);parents,_=extract_page(document[0],sha,1,min_line_length_points=.25,max_candidates=10000)
        graph=build(parents);layout=layout_review(document[0],sha,1,graph)
        return document,path,sha,graph,layout

    def test_native_named_viewport_retains_whole_crossing_components(self):
        with tempfile.TemporaryDirectory() as directory:
            doc,path,sha,graph,layout=self.fixture(Path(directory),[('South Elevation',[10,350,400,590])])
            try:
                before=copy.deepcopy((graph,layout));report=review(path,sha,1,graph,layout);row=report['viewports'][0]
                self.assertTrue(row['source_declared_boundary_supported']);self.assertTrue(row['source_named_caption_supported'])
                self.assertEqual(row['printed_caption_claim']['printed_scale_denominator'],50)
                self.assertIn('source_viewport_boundary_crossing',{r['status'] for r in row['component_membership']})
                self.assertFalse(report['view_scope_verified']);self.assertFalse(row['scale_application_verified'])
                self.assertEqual(report['world_geometry_additions'],0);self.assertEqual((graph,layout),before)
            finally:doc.close()

    def test_no_metadata_does_not_promote_printed_rectangles_or_caption_bands(self):
        with tempfile.TemporaryDirectory() as directory:
            doc,path,sha,graph,layout=self.fixture(Path(directory))
            try:
                report=review(path,sha,1,graph,layout)
                self.assertEqual(report['status'],'no_source_viewport_declarations');self.assertEqual(report['viewports'],[])
                self.assertEqual(report['counts']['named_caption_candidates'],0)
            finally:doc.close()

    def test_duplicate_names_hidden_captions_and_outside_crop_are_withheld(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for viewports,status in (
                ([('South Elevation',[10,350,400,590])]*2,'competing_source_viewport_declarations'),
                ([('Wrong View',[10,350,400,590])],'viewport_name_caption_mismatch'),
                ([('X'*600,[10,350,400,590])],'viewport_name_budget_withheld'),
                ([('South Elevation',[10,350,600,590])],'viewport_outside_native_crop'),
                ([('South Elevation',[10,10,490,590])],'missing_competing_or_boundary_crossing_caption')):
                doc,path,sha,graph,layout=self.fixture(root,viewports)
                try:
                    report=review(path,sha,1,graph,layout)
                    self.assertTrue(all(r['status']==status and not r['source_named_caption_supported'] for r in report['viewports']))
                finally:doc.close()
            doc,path,sha,graph,layout=self.fixture(root,[('South Elevation',[10,350,400,590])])
            try:
                hidden=copy.deepcopy(layout);hidden['view_captions'][0]['glyph_screen']['status']='withheld'
                self.assertEqual(review(path,sha,1,graph,hidden)['viewports'][0]['status'],'caption_visibility_withheld')
            finally:doc.close()

    def test_budget_checksum_and_graph_layout_source_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            doc,path,sha,graph,layout=self.fixture(Path(directory),[('South Elevation',[10,350,400,590])])
            try:
                with patch('voxel_mapper.architectural_view_boundaries.PdfReader',side_effect=PdfReadError('unsupported')):
                    withheld=review(path,sha,1,graph,layout)
                    self.assertEqual(withheld['status'],'source_metadata_parser_withheld')
                    self.assertEqual(withheld['viewports'],[])
                report=review(path,sha,1,graph,layout,max_checks=1)
                self.assertEqual(report['status'],'viewport_budget_withheld')
                self.assertEqual(report['counts']['named_caption_candidates'],0)
                self.assertTrue(all(r['component_membership']==[] for r in report['viewports']))
                with self.assertRaises(ValueError):review(path,sha,1,graph,layout,max_checks=True)
                broken=copy.deepcopy(layout);broken['source_graph_sha256']='changed'
                with self.assertRaises(ValueError):review(path,sha,1,graph,broken)
                path.write_bytes(path.read_bytes()+b'changed')
                with self.assertRaisesRegex(ValueError,'checksum'):review(path,sha,1,graph,layout)
            finally:doc.close()


if __name__=='__main__':unittest.main()
