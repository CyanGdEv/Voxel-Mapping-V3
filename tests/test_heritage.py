import json
import tempfile
from pathlib import Path
import unittest
from shapely.geometry import box
from voxel_mapper.reconstruction.heritage import acquire, inventory, nhle_adapter
from voxel_mapper.reconstruction.model import Source
from voxel_mapper.reconstruction.inventory import source_inventory


def sample():
    attrs = {'ListEntry': 1192015, 'Name': 'PROSPECT TOWER', 'Grade': 'II*', 'CaptureScale': '1:2500'}
    return {'layers': {
        '0': {'spatialReference': {'wkid': 27700}, 'features': [{'attributes': attrs, 'geometry': {'points': [[100,100]]}}]},
        '3': {'spatialReference': {'wkid': 27700}, 'features': [{'attributes': attrs, 'geometry': {'rings': [[[99,99],[101,99],[100,101],[99,99]]]}}]}}}


class HeritageTests(unittest.TestCase):
    def test_marker_not_extruded_even_with_accepted_registration(self):
        source = Source('nhle','heritage','https://example.test','OGL','EPSG:27700', registration_status='accepted')
        features, candidates = nhle_adapter(sample(), source)
        self.assertEqual(features, [])
        self.assertEqual(candidates[0]['polygon_role'], 'triangular_location_symbol')
        self.assertEqual(inventory(sample())['world_blocks_added'], 0)
        result = source_inventory({}, [], {}, [], candidates)
        self.assertEqual(result['candidates_by_family'], {'heritage_asset': 1})

    def test_actual_polygon_still_needs_review(self):
        data=sample();data['layers']['3']['features'][0]['geometry']['rings']=[[[99,99],[101,99],[101,101],[99,101],[99,99]]]
        self.assertEqual(inventory(data)['candidates'][0]['polygon_role'], 'unreviewed_listing_geometry')

    def test_boundary_holes_and_multipoints(self):
        data=sample(); boundary=box(90,90,110,110).difference(box(99,99,101,101))
        self.assertEqual(inventory(data,boundary)['candidates'], [])
        data['layers']['0']['features'][0]['geometry']['points'].append([105,105])
        self.assertEqual(len(inventory(data,boundary)['candidates']),1)

    def test_truncated_error_and_wrong_crs_rejected(self):
        for change in ({'exceededTransferLimit':True},{'error':{'code':500}},{'spatialReference':{'wkid':4326}}):
            data=sample();data['layers']['0'].update(change)
            with self.assertRaises(ValueError):inventory(data)

    def test_bad_locations_and_duplicates_rejected(self):
        for points in ([], [[float('nan'), 1]], [[1,2,3]]):
            data=sample();data['layers']['0']['features'][0]['geometry']['points']=points
            with self.assertRaises(ValueError):inventory(data)
        data=sample();data['layers']['0']['features']*=2
        with self.assertRaises(ValueError):inventory(data)

    def test_feed_registry_keeps_candidates_in_report_only(self):
        from voxel_mapper.reconstruction.sources import AdapterRegistry
        source = Source('nhle','heritage','https://example.test','OGL','EPSG:27700')
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'input.json').write_text(json.dumps(sample()))
            features,reports=AdapterRegistry().load([{'source':'nhle','adapter':'nhle','file':'input.json'}], {'nhle':source}, 'EPSG:27700',folder)
        self.assertEqual(features,[])
        self.assertEqual(reports[0]['decisions'][0]['id'],'nhle/1192015')

    def test_retained_alton_snapshot_is_reproducible(self):
        import hashlib
        root=Path(__file__).resolve().parents[1]/'voxel_mapper'/'data'
        content=(root/'alton-heritage-source.json').read_bytes()
        saved=json.loads((root/'alton-heritage-inventory.json').read_text())
        report=inventory(json.loads(content))
        self.assertEqual(saved['input_sha256'],hashlib.sha256(content).hexdigest())
        self.assertEqual(report['candidates'],saved['candidates'])
        self.assertEqual(len(report['candidates']),31)
        self.assertIn('nhle/1192054',{r['id'] for r in report['candidates']})

    def test_query_budget_before_network(self):
        for bounds in ([0,0,10000,10000],[0,0,0,1],[0,0,float('inf'),1]):
            with self.assertRaises(ValueError):acquire(bounds)

    def test_bounded_requests_and_no_partial_second_layer(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return sample()['layers']['0']
        class Session:
            def __init__(self):self.calls=[]
            def get(self,url,**kwargs):self.calls.append((url,kwargs));return Response()
        session=Session();data=acquire([90,90,110,110],session)
        self.assertEqual(len(session.calls),2)
        self.assertEqual(session.calls[0][1]['params']['outSR'],27700)
        self.assertEqual(len(inventory(data)['candidates']),1)

if __name__=='__main__':unittest.main()
