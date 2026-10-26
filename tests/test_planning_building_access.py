"""Access matching preserves physical ambiguity and page coordinate conventions."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import box,mapping
from voxel_mapper import planning_building_access as access


class BuildingAccessTests(unittest.TestCase):
    def test_fixed_scale_held_out_buildings_resolve_half_turn(self):
        roofs={'shop_main_roof':box(0,0,12,17),'station_main_roof':box(20,0,38,9),'maintenance_main_roof':box(20,15,43,28)}
        transform=[0,-1,1,0,100,200]
        targets={label:affine_transform(roofs[role],transform) for role,label in [('shop_main_roof','Shop'),('station_main_roof','Station'),('maintenance_main_roof','Maintenance')]}
        fit,other=access.select_fit(roofs,targets)
        self.assertEqual(len(other),2)
        self.assertLess(max(fit['held_out_building_centroid_distances_m'].values()),1e-10)
        a,b,c,d,_,_=fit['affine'];self.assertAlmostEqual(a*d-b*c,1)
        self.assertAlmostEqual(a*a+c*c,1)
        targets['Station']=box(400,400,418,409)
        with self.assertRaises(ValueError):access.select_fit(roofs,targets)

    def test_rotated_page_pixel_trace_and_furniture_round_trip(self):
        import pymupdf
        from voxel_mapper.drawing_page_tools import pixel_to_native
        doc=pymupdf.open();page=doc.new_page(width=400,height=600);page.set_rotation(90)
        pix=page.get_pixmap();points=[[20,30],[70,90]]
        furniture=np.array([[.9,0],[0,.9],[10,12]])
        xy=access.source_points(page,pix,points,furniture)
        inverse=~pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
        native=xy/access.UNIT@furniture[:2]+furniture[2]
        actual=[list(pymupdf.Point(*p)*inverse) for p in native]
        np.testing.assert_allclose(actual,points,atol=1e-5)
        with self.assertRaises(ValueError):access.source_points(page,pix,[[float('nan'),0],[1,1]])
        with self.assertRaises(ValueError):access.source_points(page,pix,[[0,0],[pix.width,1]])
        doc.close()

    def test_proximity_does_not_promote_a_doorway_and_filters_building(self):
        features=[{'id':'other','building':'Shop','role':'door_opening','geometry_nominal_local':mapping(box(0,0,1,1))},
                  {'id':'near','building':'Station','role':'stair_flight','geometry_nominal_local':mapping(box(1,0,2,1))}]
        steps=[{'source_cells_xy':[[0,0],[1,0]],'step_blocks':2}]
        floors={(1,0):{'labels':['Station']}}
        r=access.hotspot_links(steps,features,floors)[0]
        self.assertEqual([x['feature_id'] for x in r['source_access_distances']],['near'])
        self.assertEqual(r['source_access_distances'][0]['distance_m'],0)
        self.assertFalse(r['doorway_identified']);self.assertFalse(r['geometry_changed'])
        with self.assertRaises(ValueError):access.hotspot_links(steps,features,{})

    def test_degenerate_correspondences_are_rejected(self):
        with self.assertRaises(ValueError):access.rigid_candidates(box(0,0,0,1),box(1,1,2,3))

    def test_cancelled_review_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'review'
            with self.assertRaises(CancelledError):access.run({},'missing','missing','missing',output,cancelled=lambda:True)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
