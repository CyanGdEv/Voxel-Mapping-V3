import copy,json,tempfile,unittest,math
from pathlib import Path
from shapely.geometry import Polygon,box
from voxel_mapper.courtyard_south_study import apply,validate_source
from voxel_mapper.wing_shell_study import solid
from voxel_mapper.slab_roof_study import convert
from voxel_mapper.wing_block_shapes import occupied_halves


class CourtyardSouthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=json.loads((Path(__file__).resolve().parents[1]/'evidence/mutiny-south-assembly-seed.json').read_text())
        pu=2384/1800*100*.0254/72;cls.length=686*pu;cls.front=-644*pu;cls.rear=-837*pu
        rp=Polygon([(cls.rear,4),((cls.rear+cls.front)/2,7),(cls.front,4),(cls.front,3.75),((cls.rear+cls.front)/2,6.75),(cls.rear,3.75)])
        cls.model={'components':[{'id':'roof_south_range','mesh':solid(rp,0,0,cls.length)},
                                 {'id':'plan_outer_wall_main_slice_0','mesh':solid(box(0,cls.front-.2,cls.length,cls.front+.2),2,0,4)}],
                   'assumptions':[]}
        cls.cells={(x,-1,z):'stone_bricks' for x in range(33) for z in range(-40,-29)}
        cls.cells.update({(x,y,z):'stone_bricks' for x in range(33) for y in range(4) for z in (-31,-30)})
        cls.cells.update({(x,y,z):'stone_bricks' for x in range(33) if x not in (14,15,16,17) for y in range(4) for z in (-40,-39)})
        cls.cells.update({(x,4,z):'dark_oak_stairs_north' for x in range(32) for z in range(-39,-29)})
        cls.cells[10,0,2]='stone_bricks'
        cls.result,cls.native,cls.audit=apply(cls.model,cls.cells,cls.seed)
        cls.slab_model,cls.slab_cells,cls.slab_audit=convert(cls.result,cls.native)

    def test_sections_canopy_towers_and_source_inventory(self):
        self.assertEqual(self.audit['south_openings'],18)
        self.assertEqual(self.audit['south_roof_sections'],3)
        self.assertEqual(self.audit['small_arch_towers'],2)
        self.assertTrue(self.audit['canopy_built'])
        self.assertFalse(self.audit['depths_measured'])
        self.assertFalse(self.audit['corner_towers_reconstructed'])
        self.assertEqual(self.audit['curtain_slits_native_withheld'],3)
        self.assertTrue(all(c['mesh']['watertight'] for c in self.result['components']))
        self.assertEqual(self.native[10,0,2],'stone_bricks')

    def test_slab_arch_clearance_and_no_roof_template_leaks(self):
        occ=occupied_halves(self.slab_cells)
        for x in self.audit['source_arch_native_columns']:
            for z in range(math.floor(self.rear),math.floor(self.front)+2):
                self.assertTrue(all((2*x+dx,h,2*z+dz) not in occ for dx in (0,1) for h in range(4) for dz in (0,1)))
        self.assertFalse(any('glass' in v or v.startswith('dark_oak_stairs') for v in self.slab_cells.values()))
        self.assertLess(max(y for x,y,z in self.slab_cells),12)

    def test_numerical_dimensions_or_view_direction_cannot_be_silently_changed(self):
        for key,value in [('view_scale_denominator',100),('left_anchor_pixel_x',170),('tower_depth_m',float('nan')),('curtain_setback_m',10),('depths_measured',True),('hypotheses_acknowledged',False)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):apply(self.model,self.cells,s)

    def test_source_coverage_gap_or_bad_trace_rejects(self):
        s=copy.deepcopy(self.seed);s['front_sections'][0]['pixel_x'][1]=700
        with self.assertRaisesRegex(ValueError,'cover|gap'):apply(self.model,self.cells,s)
        s=copy.deepcopy(self.seed);s['openings'][0]['pixel_ring'][0][0]=float('inf')
        with self.assertRaisesRegex(ValueError,'trace'):apply(self.model,self.cells,s)

    def test_changed_source_pdf_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.pdf';p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):validate_source(self.seed,p)


if __name__=='__main__':unittest.main()
