import copy,json,tempfile,unittest
from pathlib import Path
from shapely.geometry import Polygon,box
from voxel_mapper.wing_shell_study import solid
from voxel_mapper.courtyard_facade_study import apply,validate_source


class CourtyardFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=json.loads((Path(__file__).resolve().parents[1]/'evidence/mutiny-west-facade-access-seed.json').read_text())
        cls.model={'components':[
            {'id':'left_junction_cap','mesh':solid(Polygon([(0,0),(6,0),(6,4),(3,7),(0,4)]),0,0,.5)},
            {'id':'plan_outer_wall_main_slice_0','mesh':solid(box(-.2,-30.1,.2,0),2,0,4)}],
            'assumptions':[]}
        cls.cells={(x,y,z):'stone_bricks' for x in (-1,0) for y in range(4) for z in range(-31,0)}
        cls.cells.update({(0,0,1):'stone_bricks',(0,1,1):'stone_bricks',(10,0,2):'stone_bricks',(10,6,2):'dark_oak_stairs_north'})
        cls.result,cls.output,cls.audit=apply(cls.model,cls.cells,cls.seed)

    def test_only_provisional_lobby_cap_cut_and_unrelated_cells_retained(self):
        self.assertNotIn((0,0,1),self.output);self.assertNotIn((0,1,1),self.output)
        self.assertEqual(self.output[10,0,2],'stone_bricks');self.assertEqual(self.output[10,6,2],'dark_oak_stairs_north')
        self.assertTrue(self.audit['lobby_standing_air_verified'])
        cap=next(c for c in self.result['components'] if c['id']=='left_junction_cap')
        self.assertTrue(cap['mesh']['watertight'])
        self.assertLess(cap['mesh']['volume_m3'],self.model['components'][0]['mesh']['volume_m3'])

    def test_existing_view_scale_and_withheld_dormers(self):
        self.assertEqual(self.audit['west_source_openings'],14)
        self.assertEqual(self.audit['west_dormers_withheld'],2)
        self.assertEqual(self.result['facade_study']['view_scale_denominator'],50)
        self.assertEqual(self.result['facade_study']['sheet_title_scale_denominator'],100)
        self.assertFalse(self.audit['source_registered_to_park'])
        self.assertFalse(any('glass' in m for m in self.output.values()))
        self.assertTrue(all(r['standing_front_air_verified'] for r in self.audit['west_front_passages']))

    def test_changed_scale_anchor_or_acknowledgement_rejects(self):
        for key,value in [('view_scale_denominator',100),('right_anchor_pixel_x',1600),('review_hypotheses_acknowledged',False)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):apply(self.model,self.cells,s)

    def test_lobby_cannot_cut_non_masonry_or_move_its_trace(self):
        cells=dict(self.cells);cells[0,0,1]='dark_oak_planks'
        with self.assertRaisesRegex(ValueError,'temporary masonry'):apply(self.model,cells,self.seed)
        s=copy.deepcopy(self.seed);s['lobby_access']['native_cells_to_clear'][0][0]=1
        with self.assertRaisesRegex(ValueError,'access review'):apply(self.model,self.cells,s)

    def test_nonfinite_or_outside_view_trace_rejects(self):
        for value in (float('nan'),1800):
            s=copy.deepcopy(self.seed);s['openings'][0]['pixel_ring'][0][0]=value
            with self.assertRaisesRegex(ValueError,'bounded'):apply(self.model,self.cells,s)

    def test_changed_elevation_pdf_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.pdf';p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):validate_source(self.seed,p)


if __name__=='__main__':unittest.main()
