import copy
import json
import tempfile
import unittest
from pathlib import Path
from voxel_mapper.building_native import compile_spec,export_preview
from voxel_mapper.building_spec import from_study,build
from voxel_mapper.wing_block_shapes import occupied_halves
from tests.test_building_data_pipeline import spec


def hall():
    s=spec();s['components'].extend([
      {'id':'floor','role':'floor','evidence':copy.deepcopy(s['components'][0]['evidence']),
       'geometry':{'kind':'extrusion','axis':2,'interval_m':[-.25,0],'profile':[[0,0],[8,0],[8,6],[0,6]]}},
      {'id':'roof','role':'roof','evidence':copy.deepcopy(s['components'][0]['evidence']),
       'geometry':{'kind':'extrusion','axis':0,'interval_m':[0,8],
                   'profile':[[0,4],[3,6],[6,4],[6,3.75],[3,5.75],[0,3.75]]}}])
    return s


class BuildingNativeTests(unittest.TestCase):
    def test_roof_slabs_floor_level_and_window_air(self):
        cells,audit=compile_spec(hall());occ=occupied_halves(cells)
        self.assertFalse(any('glass' in m or m.startswith('dark_oak_stairs') for m in cells.values()))
        self.assertTrue(any(m.startswith('dark_oak_slab') for m in cells.values()))
        self.assertTrue(all((x,h,z) not in occ for x in (2,3) for h in (2,3) for z in (0,1)))
        self.assertNotIn((4,0,3),cells) # Floor top stays at source zero, below standing air.
        self.assertIn((4,-1,3),cells)
        self.assertLessEqual(audit['max_roof_top_rounding_error_m'],.250000001)

    def test_declared_passage_cannot_be_closed_by_any_shape(self):
        s=hall();s['native_air_halves']=[[x,h,z] for x in (8,9) for h in range(4) for z in (0,1)]
        cells,audit=compile_spec(s)
        self.assertFalse(set(map(tuple,s['native_air_halves']))&set(occupied_halves(cells)))
        self.assertTrue(audit['protected_air_verified'])

    def test_sampling_is_independent_of_triangle_order(self):
        original=hall();m=build(original)
        retained=from_study(m,'building-a','a'*64)
        first,one=compile_spec(retained)
        for c in retained['components']:c['geometry']['mesh']['triangles'].reverse()
        second,two=compile_spec(retained)
        self.assertEqual(first,second)
        self.assertEqual(one['source_surface_halves_missing'],two['source_surface_halves_missing'])

    def test_rotated_planar_surface_does_not_fill_entire_bounding_box(self):
        s=spec();s['components'][0]['geometry']={'kind':'mesh','mesh':{
            'vertices':[[0,0,0],[5,5,0],[5,5,3],[0,0,3]],'triangles':[[0,1,2],[0,2,3]]}}
        cells,audit=compile_spec(s)
        self.assertTrue(cells)
        self.assertTrue(all(abs(x-z)<=1 for x,y,z in cells))

    def test_limits_refuse_partial_output(self):
        with self.assertRaisesRegex(ValueError,'budget'):compile_spec(hall(),max_checks=1)
        s=hall();s['native_air_halves']=[[0,float('nan'),0]]
        with self.assertRaises(ValueError):compile_spec(s)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'native'
            with self.assertRaises(ValueError):export_preview(hall(),p,max_checks=1)
            self.assertFalse(p.exists())

    def test_native_rows_export_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'native';report=export_preview(hall(),p)
            rows=[json.loads(l) for l in (p/'voxels.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),report['native_audit']['surface_cells'])
            self.assertEqual(report['park_world_blocks_added'],0)
            with self.assertRaisesRegex(ValueError,'Fresh'):export_preview(hall(),p)

    def test_import_retains_window_and_passage_guards(self):
        parent=build(hall());parent['roof_window_void_halves']=[[1,2,8]]
        parent['slab_conversion_passages']=[{'native_columns':[[2,3]]}]
        common=from_study(parent,'hall','a'*64)
        self.assertIn([2,8,4],common['native_air_halves'])
        self.assertIn([4,0,6],common['native_air_halves'])

    def test_native_world_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=export_preview(hall(),Path(tmp)/'native',world=True)
            self.assertTrue((Path(tmp)/'native/park.mcworld').is_file())
            self.assertIn('world',report)


class NativeIntegrationTests(unittest.TestCase):
    def test_multiple_roof_levels_are_retained(self):
        s=hall();roof=copy.deepcopy(s['components'][-1]);roof['id']='upper-roof'
        roof['geometry']['profile']=[[x,z+4] for x,z in roof['geometry']['profile']]
        s['components'].append(roof)
        cells,audit=compile_spec(s)
        levels=[y for (x,y,z),m in cells.items() if (x,z)==(4,1) and m.startswith('dark_oak')]
        self.assertTrue(any(y<6 for y in levels));self.assertTrue(any(y>=8 for y in levels))

    def test_batch_runs_shared_native_compiler_when_data_requests_it(self):
        from voxel_mapper.building_pipeline import run
        from tests.test_building_data_pipeline import candidate
        with tempfile.TemporaryDirectory() as tmp:
            c=candidate();c['spec']=hall()
            job={'version':'building-batch-v1','native_output':'cells',
                 'buildings':[{'building_id':'building-a','candidates':[c]}]}
            root=Path(tmp)/'batch';report=run(job,root)
            self.assertEqual(report['built'],1)
            self.assertTrue(report['buildings'][0]['native_output']['protected_air_verified'])
            self.assertTrue((root/'building-0000/native/voxels.jsonl').is_file())
