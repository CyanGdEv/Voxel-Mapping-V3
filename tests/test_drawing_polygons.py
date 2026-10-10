import unittest
from shapely.geometry import shape
from voxel_mapper.drawing_polygons import polygon_candidates


class PolygonTests(unittest.TestCase):
    def test_evenodd_holes_and_separate_paints(self):
        paths=[]
        for group,coords in [(0,[(0,0),(10,0),(10,10),(0,10),(0,0)]),(0,[(2,2),(8,2),(8,8),(2,8),(2,2)]),(1,[(20,0),(21,0),(21,1),(20,1),(20,0)])]:
            paths.append(dict(paint_group=group,paint_operator='f*',closed=True,geometry={'coordinates':coords}))
        vectors={'status':'unverified_candidates','layers':[dict(viewport=0,metric_crs='test',paths=paths)]}
        result=polygon_candidates(vectors)
        polygons=result['layers'][0]['polygons']
        self.assertEqual(shape(polygons[0]['geometry']).area,64)
        self.assertEqual(len(shape(polygons[0]['geometry']).interiors),1)
        self.assertEqual(len(polygons),2)
        self.assertEqual(polygon_candidates(vectors,max_rings=1)['layers'],[])
        self.assertEqual(polygon_candidates({'status':'blocked_reuse'})['status'],'unavailable')
