"""Native planning paving joins, conservative guards and unverified level claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import amulet
import pymupdf
import rasterio
from shapely.geometry import box, mapping

from voxel_mapper.bedrock import export_world, material_block
from voxel_mapper.pilot_access import (SURFACE_POLICY, SURFACE_STEP_POLICY, SURFACE_STEP_FEATURE,
    PATH_STEP_FEATURE, _mapped_nodes, _read_inputs, _scene, _review_surface_nodes, collision)
from voxel_mapper.pilot_access import _walkthrough
from voxel_mapper.pilot_surface_steps import append, verify, validate_settings
from voxel_mapper.pilot_navigation import inspect
from voxel_mapper.world_pilot import run
import test_pilot_surfaces as surface_fixtures
import test_pilot_review as review_fixtures

SETTINGS = {'policy':SURFACE_STEP_POLICY,'max_slabs':128}


class PlanningPavingJoinTests(unittest.TestCase):
    def job(self, root):
        path,job,_,_ = surface_fixtures.PlanningSurfaceTests().fixture(root)
        helper = review_fixtures.PilotReviewTests()
        with rasterio.open(root/'terrain.tif','r+') as raster:
            heights=raster.read(1);heights[:,61:]=181;raster.write(heights,1)
        config=json.loads((root/'config.json').read_text())
        config['terrain']['sha256']=helper.pin(root/'terrain.tif')['sha256']
        job['config']=helper.write(root/'config.json',config)
        with pymupdf.open(root/'paving.pdf') as pdf:
            page=pdf[0]
            page.insert_text((133,77),'+181.5',fontsize=6)
            page.insert_text((145,54),'+999.0',fontsize=6)
            page.insert_text((84,53),'FFL 182.5',fontsize=5)
            page.insert_text((400,450),'180.00',fontsize=6)
            data=pdf.tobytes()
        (root/'paving.pdf').write_bytes(data)
        job['review_surfaces']['source_pdf']=helper.pin(root/'paving.pdf')
        metadata=json.loads((root/'paving-source.json').read_text())
        metadata['document_sha256']=helper.pin(root/'paving.pdf')['sha256']
        job['review_surfaces']['source_record']=helper.write(root/'paving-source.json',metadata)
        job['review_surface_steps']=copy.deepcopy(SETTINGS)
        helper.write(path,job)
        return path,job

    def test_native_job_replays_joins_and_keeps_extreme_printed_levels_unapplied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,_=self.job(root)
            report=run(path,root/'one');joins=report['planning_paving_joins_review']
            self.assertEqual(joins['status'],'native_joins_verified')
            self.assertGreater(joins['verified_joins'],0)
            self.assertEqual(joins['before']['mapped_supported_cells'],joins['native_after']['mapped_supported_cells'])
            self.assertLess(joins['native_after']['walking_surface_components'],joins['before']['walking_surface_components'])
            self.assertEqual(joins['terrain_excavation_cells'],0)
            self.assertEqual(joins['absolute_finished_levels_applied'],0)
            levels=report['planning_paving_levels_review']
            self.assertEqual(levels['proposed_plus_claims'],2);self.assertEqual(levels['floor_claims'],1)
            self.assertIn(999,[c['printed_value_m'] for c in levels['claims']])
            self.assertTrue(all(c['applied_to_world'] is False for c in levels['claims']))
            self.assertTrue(all(c['vertical_datum_verified'] is False for c in levels['claims']))
            self.assertEqual(levels['absolute_finished_levels_applied'],0)
            self.assertEqual(report['readiness']['planning_components_voxelized'],0)
            form=json.loads((root/'one/playtest-results.json').read_text())
            self.assertTrue(all(c['outcome']=='not_run' for c in form['checks']))
            self.assertIn('planning-paving-joins',[c['id'] for c in form['checks']])
            self.assertEqual(form['world']['sha256'],report['world']['sha256'])
            with zipfile.ZipFile(root/'one/park.mcworld') as archive:
                embedded=json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(embedded['planning_paving_joins_review'],joins)
                self.assertEqual(embedded['planning_paving_levels_review'],levels)
            run(path,root/'two')
            for name in ('voxels.jsonl','planning-paving-joins-review.json','planning-paving-levels-review.json'):
                self.assertEqual((root/'one'/name).read_bytes(),(root/'two'/name).read_bytes())

    def test_wrong_native_slab_material_with_the_same_bearing_rejects_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,_=self.job(root)
            def wrapped(voxels,output,quality,*args,post_export_check=None,**kwargs):
                def corrupt(world,offset,spawn):
                    row=next(json.loads(line) for line in voxels.read_text().splitlines()
                             if json.loads(line).get('feature')==SURFACE_STEP_FEATURE)
                    level=amulet.load_level(str(world))
                    try:
                        x,y,z=row['x'],row['y'],row['z'];chunk=level.get_chunk(x//16,(-z)//16,'minecraft:overworld')
                        wrong=material_block('brick_slab')
                        self.assertEqual(collision(wrong),collision(material_block('stone_slab')))
                        chunk.blocks[x%16,y+offset,(-z)%16]=chunk.block_palette.get_add_block(wrong)
                        chunk.changed=True;level.put_chunk(chunk,'minecraft:overworld');level.save()
                    finally:level.close()
                    return post_export_check(world,offset,spawn)
                return export_world(voxels,output,quality,*args,post_export_check=corrupt,**kwargs)
            with patch('voxel_mapper.world_pilot.export_world',side_effect=wrapped):
                with self.assertRaisesRegex(ValueError,'planning paving material'):run(path,root/'scene')
            self.assertFalse((root/'scene.partial/park.mcworld').exists())
            self.assertFalse((root/'scene.partial/bedrock-world').exists())

    def fixture(self, root, heights=(0,0,1,1), extra=()):
        rows=[dict(x=x,y=y,z=0,kind='terrain',material='grass_block') for x,y in enumerate(heights)]
        rows += [dict(x=x,y=y,z=0,kind='plaza',feature='review/planning-paving/000',material='bricks',
                      source='provisional-plan-paving',review_surface_policy=SURFACE_POLICY,
                      source_document_sha256='a'*64,source_page=1,
                      material_origin='estimated_reconstruction_shell',accepted_physical_geometry=False)
                 for x,y in enumerate(heights)]
        rows += list(extra)
        (root/'voxels.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (root/'features-local.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
        (root/'planning-surfaces-source.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[]}))
        quality={'voxel_size_m':1,'voxel_records':len(rows),'spawn_local_xyz_m':[0,heights[0]+1,0],'crs':'unused-by-stub'}
        access={'component':{'anchor_local_m':[0,0],'floor_elevation_m':4},'footprint':box(20,20,24,24),
                'audit_scope':'whole_pilot','routes':[]}
        surfaces={'report':{'placement':{}}};source={'pdf':None,'source':{'document_sha256':'a'*64},'operation':{}}
        return quality,access,surfaces,source

    def append(self,root,quality,access,surfaces,source):
        with patch('voxel_mapper.pilot_surface_steps.extract_levels',return_value={'absolute_finished_levels_applied':0}):
            return append(root,quality,access,SETTINGS,surfaces,source)

    def test_single_join_preserves_source_rows_and_rejects_changed_source_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);q,a,s,source=self.fixture(root)
            before=(root/'voxels.jsonl').read_bytes();prepared=self.append(root,q,a,s,source)
            self.assertEqual(prepared['report']['added_slab_records'],1)
            self.assertTrue((root/'voxels.jsonl').read_bytes().startswith(before))
            records,_,paths,bounds=_read_inputs(root,a['component'],whole_area=True)
            self.assertEqual(len(_review_surface_nodes(_scene(records,bounds),records)),4)
            row=prepared['additions'][0];records[row['x'],row['y'],row['z']]['planning_source_cell']['feature']='wrong/source'
            self.assertEqual(len(_review_surface_nodes(_scene(records,bounds),records)),3)
            with self.assertRaisesRegex(ValueError,'source row|source-linked bearing'):
                verify(root,_scene(records,bounds),{},records,0,{},prepared)

    def test_lower_side_ground_existing_slab_guards_and_mapped_cells_prevent_unsafe_joins(self):
        for fault in ('lower_side','mapped','old_slab','approach','spawn','building','occupied','roof','ungrounded'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);q,a,s,source=self.fixture(root)
                rows=[json.loads(line) for line in (root/'voxels.jsonl').read_text().splitlines()]
                if fault=='lower_side':rows.append(dict(x=1,y=-1,z=1,kind='terrain',material='grass_block'))
                elif fault=='mapped':rows.insert(4,dict(x=1,y=0,z=0,kind='path',material='stone',feature='osm/path'))
                elif fault=='old_slab':rows.append(dict(x=1,y=1,z=1,kind='steps',material='stone_slab',feature=PATH_STEP_FEATURE))
                elif fault=='approach':a['routes']=[[(1,0,2)]]
                elif fault=='spawn':q['spawn_local_xyz_m']=[1,1,0]
                elif fault=='building':a['footprint']=box(2,-2,4,2)
                elif fault in ('occupied','roof'):rows.append(dict(x=1,y=1 if fault=='occupied' else 3,z=0,kind='structure',material='stone'))
                else:next(row for row in rows if row['kind']=='terrain' and row['x']==1)['y']=-1
                (root/'voxels.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                # A finish over a real mapped source must keep its explicit link.
                if fault=='mapped':
                    next(row for row in rows if row['kind']=='plaza' and row['x']==1)['overlays_mapped_source_cell']={'feature':'osm/path','x':1,'y':0,'z':0}
                    (root/'voxels.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                prepared=self.append(root,q,a,s,source)
                self.assertEqual(prepared['report']['added_slab_records'],0)

    def test_settings_without_surfaces_and_unbounded_or_unknown_options_reject_before_output(self):
        for settings in (None,{}, {**SETTINGS,'max_slabs':True},{**SETTINGS,'max_slabs':513},
                         {**SETTINGS,'max_slabs':0},{**SETTINGS,'excavate':True}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):validate_settings(settings)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,job=self.job(root)
            job.pop('review_surfaces');review_fixtures.PilotReviewTests().write(path,job)
            with self.assertRaisesRegex(ValueError,'planning surface review'):run(path,root/'scene')
            self.assertFalse((root/'scene.partial').exists())

    def test_plaza_entrance_witness_cannot_relabel_a_grass_gap_as_paving(self):
        records={(x,0,0):dict(x=x,y=0,z=0,kind='terrain',material='grass_block') for x in range(7)}
        scene=_scene(records,(0,0,6,0));footprint=box(3,-1,6,2)
        args=(scene,(0,0,2),{(3,0,2)},{(3,0)},footprint,2,0)
        self.assertEqual(_walkthrough(*args)['status'],'native_route_ready')
        walking={(0,0,2),(1,0,2)}
        self.assertEqual(_walkthrough(*args,exterior_walking_nodes=walking)['status'],'unresolved')
        walking.add((2,0,2))
        route=_walkthrough(*args,exterior_walking_nodes=walking)
        self.assertEqual(route['status'],'native_route_ready')
        self.assertEqual(route['route_local_x_z_half_y'][route['doorway_index']],[3,0,2])


if __name__=='__main__':unittest.main()
