import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from shapely.affinity import affine_transform,translate
from shapely.geometry import box,mapping,shape
from voxel_mapper.cross_drawing_alignment import match_page,collect_landmarks,run
from voxel_mapper.evidence_memory import EvidenceMemory

SHA='a'*64


def fixture():
    geometries=[box(0,0,60,30),box(200,10,240,60),box(20,300,40,380)]
    objects=[{'id':str(i),'geometry':mapping(g)} for i,g in enumerate(geometries)]
    landmarks=[{'id':'anchor-'+str(i),'feature':{'family':'wall','geometry':mapping(affine_transform(g,[0,-.1,.1,0,1000,2000]))},
        'target_crs':'EPSG:27700','document_sha256':'b'*64,'independent_root_sha256s':['c'*64,'d'*64]}
        for i,g in enumerate(geometries)]
    return objects,landmarks


class CrossDrawingTests(unittest.TestCase):
    def match(self,objects,landmarks,**options):
        return match_page(objects,landmarks,document_sha256=SHA,target_crs='EPSG:27700',expected_scale=.1,**options)

    def test_rotation_scale_and_context_find_one_frame_without_prepared_pairs(self):
        objects,landmarks=fixture();result=self.match(objects,landmarks)
        self.assertTrue(result['unique_contextual_proposal'],result)
        fit=result['hypotheses'][0]
        self.assertEqual(len(fit['supports']),3)
        self.assertAlmostEqual(fit['scale_metres_per_pdf_point'],.1)
        self.assertAlmostEqual(fit['translation_m'][0],1000)
        self.assertAlmostEqual(fit['translation_m'][1],2000)
        self.assertFalse(result['registration_verified'])
        self.assertEqual(result['training_labels_generated'],0)

    def test_two_equivalent_neighbourhoods_remain_ambiguous(self):
        objects,landmarks=fixture()
        alternate=[{**r,'id':r['id']+'-alt','feature':{**r['feature'],
            'geometry':mapping(translate(shape(r['feature']['geometry']),100,100))}}
            for r in landmarks]
        result=self.match(objects,landmarks+alternate)
        self.assertFalse(result['unique_contextual_proposal'])
        self.assertIn('multiple_sheet_placements',result['review_flags'])

    def test_source_or_root_self_alignment_is_excluded(self):
        objects,landmarks=fixture()
        for field in ['document_sha256','independent_root_sha256s']:
            refs=copy.deepcopy(landmarks)
            for r in refs:r[field]=SHA if field=='document_sha256' else [SHA]
            self.assertEqual(self.match(objects,refs)['eligible_landmarks'],0)

    def test_unmatched_scale_and_nested_shapes_do_not_prove_a_frame(self):
        objects,landmarks=fixture()
        for r in landmarks:r['feature']['geometry']=mapping(box(0,0,100,100))
        self.assertEqual(self.match(objects,landmarks)['hypotheses'],[])
        objects,landmarks=fixture()
        result=self.match(objects,landmarks,max_pair_fits=1)
        self.assertIn('pair_fit_budget_exhausted',result['review_flags'])
        self.assertFalse(result['unique_contextual_proposal'])
        self.assertEqual(self.match(objects*22,landmarks)['status'],'matching_budget_withheld')

    def test_registered_bridge_landmarks_retain_dependencies_and_rejections(self):
        from tests.test_drawing_registration_bridge import BridgeTests
        from voxel_mapper.drawing_registration_bridge import run_batch
        test=BridgeTests();test.setUp()
        try:
            inputs=test.batch_inputs();store=test.root/'memory.sqlite'
            report=run_batch(*inputs,test.root/'bridge',knowledge_store=store)
            with EvidenceMemory(store) as memory:
                anchors=collect_landmarks(memory)
                self.assertEqual(len(anchors),3)
                self.assertEqual(collect_landmarks(memory),anchors)
                parent=report['knowledge_memory']['page_facts'][0]['id']
                memory.reject(parent,reviewer='qa',reason='incorrect control identity',review_reference='test/1')
                self.assertEqual(collect_landmarks(memory),[])
                self.assertEqual(memory.report()['facts']['invalidated'],3)
        finally:test.tearDown()

    def test_real_pdf_cache_keeps_empty_pages_and_rechecks_original_bytes(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            with pymupdf.open() as doc:
                doc.new_page();page=doc.new_page()
                page.draw_rect((20,20,100,100));page.insert_text((20,200),'Scale 1:100')
                data=doc.tobytes()
            try:
                corpus.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test'])
                corpus.acquire(fetch=lambda _:data);extract(corpus,root/'geometry')
                store=root/'memory.sqlite'
                first=run(corpus,root/'geometry',store,root/'output',target_crs='EPSG:27700')
                self.assertEqual(first['pages'],2)
                with patch('voxel_mapper.cross_drawing_alignment.match_page',side_effect=AssertionError('Recomputed')):
                    again=run(corpus,root/'geometry',store,root/'new-output',target_crs='EPSG:27700')
                self.assertEqual(again['reused_pages'],2)
                self.assertEqual(first['output_sha256'],again['output_sha256'])
                same=run(corpus,root/'geometry',store,root/'output',target_crs='EPSG:27700')
                self.assertEqual(same['run_pages'],0)
                from voxel_mapper.area_reconstruction import run as area_run
                from voxel_mapper.generation_cycles import file_hash
                pdf=next((corpus.root/'files').glob('*.pdf'))
                (root/'catalogue.json').write_text(json.dumps({'entries':[{'applicationReference':'A',
                    'url':'https://portal.test/a','title':'Plan','sha256':file_hash(pdf)}]}))
                job={'work_directory':'area-work','catalogue':'catalogue.json','official_hosts':['portal.test'],
                    'offline':True,'source_directories':['corpus/files'],
                    'cross_drawing_alignment':{'enabled':True,'target_crs':'EPSG:27700'},
                    'areas':[{'id':'a','name':'A','application_references':['A'],'required_families':['local_building']}]}
                (root/'job.json').write_text(json.dumps(job))
                area=area_run(root/'job.json')['areas']['a']
                self.assertEqual(area['cross_drawing_alignment']['pages'],2)
                self.assertEqual(area['cross_drawing_alignment']['registrations_accepted'],0)
                resumed=area_run(root/'job.json')['areas']['a']['cross_drawing_alignment']
                self.assertEqual(resumed['run_pages'],0)
                with pymupdf.open() as extra:
                    extra.new_page();extra_bytes=extra.tobytes()
                corpus.ingest([{'url':'https://portal.test/b','title':'Other drawing'}],['portal.test'])
                corpus.acquire(fetch=lambda _:extra_bytes,interval=0)
                extract(corpus,root/'geometry')
                expanded=run(corpus,root/'geometry',store,root/'expanded',target_crs='EPSG:27700')
                self.assertEqual(expanded['pages'],3)
                self.assertEqual(expanded['reused_pages'],2)
                self.assertEqual(expanded['run_pages'],1)
                pdf=next((corpus.root/'files').glob('*.pdf'));pdf.write_bytes(pdf.read_bytes()+b'corrupt')
                with self.assertRaisesRegex(ValueError,'Pinned source PDF'):
                    run(corpus,root/'geometry',store,root/'output',target_crs='EPSG:27700')
            finally:corpus.close()
