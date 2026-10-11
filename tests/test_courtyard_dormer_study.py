import copy,json,unittest
from pathlib import Path
from shapely.geometry import Polygon,box
from voxel_mapper.wing_shell_study import solid
from voxel_mapper.courtyard_dormer_study import apply
from voxel_mapper.slab_roof_study import convert
from voxel_mapper.wing_block_shapes import occupied_halves


class CourtyardDormerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=json.loads((Path(__file__).resolve().parents[1]/'evidence/mutiny-west-dormer-seed.json').read_text())
        profile=Polygon([(-6,4),(-3,7),(0,4),(0,3.75),(-3,6.75),(-6,3.75)])
        cls.model={'components':[{'id':'roof_west_range','mesh':solid(profile,1,-38,6)},
                                 {'id':'west_courtyard_elevation_wall','mesh':solid(box(-30,0,0,4),0,-.2,.2)}],
                   'facade_study':{'source_pdf_sha256':cls.seed['source_pdf_sha256'],'wall_height_from_view_m':4,'withheld':[]},'assumptions':[]}
        cls.cells={(x,4,z):'dark_oak_stairs_north' for x in range(-6,0) for z in range(-38,6)}
        cls.cells.update({(x,y,z):'stone_bricks' for x in (-1,0) for y in range(4) for z in range(-30,0)})
        cls.cells[20,0,2]='stone_bricks'
        cls.result,cls.native,cls.audit=apply(cls.model,cls.cells,cls.seed)
        cls.slab_model,cls.slab_cells,cls.slab_audit=convert(cls.result,cls.native)

    def test_two_source_fronts_depth_remains_hypothesis_and_other_cells_retained(self):
        self.assertEqual(self.audit['dormers_built'],2)
        self.assertFalse(self.audit['depth_measured'])
        self.assertEqual(self.native[20,0,2],'stone_bricks')
        self.assertEqual(self.result['facade_study']['withheld'],[])
        self.assertTrue(all(c['mesh']['watertight'] for c in self.result['components']))
        self.assertTrue(any(c['id'].startswith('roof_west_segment_') for c in self.result['components']))

    def test_slab_courses_leave_dormer_windows_open(self):
        occ=occupied_halves(self.slab_cells)
        for x,z,h in self.result['roof_window_void_halves']:
            for dx in (0,1):
                for dz in (0,1):self.assertNotIn((2*x+dx,h,2*z+dz),occ)
        self.assertGreater(self.slab_audit['roof_window_air_halves_verified'],0)
        self.assertFalse(any('glass' in v or v.startswith('dark_oak_stairs') for v in self.slab_cells.values()))

    def test_depth_or_source_cannot_be_silently_changed(self):
        for key,value in [('depth_display_m',float('nan')),('depth_display_m',.1),('source_pdf_sha256','bad'),('depth_measured',True),('review_hypotheses_acknowledged',False)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):apply(self.model,self.cells,s)

    def test_bad_front_trace_rejected(self):
        s=copy.deepcopy(self.seed);s['dormers'][0]['window_pixels'][0]=float('inf')
        with self.assertRaisesRegex(ValueError,'silhouette'):apply(self.model,self.cells,s)

    def test_clearance_budget_and_outside_roof_constraints_rejected(self):
        m=copy.deepcopy(self.result);m['roof_window_void_halves']=[[0,-12,8]]*129
        with self.assertRaisesRegex(ValueError,'budget'):convert(m,self.native)
        m=copy.deepcopy(self.result);m['roof_minimum_cap_bottoms']=[{'column':[999,999],'minimum_cap_bottom_m':4.5}]
        with self.assertRaisesRegex(ValueError,'outside native'):convert(m,self.native)


if __name__=='__main__':unittest.main()
