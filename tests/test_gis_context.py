import json
import tempfile
import unittest
from pathlib import Path
from shapely.geometry import box, mapping
from voxel_mapper.gis_context import review_geometry, import_polygons, write_context_grid

try:
    import numpy as np
    import rasterio
except ImportError:
    rasterio = None

BOUNDS=(-1.9,52.98,-1.899,52.981)
def f(id,g,**p):
    return {"type":"Feature","id":id,"geometry":mapping(g),"properties":p}

class GeometryReview(unittest.TestCase):
    def test_partial_water_gap_is_review_only(self):
        original=f("osm-water",box(-1.8998,52.9802,-1.8995,52.9806),kind="water")
        gis=f("os-water",box(-1.8998,52.9802,-1.8992,52.9806),gis_role="water_polygon",source_id="os",lineage_family="os")
        collection={"features":[original]}
        report,candidates=review_geometry(collection,[gis],BOUNDS)
        self.assertEqual(report["comparison_count"],1)
        self.assertAlmostEqual(report["comparisons"][0]["covered_fraction"],0.5,places=3)
        self.assertEqual(len(candidates["features"]),1)
        self.assertTrue(candidates["features"][0]["properties"]["review_only"])
        self.assertEqual(collection["features"],[original])

    def test_no_gap_if_same_and_context_not_geometry(self):
        g=box(-1.8998,52.9802,-1.8995,52.9806)
        original=f("b",g,kind="building")
        gis=f("os-b",g,gis_role="building_footprint",source_id="os")
        habitat=f("hab",g,gis_role="habitat_context",source_id="ne")
        report,candidates=review_geometry({"features":[original]},[gis,habitat],BOUNDS)
        self.assertEqual(report["comparison_count"],1)
        self.assertEqual(report["comparisons"][0]["matches"][0]["centroid_offset_m"],0)
        self.assertEqual(report["candidate_count"],0)

    def test_local_polygon_import(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"water.geojson").write_text(json.dumps({"type":"FeatureCollection","features":[f("w",box(-1.8998,52.9802,-1.8995,52.9806))]}))
            item={"id":"os-water","role":"water_polygon","path":"water.geojson","crs":"EPSG:4326","license":"OGL-3.0","url":"https://www.ordnancesurvey.co.uk/products/os-open-map-local","attribution":"OS","lineage_family":"ordnance-survey"}
            features,sources,reports=import_polygons([item],BOUNDS,root=root)
            self.assertEqual(len(features),1)
            self.assertEqual(reports[0]["status"],"available")
            self.assertTrue(features[0]["properties"]["context_only"])
            self.assertNotIn("path",sources[0])
            with self.assertRaisesRegex(ValueError,"license"):
                import_polygons([{**item,"license":"unknown"}],BOUNDS,root=root)

    @unittest.skipIf(rasterio is None,"install .[gis]")
    def test_partial_and_unavailable_grid(self):
        g=f("wood",box(-1.8998,52.9802,-1.8995,52.9806),gis_role="woodland_context",source_id="nfi")
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            result=write_context_grid(BOUNDS,[g],[{"source_id":"nfi","status":"partial"},{"source_id":"missing","status":"unavailable"}],root,
                landcover_report={"status":"unavailable","year":2025})
            with np.load(root/result["path"]) as grid:
                self.assertEqual(grid["channels"].shape[0],3)
                self.assertIn(1,np.unique(grid["channels"][0]))
                self.assertNotIn(0,np.unique(grid["channels"][0]))
                self.assertTrue(np.all(grid["channels"][1:]==255))

if __name__=="__main__":
    unittest.main()
