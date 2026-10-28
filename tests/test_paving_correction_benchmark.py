import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from pyproj import Transformer

from voxel_mapper import paving_masks as masks, paving_binary_learning as binary
from voxel_mapper import paving_correction_benchmark as benchmark
from voxel_mapper.desktop_memory import digest
from voxel_mapper.generation_cycles import atomic_json, file_hash
from test_paving_binary_learning import fixture


class CorrectionBenchmarkTests(unittest.TestCase):
    def test_literal_towers_recipe_has_expected_changes_and_preserves_other_crops(self):
        root = Path(__file__).resolve().parents[1]/'voxel_mapper/data'
        recipe = json.loads((root/'towers-paving-correction.json').read_text())
        annotation = root/'paving-mask-annotations.json'
        self.assertEqual(file_hash(annotation), recipe['parent_annotation_sha256'])
        original = json.loads(annotation.read_text()); corrected = copy.deepcopy(original)
        corrected['crops'][recipe['crop_id']].extend(recipe['add_traces'])
        a, _ = masks.rasterize(original['crops'][recipe['crop_id']], (330,620))
        b, reasons = masks.rasterize(corrected['crops'][recipe['crop_id']], (330,620))
        self.assertEqual(int((a!=b).sum()), recipe['expected_changes']['changed_pixels'])
        self.assertEqual(int((reasons==masks.REASONS['conflicting_traces']).sum()), 0)
        for p in recipe['probes']:
            x,y=p['xy'];self.assertEqual(int(a[y,x]),p['before']);self.assertEqual(int(b[y,x]),p['after'])
        for cid in original['crops']:
            if cid!=recipe['crop_id']:self.assertEqual(original['crops'][cid],corrected['crops'][cid])

    def test_gate_requires_non_regression_and_available_boundary_evidence(self):
        score = {'paving_iou': .7, 'paving_precision': .8, 'paving_recall': .75,
            'boundary': {'f1': .6}, 'connections': {'recall': 1.}}
        scores = {'baseline_rgb': score, 'corrected_rgb': copy.deepcopy(score)}
        development = {'baseline_rgb_macro_iou': .5, 'corrected_rgb_macro_iou': .51}
        self.assertTrue(benchmark.adoption(scores, development)['passes_numeric_gate'])
        self.assertFalse(benchmark.adoption(scores, development)['automatic_adoption'])
        scores['corrected_rgb']['boundary']['f1'] = None
        self.assertIn('boundary evidence unavailable', benchmark.adoption(scores, development)['reasons'])
        scores['corrected_rgb']['paving_precision'] = .79
        self.assertIn('paving_precision decreased', benchmark.adoption(scores, development)['reasons'])
        development['corrected_rgb_macro_iou'] = .49
        self.assertIn('whole-park macro IoU decreased', benchmark.adoption(scores, development)['reasons'])

    def test_real_models_seal_replay_and_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); data, _ = fixture(root)
            binary.train(data, root/'training', {'epochs': 1, 'hidden': 8})
            source = root/'new.png'; rgb = np.full((64,64,3), [155,140,125], np.uint8)
            rgb[:,32:] = [48,100,58]; Image.fromarray(rgb).save(source)
            receipt = root/'new.json'; atomic_json(receipt, {'width':64, 'height':64,
                'image_sha256':file_hash(source), 'extent_epsg3857':[10000.,10000.,10064.,10064.]})
            ann = root/'test-ann.json'; atomic_json(ann, {'version':masks.ANNOTATIONS,
                'review_policy':masks.POLICY, 'boundary_ignore_pixels':1, 'crops':{'newcrop':[
                    {'id':'pave','label':'paving','outer':[[0,0],[15,0],[15,32],[0,32]],'reason':'Synthetic'},
                    {'id':'other','label':'non_paving','outer':[[17,0],[32,0],[32,32],[17,32]],'reason':'Synthetic'}]}})
            item = {'id':'newcrop','site_id':'newpark','source_record_id':'new',
                'source_file':str(source),'source_sha256':file_hash(source),'metadata_file':str(receipt),
                'metadata_sha256':file_hash(receipt),'crop_pixels':[16,16,48,48]}
            test = root/'test'; manifest = masks.build([item],ann,test,reserved_test=True)
            inverse = Transformer.from_crs(3857,4326,always_xy=True)
            west,south = inverse.transform(10000,10000);east,north = inverse.transform(10064,10064)
            protocol = root/'protocol.json'; value = {'version':'paving-correction-test-protocol-v1',
                'reserved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'test_site_id':'newpark','test_crop_id':'newcrop','bounds_wgs84':[west,south,east,north],
                'native_export_dimensions':[64,64],'methods':[*benchmark.METHODS,'always_paving'],
                'boundary_ignore_pixels':1,
                'head_settings':json.loads((root/'training/models/rgb_only/model.json').read_text())['network']['settings'],
                'score_threshold':.5,'boundary_tolerance_native_pixels':2}
            atomic_json(protocol,value)
            dev = root/'development.json'; atomic_json(dev, {'development_dataset_sha256':file_hash(data/'dataset.json'),
                'baseline_rgb_macro_iou':.5,'corrected_rgb_macro_iou':.5})
            frozen = root/'frozen.json'; f = {'frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'protocol_sha256':file_hash(protocol),'development_dataset_sha256':file_hash(data/'dataset.json'),
                'models':{name:{'file':'training/models/'+('rgb_only' if name.endswith('_rgb') else 'rgb_context')+'/model.json',
                    'sha256':file_hash(root/'training/models'/('rgb_only' if name.endswith('_rgb') else 'rgb_context')/'model.json')}
                    for name in benchmark.METHODS}}
            atomic_json(frozen,f)
            seal = root/'seal.json'; s = {'sealed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'test_manifest_sha256':file_hash(test/'dataset.json'),'test_annotation_sha256':manifest['annotation_sha256'],
                'frozen_models_sha256':file_hash(frozen),'development_comparison_sha256':file_hash(dev),
                'connection_probes':{'newcrop':[{'id':'left','a_xy':[4,5],'b_xy':[8,25]}]}}
            atomic_json(seal,s);args = [test,frozen,seal,protocol,dev]
            first = benchmark.evaluate(*args,root/'first');again = benchmark.evaluate(*args,root/'again')
            self.assertEqual(first['results'],again['results']);self.assertTrue(again['identical_sealed_input_replay'])
            self.assertFalse(first['results'][0]['adoption_gate']['passes_numeric_gate'])
            # A changed set of target probes cannot reuse a consumed evaluation.
            s['connection_probes']['newcrop'] = [];atomic_json(seal,s)
            with self.assertRaisesRegex(ValueError,'consumed'):benchmark.evaluate(*args,root/'changed')
            s['connection_probes']['newcrop'] = [{'id':'left','a_xy':[4,5],'b_xy':[8,25]}];atomic_json(seal,s)
            # A pinned checkpoint is still checked for test-source leakage.
            path = root/f['models']['baseline_rgb']['file']; original = path.read_bytes();model=json.loads(original)
            model['training_source_sha256'].append(item['source_sha256'])
            model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'})
            atomic_json(path,model)
            with self.assertRaisesRegex(ValueError,'checkpoint changed'):benchmark.evaluate(*args,root/'tamper')
            for name in ('baseline_rgb','corrected_rgb'):f['models'][name]['sha256']=file_hash(path)
            atomic_json(frozen,f);s['frozen_models_sha256']=file_hash(frozen);atomic_json(seal,s)
            with self.assertRaisesRegex(ValueError,'leaked'):benchmark.evaluate(*args,root/'leaked')
            path.write_bytes(original)


if __name__ == '__main__': unittest.main()
