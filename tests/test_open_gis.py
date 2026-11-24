import json
import tempfile
import unittest
from pathlib import Path
from shapely.geometry import box, mapping
from voxel_mapper.open_gis import SOURCES, acquire, collect, fuse

class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload

def feature(ident, geom):
    return {"type":"Feature","id":ident,"properties":{"OBJECTID":ident},"geometry":mapping(geom)}

class GIS(unittest.TestCase):
    def setUp(self):
        self.layer = SOURCES[0]
        self.bounds = (-2,52,-1,53)

    def get(self, url, params, timeout):
        if not url.endswith("/query"):
            return Response({"objectIdField":"OBJECTID","supportedQueryFormats":"JSON, geoJSON","maxRecordCount":1})
        if params.get("returnIdsOnly"):
            self.assertEqual(params["inSR"],4326)
            return Response({"objectIds":[2,1]})
        i = int(params["objectIds"])
        self.assertEqual(params["outSR"],4326)
        return Response({"type":"FeatureCollection","features":[feature(i,box(-2.1,52.1+i/10,-1.9,52.15+i/10))]})

    def test_acquire_paginates_and_clips(self):
        result, report = acquire(self.layer,self.bounds,get=self.get)
        self.assertEqual(report["accepted"],2)
        self.assertEqual(result[0]["id"],self.layer["id"]+"/1")
        self.assertEqual(result[0]["properties"]["context_only"],True)
        from shapely.geometry import shape
        self.assertEqual(shape(result[0]["geometry"]).bounds[0],-2)

    def test_incomplete_batch_fails(self):
        def broken(url,params,timeout):
            if params.get("f")=="geojson":
                return Response({"type":"FeatureCollection","features":[]})
            return self.get(url,params,timeout)
        with self.assertRaisesRegex(ValueError,"Incomplete"):
            acquire(self.layer,self.bounds,get=broken)

    def test_budget_fails(self):
        with self.assertRaisesRegex(ValueError,"budget"):
            acquire(self.layer,self.bounds,get=self.get,max_features=1)

    def test_collection_and_fusion(self):
        with tempfile.TemporaryDirectory() as temp:
            features, report = collect(self.bounds,{"sources":[self.layer["id"]]},Path(temp),get=self.get)
            self.assertEqual(report["feature_count"],2)
            self.assertEqual(json.loads((Path(temp)/"gis-report.json").read_text())["feature_count"],2)
        original = {"type":"FeatureCollection","features":[{"type":"Feature","id":"existing","properties":{"kind":"building"},"geometry":features[0]["geometry"]}]}
        result = fuse(original,features)
        self.assertEqual(result["building_review_candidates"],[features[1]["id"]])
        self.assertEqual(len(original["features"]),1)
        self.assertEqual(original["features"][0]["properties"]["gis_footprint_matches"][0]["iou"],1.0)
        result = fuse({"features":[]},features,promote_missing=True)
        self.assertEqual(result["draft_footprints_added"],2)

    def test_context_not_voxelized(self):
        f = feature(3,box(-2,52,-1,53))
        f["properties"]={"gis_role":"heritage_designation"}
        collection={"features":[]}
        self.assertEqual(fuse(collection,[f],promote_missing=True)["draft_footprints_added"],0)
        self.assertEqual(collection["features"],[])

    def test_cache_reuse_integrity_and_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            settings = {"sources":[self.layer["id"]], "cache_dir":str(root/"cache")}
            fs, first = collect(self.bounds, settings, root/"one", get=self.get)
            def offline(*args, **kwargs):
                raise AssertionError("cache should avoid network")
            cached, second = collect(self.bounds, settings, root/"two", get=offline)
            self.assertEqual(json.loads(json.dumps(fs)), cached)
            self.assertTrue(second["layers"][0]["cache_hit"])
            path = next((root/"cache").glob("*.json"))
            data = json.loads(path.read_text())
            data["payload"][0] = []
            path.write_text(json.dumps(data))
            restored, report = collect(self.bounds, settings, root/"three", get=self.get)
            self.assertEqual(restored, fs)
            self.assertFalse(report["layers"][0]["cache_hit"])
            settings["cache_max_age_seconds"] = 0
            _, report = collect(self.bounds, settings, root/"four", get=self.get)
            self.assertFalse(report["layers"][0]["cache_hit"])
            settings["workers"] = 9
            with self.assertRaisesRegex(ValueError,"workers"):
                collect(self.bounds, settings, root/"bad", get=self.get)

if __name__=="__main__":
    unittest.main()
