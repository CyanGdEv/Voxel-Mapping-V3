import copy
import unittest
from voxel_mapper.building_roof_repair import repair
from voxel_mapper.building_structure import inspect
from voxel_mapper.building_spec import from_study
from voxel_mapper.building_native import compile_spec
from tests.test_building_native import hall


class RoofRepairTests(unittest.TestCase):
    def fixture(self):
        return {(0,-1,0):'stone_bricks',(0,0,0):'stone_bricks',
                (0,1,0):'dark_oak_slab',(1,2,0):'dark_oak_slab'}

    def test_bounded_wood_join_keeps_masonry_and_connects_roof(self):
        cells=self.fixture();result,records=repair(cells,{(0,-1,0)},set(),{(0,0),(1,0)})
        self.assertEqual(len(records),1);self.assertEqual(inspect(result,{(0,-1,0)})['unsupported_roof_regions'],0)
        self.assertEqual(result[0,0,0],cells[0,0,0]);self.assertEqual(cells,self.fixture())
        self.assertFalse(any('stairs' in m for m in result.values()))

    def test_air_guards_remote_gaps_and_unknown_floor_are_not_filled(self):
        cells=self.fixture()
        for anchors,guards,columns in [({(0,-1,0)},{(2,2,0)},{(0,0),(1,0)}),
                                      (set(),set(),{(0,0),(1,0)}),
                                      ({(0,-1,0)},set(),{(0,0)})]:
            result,records=repair(cells,anchors,guards,columns)
            self.assertEqual(result,cells);self.assertEqual(records,[])
        cells[1,4,0]=cells.pop((1,2,0))
        self.assertEqual(repair(cells,{(0,-1,0)},set(),{(0,0),(1,0)})[0],cells)

    def test_display_floor_requires_explicit_level_outline_and_is_unverified(self):
        parent={'wall_mesh':{'vertices':[[0,0,0],[3,0,0],[3,0,3]],'triangles':[[0,1,2]]},
                'outer_wall_base_outline':[[0,0,0],[3,0,0],[3,3,0],[0,3,0]]}
        ordinary=from_study(parent,'test','a'*64)
        self.assertNotIn('floor_reference',ordinary)
        common=from_study(parent,'test','a'*64,display_floor=True)
        self.assertFalse(common['floor_reference']['surveyed_datum_verified'])
        self.assertEqual(common['components'][-1]['role'],'floor')
        self.assertEqual(common['components'][-1]['geometry']['interval_m'],[-1,0])
        parent['outer_wall_base_outline'][0][2]=1
        with self.assertRaisesRegex(ValueError,'Level'):from_study(parent,'test','a'*64,display_floor=True)

    def test_unsupported_remote_upper_roof_remains_rejected(self):
        s=hall();roof=copy.deepcopy(s['components'][-1]);roof['id']='remote'
        roof['geometry']['profile']=[[x,z+5] for x,z in roof['geometry']['profile']];s['components'].append(roof)
        cells,audit=compile_spec(s)
        self.assertGreater(audit['structural_review']['unsupported_roof_regions'],0)


class FloorThicknessTests(unittest.TestCase):
    def test_one_metre_closed_floor_does_not_grow_an_extra_bottom_layer(self):
        s=hall();s['components'][1]['geometry']['interval_m']=[-1,0]
        cells,audit=compile_spec(s)
        self.assertEqual(cells[4,-1,3],'stone_bricks')
        self.assertNotIn((4,-2,3),cells)
        self.assertNotIn((4,0,3),cells)
