import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock,patch

from shapely.geometry import box, mapping

from voxel_mapper.overture import acquire_buildings, supplement_buildings
from voxel_mapper.pipeline import run_auto
import test_terrain_osm as fixtures


class OvertureTests(unittest.TestCase):
    bounds=[0,0,.001,.001]

    def building(self,identity='new',geometry=None,**extra):
        props={'type':'building','theme':'buildings','height':4,
               'sources':[{'property':'/geometry','dataset':'Microsoft','record_id':'m1','confidence':.99}]}
        props.update(extra)
        return {'type':'Feature','id':identity,'geometry':mapping(geometry or box(.0007,.0007,.0008,.0008)),
                'properties':props}

    def test_disjoint_footprint_adds_geometry_height_and_provenance_without_mutation(self):
        existing={'type':'FeatureCollection','features':[{'id':'osm/way/1','type':'Feature',
            'geometry':mapping(box(.0001,.0001,.0002,.0002)),
            'properties':{'kind':'building','source_id':'osm','height':'8'}}]}
        original=copy.deepcopy(existing)
        enriched,report=supplement_buildings(existing,{'features':[self.building()]},self.bounds,'2026-09-23.1')
        self.assertEqual(existing,original)
        self.assertEqual(enriched['features'][0],original['features'][0])
        added=enriched['features'][1]
        self.assertEqual(added['geometry'],self.building()['geometry'])
        self.assertEqual(added['properties']['height_m'],4)
        self.assertEqual(added['properties']['overture_release'],'2026-09-23.1')
        self.assertEqual(added['properties']['overture_sources'][0]['record_id'],'m1')
        self.assertEqual(report['added_physical_features'],1)
        self.assertEqual(report['geometry_replacements'],0)

    def test_overlap_nearby_and_duplicate_supplements_withheld(self):
        existing={'features':[{'id':'osm/way/1','geometry':mapping(box(.0001,.0001,.0002,.0002)),
                              'properties':{'kind':'building'}}]}
        candidates=[self.building('overlap',box(.00015,.00015,.00025,.00025)),
                    self.building('near',box(.000205,.0001,.0003,.0002)),
                    self.building('new'),self.building('same',box(.00071,.00071,.00081,.00081))]
        enriched,report=supplement_buildings(existing,{'features':candidates},self.bounds)
        self.assertEqual(len(enriched['features']),2)
        self.assertEqual(report['added_physical_features'],1)
        self.assertEqual(sum(d['status']=='rejected' for d in report['decisions']),3)
        self.assertTrue(any(d.get('conflicts')==['osm/way/1'] for d in report['decisions']))

    def test_osm_geometry_not_reintroduced_or_claimed_independent(self):
        for property_name in ('/geometry','',None):
            candidate=self.building(sources=[{'property':property_name,'dataset':'OpenStreetMap','record_id':'w1@4'}])
            enriched,report=supplement_buildings({'features':[]},{'features':[candidate]},self.bounds)
            self.assertEqual(enriched['features'],[])
            self.assertIn('OSM-derived',report['decisions'][0]['reason'])

    def test_non_ground_missing_sources_low_confidence_and_invalid_height_rejected(self):
        for extra in ({'is_underground':True},{'level':1},{'min_height':3},{'min_floor':1},
                      {'height':float('nan')},{'height':-1},{'sources':[]},
                      {'sources':[{'dataset':'Microsoft','record_id':'m1','confidence':.2}]}):
            _,report=supplement_buildings({'features':[]},{'features':[self.building(**extra)]},self.bounds)
            self.assertEqual(report['added_physical_features'],0)

    def test_holes_preserved_and_paths_protect_existing_structures(self):
        ring=box(.0006,.0006,.0009,.0009).difference(box(.0007,.0007,.0008,.0008))
        candidate=self.building(geometry=ring)
        enriched,report=supplement_buildings({'features':[]},{'features':[candidate]},self.bounds)
        self.assertEqual(len(enriched['features'][0]['geometry']['coordinates']),2)
        existing={'features':[{'id':'path','geometry':{'type':'LineString',
                       'coordinates':[[.0005,.00065],[.00095,.00065]]},'properties':{'kind':'path'}}]}
        _,report=supplement_buildings(existing,{'features':[candidate]},self.bounds)
        self.assertEqual(report['added_physical_features'],0)

    def test_invalid_geometry_identity_extent_and_shared_budget(self):
        for candidate in (self.building(identity=None),self.building(geometry=box(5,5,6,6)),
                          self.building(geometry=box(.0007,.0007,.000701,.000701))):
            _,report=supplement_buildings({'features':[]},{'features':[candidate]},self.bounds)
            self.assertEqual(report['added_physical_features'],0)
        with self.assertRaisesRegex(RuntimeError,'budget'):
            supplement_buildings({'features':[]},{'features':[self.building()]},self.bounds,max_checks=0)

    def reply(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=[b'{"latest":"2026-09-23.1"}']
        return response

    def test_acquisition_pins_release_and_preserves_hashes(self):
        with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.overture.requests.get',return_value=self.reply()),patch('voxel_mapper.overture.subprocess.run') as run:
            def download(args,**kwargs):
                Path(args[5]).write_text(json.dumps(self.building())+'\n')
                return Mock(returncode=0)
            run.side_effect=download
            collection,result=acquire_buildings(self.bounds,Path(d))
            self.assertEqual(result['status'],'downloaded')
            self.assertEqual(collection['features'][0]['id'],'new')
            self.assertEqual(run.call_args.args[0][3],'2026-09-23.1')
            self.assertEqual(result['sha256'],hashlib.sha256((Path(d)/result['file']).read_bytes()).hexdigest())
            self.assertFalse((Path(d)/'overture-buildings.partial.jsonl').exists())

    def test_timeout_partial_bad_catalog_and_failed_reader_keep_empty_results(self):
        for failure in ('timeout','failed','catalog'):
            reply=self.reply()
            if failure=='catalog':reply.iter_content.return_value=[b'{"latest":"not-a-release"}']
            with tempfile.TemporaryDirectory() as d,patch('voxel_mapper.overture.requests.get',return_value=reply),patch('voxel_mapper.overture.subprocess.run') as run:
                def download(args,**kwargs):
                    Path(args[5]).write_text(json.dumps(self.building())+'\n')
                    if failure=='timeout':raise subprocess.TimeoutExpired(args,180)
                    return Mock(returncode=1,stderr=b'Network unavailable')
                run.side_effect=download
                collection,result=acquire_buildings(self.bounds,Path(d))
                self.assertEqual(collection['features'],[])
                self.assertEqual(result['status'],'unavailable')
                self.assertTrue(result['failures'])
                self.assertFalse((Path(d)/'overture-buildings.partial.jsonl').exists())
                self.assertFalse((Path(d)/'overture-buildings.geojsonl').exists())

    def test_automatic_pipeline_inserts_building_and_packages_quality_and_attribution(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,collection=fixtures.TerrainTests().fixture(root)
            source={'id':'dem','url':'https://example.org','license':'CC0','resolution_m':1}
            discovery={'provider':'overture-buildings','status':'downloaded','release':'2026-09-23.1','failures':[],'feature_count':1}
            with patch('voxel_mapper.pipeline.acquire_terrain',return_value=(config['terrain'],source,[])),patch('voxel_mapper.pipeline.acquire_surface',return_value=(None,None,[])),patch('voxel_mapper.pipeline.fetch_osm',return_value=(collection,{'elements':[]},[])),patch('voxel_mapper.pipeline.acquire_buildings',return_value=({'features':[self.building()]},discovery)):
                report=run_auto(root/'out',bounds=config['bbox'])
            records=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            added=[r for r in records if r.get('feature')=='overture/building/new']
            self.assertTrue(added)
            self.assertEqual({r['y'] for r in added},{25,26,27,28})
            with zipfile.ZipFile(root/'out/park.mcworld') as archive:
                packaged=json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(packaged['supplemental_buildings']['matching']['added_physical_features'],1)
                self.assertIn('Overture Maps Foundation',archive.read('ATTRIBUTION.txt').decode())
            self.assertEqual(report['world']['blocks_per_metre'],1)

    def test_partition_rows_and_versioned_provider_without_upstream_record_id(self):
        from shapely import to_wkb
        from voxel_mapper.overture_worker import record_to_feature
        candidate=self.building(sources=[{'property':'','dataset':'Microsoft ML Buildings',
            'record_id':None,'confidence':None,'provider':'microsoft','resource':'ml_buildings','version':'2026-08-11'}])
        row=copy.deepcopy(candidate['properties'])
        del row['theme']; del row['type']
        row['id']='gers-1'; row['geometry']=to_wkb(box(.0007,.0007,.0008,.0008))
        feature=record_to_feature(row)
        enriched,report=supplement_buildings({'features':[]},{'features':[feature]},self.bounds,'2026-09-23.1')
        self.assertEqual(report['added_physical_features'],1)
        self.assertEqual(report['decisions'][0]['upstream_identity_status'],'provider_resource_version_only')
        self.assertEqual(enriched['features'][0]['properties']['overture_sources'][0]['record_id'],None)
        self.assertNotIn('type',row)
        with self.assertRaisesRegex(ValueError,'partition'):
            record_to_feature({**row,'type':'building_part'})
