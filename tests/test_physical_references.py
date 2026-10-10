import unittest
from shapely.geometry import box,mapping
from pyproj import Transformer
from shapely.ops import transform
from voxel_mapper.physical_references import select


class PhysicalReferenceTests(unittest.TestCase):
    def feature(self,id,kind,geometry,name=None):
        return {'type':'Feature','id':id,'properties':{'kind':kind,**({'name':name} if name else {})},'geometry':mapping(geometry)}

    def test_unnamed_physical_outlines_retained_but_paths_extents_and_outside_excluded(self):
        domain=transform(Transformer.from_crs(4326,27700,always_xy=True).transform,box(-1.9,52.98,-1.88,53))
        inside=box(-1.895,52.985,-1.89,52.99);outside=box(-2,52.9,-1.99,52.91)
        feed={'type':'FeatureCollection','features':[self.feature('unnamed','building',inside),self.feature('lake','water',inside,'Lake'),self.feature('path','path',inside),self.feature('ride','attraction',inside),self.feature('outside','building',outside)]}
        selected,counts=select(feed,domain,27700)
        self.assertEqual([f['id'] for f in selected['features']],['lake','unnamed']);self.assertEqual(counts['unnamed'],1);self.assertEqual(counts['outside_or_crossing_park_domain'],1)

    def test_domain_crossing_not_clipped_into_a_new_outline(self):
        domain=transform(Transformer.from_crs(4326,27700,always_xy=True).transform,box(-1.9,52.98,-1.88,53))
        feed={'type':'FeatureCollection','features':[self.feature('cross','building',box(-1.91,52.985,-1.89,52.99))]}
        self.assertFalse(select(feed,domain,27700)[0]['features'])

    def test_angular_domain_and_duplicate_ids_refused(self):
        feed={'type':'FeatureCollection','features':[self.feature('same','building',box(-1.895,52.985,-1.89,52.99))]*2}
        with self.assertRaisesRegex(ValueError,'Projected metre'):select(feed,box(-2,52,-1,54),4326)
        with self.assertRaisesRegex(ValueError,'Unique'):select(feed,box(0,0,1000000,1000000),27700)

if __name__=='__main__':unittest.main()
