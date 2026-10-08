import unittest
from shapely.geometry import LineString
from voxel_mapper.park_completion import line_cells
from voxel_mapper.bedrock import material_block,DETAIL_MATERIALS
class CompletionTests(unittest.TestCase):
    def test_diagonal_route_includes_endpoints_and_only_nearby_cells(self):
        cells=line_cells(LineString([(0,0),(10,10)]))
        self.assertIn((0,0),cells);self.assertIn((10,10),cells)
        self.assertTrue(all(abs(x-z)<=1 for x,z in cells));self.assertLessEqual(len(cells),30)
        reached={(0,0)}
        while True:
            nxt=reached|{p for p in cells if any((p[0]+dx,p[1]+dz) in reached for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))}
            if nxt==reached:break
            reached=nxt
        self.assertEqual(reached,set(cells))
    def test_transport_geometry_budget(self):
        with self.assertRaises(ValueError):line_cells(LineString([(0,0),(10001,0)]))
    def test_partial_blocks_have_native_bedrock_identifiers(self):
        import PyMCTranslate
        translator=PyMCTranslate.new_translation_manager().get_version('bedrock',(1,21,130)).block
        for material in sorted(DETAIL_MATERIALS):
            with self.subTest(material=material):
                native=translator.from_universal(material_block(material))[0]
                self.assertEqual(native.namespace,'minecraft')
    def test_spruce_planks_keep_material(self):
        self.assertEqual(material_block('spruce_planks').properties['material'].py_data,'spruce')
if __name__=='__main__':unittest.main()
