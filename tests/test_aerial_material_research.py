import copy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from urllib.parse import urlencode
from voxel_mapper import aerial_material_research as aerial, web_evidence as web
from test_web_evidence import Session, Response, resolver


def config(provider='esri_world_imagery'):
    return {'version':aerial.VERSION,'site_id':'public-park','site':'Public Park','provider':provider,
        'bounds_wgs84':[-1.89,52.989,-1.889,52.990],'width':128,'height':128,'grid':4,'exclude_footer_pixels':0,'offline':True}


def fixture(root):
    data=np.zeros((128,128,4),dtype=np.uint8);data[:,:,3]=255
    data[:64,:64,:3]=[20,130,30];data[:64,64:,:3]=[20,20,20]
    data[64:,:64,:3]=[160,75,50];data[64:,64:,:3]=[140,140,140]
    path=root/'source.png';Image.fromarray(data).save(path)
    receipt={'provider':'esri_world_imagery','image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'extent_epsg3857':[-210000,6980000,-209800,6980200],'width':128,'height':128,'sources':[]}
    return path,receipt


def cache_fixture(root,c):
    path,receipt=fixture(root);b=c['bounds_wgs84']
    endpoint=aerial.ESRI+'/export?'+urlencode({'bbox':','.join(map(str,b)),'bboxSR':4326,'imageSR':3857,'size':'128,128','format':'png','f':'json'})
    target='https://server.arcgisonline.com/example.png';x0,y0,x1,y1=receipt['extent_epsg3857']
    raw=json.dumps({'href':target,'width':128,'height':128,'extent':{'xmin':x0,'ymin':y0,'xmax':x1,'ymax':y1,'spatialReference':{'wkid':3857}}}).encode()
    for url,data,mime in [(endpoint,raw,'application/json'),(target,path.read_bytes(),'image/png')]:
        web.fetch(url,root/'cache',['server.arcgisonline.com'],session=Session([Response(data=data,headers={'Content-Type':mime})]),resolver=resolver)


class AerialMaterialResearchTests(unittest.TestCase):
    def test_rgb_samples_keep_real_extent_and_withhold_shadows_and_vegetation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=fixture(Path(tmp));rows=aerial.sample(path,receipt,4,0)
            self.assertEqual(len(rows),16)
            self.assertEqual(rows[0]['median_rgb'],[20,130,30]);self.assertEqual(rows[0]['colour_cue'],'vegetation_colour')
            self.assertEqual(rows[2]['colour_cue'],'shadow_or_dark_surface')
            self.assertTrue(rows[2]['palette_use_withheld'])
            self.assertEqual(rows[8]['colour_cue'],'warm_brown_or_red_surface')
            self.assertTrue(all(not r['material_verified'] and not r['training_eligible'] for r in rows))
            self.assertEqual(rows[0]['geometry']['type'],'Polygon')
            self.assertEqual(rows[0]['geometry']['coordinates'][0][0],rows[0]['geometry']['coordinates'][0][-1])
            self.assertTrue(all('delta_e76' in r['block_palette_candidates'][0] for r in rows))

    def test_lab_conversion_matches_standard_black_and_white_reference_values(self):
        np.testing.assert_allclose(aerial._lab([0,0,0]),[0,0,0],atol=1e-8)
        np.testing.assert_allclose(aerial._lab([255,255,255]),[100,0,0],atol=.001)

    def test_source_pin_dimensions_transparency_and_cancellation_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=fixture(Path(tmp));wrong={**receipt,'width':129}
            with self.assertRaisesRegex(ValueError,'dimensions'):aerial.sample(path,wrong,4,0)
            with self.assertRaises(aerial.CancelledError):aerial.sample(path,receipt,4,0,cancelled=lambda:True)
            data=np.zeros((128,128,4),np.uint8);Image.fromarray(data).save(path)
            receipt['image_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(all(r['status']=='insufficient_opaque_pixels' for r in aerial.sample(path,receipt,4,0)))
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):aerial.sample(path,receipt,4,0)

    def test_offline_esri_job_retains_original_bytes_and_no_accepted_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config();cache_fixture(root,c)
            result=aerial.run(c,root/'out',root/'cache')
            self.assertEqual(result['sample_cells'],16);self.assertEqual(result['network_bytes'],0)
            self.assertEqual(result['material_assignments_accepted'],0)
            self.assertEqual((root/'out/source-image.bin').read_bytes(),(root/'source.png').read_bytes())
            self.assertFalse(result['imagery']['point_metadata_applies_to_whole_image'])
            self.assertEqual(result['world_blocks_generated'],0)

    def test_bing_missing_key_is_explicit_and_does_not_fetch_or_leak_credentials(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BING_MAPS_KEY':''}):
            c=config('bing_aerial');c['offline']=False
            with patch.object(aerial,'_bing_get') as get:
                result=aerial.run(c,Path(tmp)/'out',Path(tmp)/'cache')
            get.assert_not_called();self.assertEqual(result['status'],'awaiting_bing_maps_key')
            self.assertEqual(result['sample_cells'],0);self.assertIn('www.bing.com/maps?',result['bing_viewer_url'])

    def test_bing_adapter_uses_returned_bbox_and_reuses_key_free_retained_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,receipt=fixture(root);c=config('bing_aerial');c['offline']=False
            metadata={'statusCode':200,'authenticationResultCode':'ValidCredentials','copyright':'Microsoft fixture',
                'resourceSets':[{'resources':[{'bbox':[52.988,-1.891,52.991,-1.888],'imageWidth':128,'imageHeight':128}]}]}
            with patch.dict(os.environ,{'BING_MAPS_KEY':'synthetic-fixture-secret'}),patch.object(aerial,'_bing_get',side_effect=[json.dumps(metadata).encode(),path.read_bytes()]) as get:
                result=aerial.run(c,root/'first',root/'cache')
            self.assertEqual(get.call_count,2);self.assertTrue(result['imagery']['extent_epsg3857'][0]<-210000)
            self.assertEqual(result['sample_cells'],16)
            with patch.dict(os.environ,{'BING_MAPS_KEY':''}):
                second=aerial.run(c,root/'second',root/'cache')
            self.assertEqual(result['imagery']['image_sha256'],second['imagery']['image_sha256'])
            self.assertFalse(any(b'synthetic-fixture-secret' in p.read_bytes() for p in root.rglob('*') if p.is_file()))
            saved=next((root/'cache').rglob('receipt.json'));edited=json.loads(saved.read_text());edited['extent_epsg3857'][0]+=1;saved.write_text(json.dumps(edited))
            with self.assertRaisesRegex(ValueError,'changed'):aerial.run(c,root/'tampered',root/'cache')

    def test_bing_transport_errors_redact_request_url_and_reject_redirects(self):
        import requests
        with patch.object(web,'_public_dns'):
            session=Session([requests.ConnectionError('https://dev.virtualearth.net/?key=do-not-log')])
            with self.assertRaises(web.WebError) as e:aerial._bing_get({},'do-not-log',cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget(),session=session)
            self.assertNotIn('do-not-log',str(e.exception))
            with self.assertRaises(web.WebError):aerial._bing_get({},'do-not-log',cancelled=lambda:False,deadline=time.monotonic()+10,budget=web.Budget(),session=Session([Response(status=302)]))

    def test_desktop_worker_can_analyse_retained_aerial_rgb(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config();desktop=root/'desktop';cache_fixture(root,c)
            import shutil
            shutil.copytree(root/'cache',desktop/'web-cache')
            path=root/'request.json';path.write_text(json.dumps(c));runtime=DesktopRuntime(desktop,workers=1,memory_budget_mb=2048)
            try:
                jid=runtime.submit('aerial_material_research',path);runtime._futures[jid].result(timeout=30)
                job=runtime.store.job(jid);self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertEqual(job['result']['sample_cells'],16)
                self.assertIn('aerial_rgb_observation',runtime.store.context(20000))
            finally:runtime.close(wait=True)

    def test_learning_cycle_consumes_rgb_without_retraining_unchanged_dataset(self):
        from test_research_learning_cycle import ResearchLearningCycleTests
        from voxel_mapper import research_learning_cycle as cycle
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=ResearchLearningCycleTests().config(root);c['max_research_jobs']=0;a=config();cache_fixture(root,a)
            c['public_sites'][0]['aerial_context']={k:v for k,v in a.items() if k not in ['version','site','site_id']}
            first=cycle.run(c,root/'first',root/'memory',root/'cache')
            second=cycle.run(c,root/'second',root/'memory',root/'cache')
            self.assertEqual(first['aerial_reports'][0]['sample_cells'],16)
            self.assertEqual(first['remembered_sources'],2)
            self.assertEqual(first['checkpoint_sha256'],second['checkpoint_sha256'])
            self.assertFalse(second['model_weights_updated']);self.assertEqual(second['web_sources_automatically_labelled'],0)


if __name__=='__main__':unittest.main()
