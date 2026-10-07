import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import zipfile

from voxel_mapper.planning import discover_planning, match_planning
from voxel_mapper.pipeline import run_auto
import test_terrain_osm as fixtures


def response(data):
    result = Mock()
    result.json.return_value = data
    return result


class PlanningTests(unittest.TestCase):
    bounds = [-.52, 51.39, -.50, 51.41]

    def test_discovery_retains_pages_hashes_and_empty_catalogue(self):
        authority = {'dataset':'local-planning-authority', 'entity':1, 'name':'Council'}
        application = {'dataset':'planning-application', 'entity':2, 'reference':'APP/1'}
        pages = [response({'entities':[authority], 'links':{}, 'count':1}),
                 response({'entities':[application], 'links':{'next':'unused'}, 'count':1}),
                 response({'entities':[], 'links':{}, 'count':1}),
                 response({'entities':[], 'links':{}, 'count':0}),
                 response({'dataset':'planning-application-document','entity-count':0})]
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.planning.requests.get',side_effect=pages) as get, patch('voxel_mapper.planning.time.sleep'):
            result = discover_planning(self.bounds, Path(d), page_size=2)
            self.assertEqual(len(result['records']), 2)
            self.assertEqual(result['documents']['status'], 'catalogue_empty')
            self.assertEqual(result['datasets'][2]['status'], 'empty_coverage_unknown')
            self.assertEqual(len(result['datasets'][1]['pages']), 2)
            self.assertEqual(get.call_args_list[2].kwargs['params']['offset'], 2)
            self.assertEqual(len(result['datasets'][0]['pages'][0]['sha256']), 64)
            self.assertTrue((Path(d)/'planning-discovery.json').exists())

    def test_outage_is_not_successful_empty_coverage(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.planning.requests.get',side_effect=requests.Timeout('outage')):
            result = discover_planning(self.bounds,Path(d))
            self.assertTrue(all(entry['status']=='unavailable_or_incomplete' for entry in result['datasets']))
            self.assertEqual(result['documents']['status'], 'unavailable')

    def test_global_region_has_explicit_no_adapter(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.planning.requests.get') as get:
            result = discover_planning([100,20,100.001,20.001],Path(d))
            self.assertEqual(result['status'], 'not_supported')
            get.assert_not_called()

    def test_pagination_budget_is_reported(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.planning.requests.get',side_effect=[
            response({'entities':[{'dataset':dataset,'entity':i}], 'links':{'next':'exists'}}) for i,dataset in enumerate(('local-planning-authority','planning-application','listed-building'))
        ]+[response({'dataset':'planning-application-document','entity-count':3})]):
            result = discover_planning(self.bounds,Path(d),max_pages=1,page_size=1)
            self.assertTrue(all(e['status']=='truncated' for e in result['datasets']))
            self.assertEqual(result['documents']['status'], 'catalogue_present_not_acquired')

    def fixture(self):
        coords = [[-.515,51.395],[-.514,51.395],[-.514,51.396],[-.515,51.396],[-.515,51.395]]
        feature = {'type':'Feature','id':'osm/way/1','geometry':{'type':'Polygon','coordinates':[coords]},
                   'properties':{'kind':'building','source_id':'osm','height':'8'}}
        return {'features':[feature]}

    def test_proposal_is_context_and_does_not_add_or_replace_geometry(self):
        collection = self.fixture(); original = copy.deepcopy(collection)
        discovery = {'records':[{'dataset':'planning-application','entity':2,
                     'point':'POINT(-0.5145 51.3955)','decision':'approved','height_m':90,'name':'New ride'}]}
        enriched, report = match_planning(collection, discovery, self.bounds)
        self.assertEqual(collection, original)
        self.assertEqual(enriched['features'][0]['geometry'], original['features'][0]['geometry'])
        self.assertEqual(enriched['features'][0]['properties']['height'], '8')
        self.assertEqual(report['geometry_replacements'], 0)
        self.assertEqual(report['added_physical_features'], 0)
        self.assertEqual(report['matches'][0]['status'], 'candidate_context')
        self.assertEqual(enriched['features'][0]['properties']['planning_evidence'][0]['construction_status'], 'not_verified')

    def test_ambiguity_holes_and_invalid_records(self):
        collection = self.fixture()
        duplicate = copy.deepcopy(collection['features'][0]); duplicate['id']='osm/way/2'
        collection['features'].append(duplicate)
        records = [{'dataset':'planning-application','entity':2,'point':'POINT(-0.5145 51.3955)'},
                   {'dataset':'planning-application','entity':3,'point':'nonsense'},
                   {'dataset':'planning-application','entity':4,'point':'POINT(100 20)'}]
        enriched, report = match_planning(collection, {'records':records},self.bounds)
        self.assertEqual([m['status'] for m in report['matches']], ['ambiguous_context','rejected','rejected'])
        hole = [[-.5148,51.3952],[-.5142,51.3952],[-.5142,51.3958],[-.5148,51.3958],[-.5148,51.3952]]
        collection = self.fixture(); collection['features'][0]['geometry']['coordinates'].append(hole)
        _, report = match_planning(collection,{'records':records[:1]},self.bounds)
        self.assertEqual(report['matches'][0]['status'], 'unmatched')

    def test_authority_is_separate_and_matching_budget_enforced(self):
        record = {'dataset':'local-planning-authority','entity':1,'name':'Council','point':'POINT(-0.5145 51.3955)'}
        _, report = match_planning(self.fixture(),{'records':[record]},self.bounds)
        self.assertEqual(report['authorities'][0]['name'],'Council')
        self.assertEqual(report['matches'][0]['status'],'authority_context')
        record['dataset'] = 'planning-application'
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            match_planning(self.fixture(),{'records':[record]},self.bounds,max_candidates=0)

    def test_automatic_pipeline_packages_context_without_generating_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            config, collection=fixtures.TerrainTests().fixture(root)
            source={'id':'dem','url':'https://example.org','license':'CC0','resolution_m':1}
            evidence={'provider':'planning-data-england','status':'checked', 'datasets':[],
                      'documents':{'status':'catalogue_empty'}, 'records':[
                          {'entity':9,'dataset':'planning-application','point':'POINT(0.0005 0.0005)','decision':'approved','height_m':120}]}
            with patch('voxel_mapper.pipeline.acquire_terrain', return_value=(config['terrain'],source,[])), patch('voxel_mapper.pipeline.acquire_surface',return_value=(None,None,[])), patch('voxel_mapper.pipeline.fetch_osm',return_value=(collection,{'elements':[]},[])), patch('voxel_mapper.pipeline.discover_planning',return_value=evidence):
                report=run_auto(root/'out',bounds=config['bbox'])
            self.assertEqual(report['planning_matches']['geometry_replacements'],0)
            self.assertEqual(report['planning_matches']['matches'][0]['status'],'candidate_context')
            records=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            self.assertEqual({r['y'] for r in records},{25})
            with zipfile.ZipFile(root/'out/park.mcworld') as archive:
                packaged=json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(packaged['planning_discovery']['record_count'],1)
                self.assertEqual(packaged['capabilities']['planning_drawings'],'not_implemented')
                self.assertIn('planning-data-england',archive.read('ATTRIBUTION.txt').decode())
