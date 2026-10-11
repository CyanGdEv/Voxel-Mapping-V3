import copy
import json
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import box,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.linework_boundaries import recover_page,run
from voxel_mapper.linework_envelopes import combine


class EnvelopeTests(unittest.TestCase):
    def records(self,rings):
        return recover_page(fixtures.LineworkTests().parents(rings))[0]

    def test_adjacent_rooms_recover_exact_outline_and_provenance(self):
        records=self.records([list(box(0,0,60,40).exterior.coords),[(20,0),(20,40)],[(40,0),(40,40)]])
        envelopes,report=combine(records)
        self.assertEqual(len(envelopes),1);candidate=envelopes[0]
        self.assertTrue(shape(candidate['geometry']).equals(box(0,0,60,40)))
        self.assertEqual(len(candidate['face_parent_ids']),3)
        self.assertFalse(candidate['physical_identity_verified']);self.assertEqual(candidate['world_geometry_additions'],0)
        from voxel_mapper.drawing_footprints import reviewed_feature
        with self.assertRaisesRegex(ValueError,'explicit source'):reviewed_feature(candidate,{},None,{},'EPSG:27700')

    def test_gap_and_point_contact_do_not_become_one_outline(self):
        for second in [box(20.000001,0,40,20),box(20,20,40,40)]:
            envelopes,_=combine(self.records([list(box(0,0,20,20).exterior.coords),list(second.exterior.coords)]))
            self.assertEqual(envelopes,[])

    def test_recovered_hole_is_not_filled_by_its_nested_face(self):
        records=self.records([list(box(0,0,100,100).exterior.coords),list(box(20,20,80,80).exterior.coords)])
        envelopes,report=combine(records)
        self.assertEqual(envelopes,[]);self.assertGreater(report['counts']['nested_hole_links_withheld'],0)

    def test_input_order_and_duplicate_identity_do_not_change_output(self):
        records=self.records([list(box(0,0,60,40).exterior.coords),[(20,0),(20,40)],[(40,0),(40,40)]])
        first=combine(records)[0];second=combine(list(reversed(records)))[0]
        self.assertEqual(first,second)

    def test_mixed_pages_are_refused(self):
        records=self.records([list(box(0,0,60,40).exterior.coords),[(20,0),(20,40)]])
        faces=[r for r in records if r['extraction_kind']=='linework_boundaries']
        faces[-1]={**faces[-1],'page':2}
        with self.assertRaisesRegex(ValueError,'One retained'):combine(faces)

    def test_native_pdf_replay_source_tamper_and_optional_pipeline(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.footprint_matching import NativeNames
        from voxel_mapper.park_pipeline import run as park
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            with pymupdf.open() as document:
                page=document.new_page(width=300,height=300)
                for a,b in zip(box(20,20,160,100).exterior.coords,list(box(20,20,160,100).exterior.coords)[1:]):page.draw_line(a,b)
                page.draw_line((80,20),(80,100));data=document.tobytes()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Plan'}],['portal.test']);corpus.acquire(fetch=lambda _:data)
                extract(corpus,root/'drawing-geometry');feed=root/'drawing-geometry/geometry-candidates.jsonl'
                receipt=run(corpus,feed,root/'envelopes',envelopes=True)
                self.assertEqual(receipt['counts']['envelopes'],1)
                self.assertEqual(run(corpus,feed,root/'envelopes',envelopes=True),receipt)
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(corpus,feed,root/'envelopes')
                rows=[json.loads(s) for s in (root/'envelopes/boundary-candidates.jsonl').read_text().splitlines()]
                candidate=next(r for r in rows if r['extraction_kind']=='linework_envelopes')
                names=NativeNames(corpus,[])
                try:
                    names.get(candidate)
                    with self.assertRaisesRegex(ValueError,'differs'):names.get({**candidate,'face_parent_ids':[]})
                finally:names.close()
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},
                    'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},
                    'linework_boundaries':{'enabled':True,'envelopes':True}}))
                report=park(job,'acquire');self.assertEqual(report['stages']['linework_boundaries']['counts']['envelopes'],1)
                pdf=corpus.root/'files'/f"{receipt['source_documents'][0]}.pdf";pdf.write_bytes(pdf.read_bytes()+b'changed')
                with self.assertRaisesRegex(ValueError,'Source PDF'):run(corpus,feed,root/'envelopes',envelopes=True)
            finally:corpus.close()
