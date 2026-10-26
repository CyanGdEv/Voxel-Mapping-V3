import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import Point,box,mapping
from shapely.affinity import affine_transform

from voxel_mapper import planning_geometry_world as world,planning_hatch_regions,planning_gap_boundaries
from tests.test_planning_area_world_preview import source_layout


def inputs(width=3):
    layout=copy.deepcopy(source_layout());scale=layout['shared_frame']['metres_per_pdf_point']
    g=box(5,5,25,25).difference(box(5+width,5+width,25-width,25-width))
    native=affine_transform(g,[1/scale,0,0,1/scale,0,0])
    paving={'version':planning_hatch_regions.VERSION,'document_sha256':layout['document_sha256'],'page':layout['page'],
        'coordinate_frame':'pdf_native_points_y_up','analysis_complete':True,
        'summary':{'legend_associated_paving_regions':1},'records':[{
            'id':'ring','geometry':mapping(native),'paint_kind':'solid','legend_claim':{'printed_state':'new'}}]}
    gaps=planning_gap_boundaries.review(paving,layout)
    assert gaps['analysis_complete'],gaps.get('reason')
    return {'layout':layout,'paving':paving,'gaps':gaps}


def request(root,data):
    config={'version':world.VERSION}
    for key,value in data.items():
        p=root/(key+'.json');p.write_text(json.dumps(value));config[key+'_path']=str(p);config[key+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    return config


class GeometryWorldTests(unittest.TestCase):
    def test_width_less_than_four_uses_oak_fence(self):
        r=world.rasterize(inputs(3))
        self.assertTrue(r['rocks'])
        self.assertTrue(all(col==[(1,'oak_fence')] for col in r['rocks'].values()))
        self.assertTrue(all(w<4 for w in r['widths'].values()))
        self.assertFalse(set(r['rocks'])&r['paving'])

    def test_exactly_four_and_wider_use_rock_preset(self):
        for width in (4,5):
            with self.subTest(width=width):
                r=world.rasterize(inputs(width))
                self.assertTrue(r['rocks']);self.assertTrue(all(col!=[(1,'oak_fence')] for col in r['rocks'].values()))
                self.assertTrue(all(w>=4 for w in r['widths'].values()))

    def test_width_stops_at_first_paving_exit_not_another_path(self):
        paving=box(0,0,3,20).union(box(10,0,30,20))
        self.assertAlmostEqual(world.local_path_width(paving,Point(-.5,10),Point(0,10)),3)
        self.assertAlmostEqual(world.local_path_width(box(0,0,4,20),Point(-.5,10),Point(0,10)),4)

    def test_corner_width_uses_source_edge_normal(self):
        gap=box(3,3,17,17);paving=box(0,0,20,20).difference(gap)
        self.assertEqual(world.local_path_width(paving,Point(3,3),Point(3,3),gap),3)

    def test_reference_profile_is_deterministic_and_has_partial_blocks(self):
        columns=[world.rock_column(x,z,'north') for x in range(20) for z in range(20)]
        materials={m for c in columns for _,m in c}
        self.assertIn('cobblestone',materials);self.assertIn('stone_bricks',materials)
        self.assertTrue(any('stairs' in m for m in materials));self.assertIn('stone_slab',materials)
        self.assertTrue(any(y==2 for c in columns for y,_ in c))
        self.assertEqual(world.rock_column(14,19,'east'),world.rock_column(14,19,'east'))
        self.assertTrue(all(1<=y<=2 for c in columns for y,_ in c))

    def test_opening_override_does_not_get_a_rock_or_fence(self):
        data=inputs();identifier=data['gaps']['records'][0]['id']
        data['gaps']=planning_gap_boundaries.review(data['paving'],data['layout'],overrides={identifier:{'kind':'opening','evidence':'User opening'}})
        self.assertFalse(world.rasterize(data)['rocks'])

    def test_sampling_and_complete_area_limits_fail_without_cropping(self):
        for limits in ({'max_platform_cells':1},{'max_sampling_checks':1},{'max_points':1},{'max_boundary_cells':1},{'max_width_checks':1}):
            with self.subTest(limits=limits),self.assertRaises(ValueError):world.rasterize(inputs(),limits=limits)
        with self.assertRaises(CancelledError):world.rasterize(inputs(),cancelled=lambda:True)

    def test_diagonal_narrow_fences_gain_grass_side_connections(self):
        from shapely.affinity import rotate
        from voxel_mapper.planning_area_world_preview import _grid_connectivity
        data=inputs(3);scale=data['layout']['shared_frame']['metres_per_pdf_point']
        g=rotate(box(5,5,25,25).difference(box(8,8,22,22)),45,origin=(15,15))
        data['paving']['records'][0]['geometry']=mapping(affine_transform(g,[1/scale,0,0,1/scale,0,0]))
        data['gaps']=planning_gap_boundaries.review(data['paving'],data['layout'])
        result=world.rasterize(data)
        fences={key for key,column in result['rocks'].items() if column==[(1,'oak_fence')]}
        self.assertGreater(result['fence_grid_connectors'],0)
        self.assertFalse(fences&result['paving'])
        self.assertEqual(_grid_connectivity(fences,{})['component_count'],1)

    def test_pinned_inputs_and_current_gap_geometry_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=request(root,inputs());world.read_inputs(config)
            data=json.loads(Path(config['gaps_path']).read_text());data['records'][0]['material']='diamond'
            Path(config['gaps_path']).write_text(json.dumps(data))
            with self.assertRaises(ValueError):world.read_inputs(config)
            config['gaps_sha256']=hashlib.sha256(Path(config['gaps_path']).read_bytes()).hexdigest()
            with self.assertRaises(ValueError):world.read_inputs(config)

    def test_native_world_preserves_fence_and_slab_stair_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=request(root,inputs(3))
            from voxel_mapper.planning_area_world_preview import run
            result=run(config,root/'world')
            self.assertGreater(result['fence_columns'],0);self.assertEqual(result['rock_columns'],0)
            self.assertTrue(result['saved_geometry_validation']['native_block_states_verified'])
            self.assertTrue(result['archive_validation']['saved_world_reopened'])
            self.assertTrue(result['spawn_validation']['verified'])
            self.assertFalse(result['world_placement_eligible'])
            self.assertTrue((root/'world'/result['file']).is_file())
            self.assertEqual(result['rock_paving_cell_overlap'],0)
            for name in ('layout','paving','gaps'):
                self.assertEqual(hashlib.sha256((root/'world'/('source-'+name+'.json')).read_bytes()).hexdigest(),config[name+'_sha256'])
            config=request(root,inputs(5));result=run(config,root/'rocks')
            self.assertGreater(result['rock_columns'],0);self.assertEqual(result['fence_columns'],0)
            self.assertTrue(result['saved_geometry_validation']['native_block_states_verified'])
            self.assertEqual(result['saved_geometry_validation']['saved_rock_blocks_verified'],result['rock_blocks'])

    def test_managed_export_selects_current_geometry_and_survives_restart(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime,write_json,_wait
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();data=inputs();layout=data['layout']
            name='area-layout-fixture.json';write_json(source/name,layout);pin=hashlib.sha256((source/name).read_bytes()).hexdigest()
            write_json(source/'area-layouts.json',{'page_layout_files':[{'id':layout['id'],'file':name,'sha256':pin,
                'document_sha256':layout['document_sha256'],'page':layout['page']}]})
            write_json(source/'page.json',{'source_hatch_region_review':data['paving'],'gap_boundary_review':data['gaps']})
            manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
            try:
                runtime.store.add_job({'id':'source','kind':'planning_source_pilot','config_path':str(root/'unused.json'),'config_sha256':'a'*64,'output_directory':str(source)})
                runtime.store.update_job('source',status='completed',result={'output_sha256':manifest,'pages':[{
                    'document_sha256':layout['document_sha256'],'page':layout['page'],'evidence_file':'page.json'}]})
                identifier=runtime.submit_planning_area_world_preview('source');job=_wait(runtime,identifier)
                self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertGreater(job['result']['fence_columns'],0)
            finally:runtime.close(wait=True)
            reopened=DesktopRuntime(root/'memory',workers=1,memory_budget_mb=2048)
            try:self.assertEqual(reopened.store.job(identifier)['result'],job['result'])
            finally:reopened.close(wait=True)


if __name__=='__main__':unittest.main()
