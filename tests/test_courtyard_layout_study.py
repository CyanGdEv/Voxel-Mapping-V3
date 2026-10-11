import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from shapely.geometry import box
from voxel_mapper.courtyard_layout_study import build,validate_source
from voxel_mapper.wing_shell_study import solid


class CourtyardLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=json.loads((Path(__file__).resolve().parents[1]/'evidence/mutiny-full-courtyard-layout-seed.json').read_text())
        cls.north={'components':[{'id':'floor','mesh':solid(box(0,0,32,6),2,-.25,0)}]}
        cls.seed['north_model_sha256']=hashlib.sha256((json.dumps(cls.north,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
        cls.cells={(10,0,2):'stone_bricks',(10,5,2):'dark_oak_stairs_north',(4,0,1):'stone_bricks'}
        cls.model,cls.output,cls.audit=build(cls.north,cls.cells,cls.seed)

    def test_four_ranges_annexes_and_rooms_without_changing_north(self):
        self.assertEqual(self.audit['rooms_in_layout'],28)
        self.assertEqual(len(self.model['footprints']),6)
        self.assertTrue(all(self.output[p]==m for p,m in self.cells.items()))
        self.assertGreater(len(self.output),4000)
        self.assertTrue(self.audit['all_component_solids_watertight'])
        self.assertFalse(self.model['surveyed_complete_structure'])
        self.assertFalse(self.model['world_placement_eligible'])

    def test_courtyard_open_and_through_passages_standing_clear(self):
        self.assertFalse(any((16,y,-16) in self.output for y in range(12)))
        passages=[r for r in self.audit['passages_and_doors'] if r['kind']=='passage']
        self.assertEqual(len(passages),4)
        self.assertTrue(all(r['standing_air_verified'] for r in passages))
        self.assertFalse(any('glass' in v for v in self.output.values()))

    def test_unpinned_north_or_unacknowledged_hypothesis_rejects(self):
        for key,value in [('north_model_sha256','0'*64),('hypotheses_acknowledged',False)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):build(self.north,self.cells,s)

    def test_bad_dimensions_and_scale_reject(self):
        for key,value in [('wall_height_m',float('nan')),('wall_thickness_m',3),('source_scale_denominator',50),('origin_pixel',[0,0]),('window_sill_m',2.2)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):build(self.north,self.cells,s)

    def test_budget_and_nonfinite_traces_reject(self):
        s=copy.deepcopy(self.seed);s['external_walls']*=28
        with self.assertRaisesRegex(ValueError,'budget'):build(self.north,self.cells,s)
        s=copy.deepcopy(self.seed);s['footprints'][0]['pixel_ring'][0][0]=float('inf')
        with self.assertRaisesRegex(ValueError,'in-page'):build(self.north,self.cells,s)

    def test_courtyard_encroachment_rejects(self):
        s=copy.deepcopy(self.seed);s['footprints'][0]['pixel_ring']=[[222,305],[1059,305],[1059,991],[222,991]]
        with self.assertRaisesRegex(ValueError,'protected courtyard'):build(self.north,self.cells,s)

    def test_changed_source_checksum_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'changed.pdf';p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):validate_source(self.seed,p)

    def test_roof_stairs_face_ridges_in_both_plan_axes(self):
        new=[m for p,m in self.output.items() if p not in self.cells and m.startswith('dark_oak')]
        self.assertGreater(len(new),500)
        self.assertEqual(set(new),{'dark_oak_stairs_'+d for d in ('north','south','east','west')})
        for c in self.model['components']:
            if c['id'].startswith('plan_outer_wall_north_'):
                self.assertLessEqual(max(v[2] for v in c['mesh']['vertices']),2.8)


if __name__=='__main__':unittest.main()
