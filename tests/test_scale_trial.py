"""Dense native tiles: real material faults, restart intent and source-bound scaling."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

import amulet
import numpy as np
import rasterio
from rasterio.transform import from_origin

from voxel_mapper.bedrock import material_block
from voxel_mapper.horizontal_grid import OSTN15Transform
from voxel_mapper.native_tile_export import export,SHAPE,read_tile,tile_hash
from voxel_mapper.scale_trial import prepare,run_stage

ROOT=Path(__file__).resolve().parents[1]


class NativeTileTests(unittest.TestCase):
    materials=['air','grass_block','stone']
    def tile(self,cx,cz):
        array=np.zeros(SHAPE,dtype=np.uint16)
        array[:,124:128,:]=2;array[:,128,:]=1
        array[4:7,129:132,4:7]=2
        return array
    def run_export(self,root,**kwargs):
        return export(root,{'fixture':'dense-native'},[(0,0),(1,0),(-1,-1)],self.tile,self.materials,
                      [0,65,0],{'name':'Synthetic tile test'},batch_size=2,**kwargs)

    def test_dense_native_all_materials_air_and_coverage_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'world';r=self.run_export(root)
            self.assertEqual(r['status'],'native_complete');self.assertEqual(r['verified_chunks'],3)
            self.assertEqual(r['native_cell_positions_checked_this_run'],3*16*384*16)
            with zipfile.ZipFile(root/'park.mcworld') as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(json.loads(archive.read('voxel-scale-report.json'))['accepted_planning_components'],0)
            level=amulet.load_level(str(root/'bedrock-world'))
            try:
                self.assertEqual(set(level.all_chunk_coords('minecraft:overworld')),{(0,0),(1,0),(-1,-1)})
                for x,z in [(-1,-1),(0,0),(1,0)]:np.testing.assert_array_equal(read_tile(level,x,z,self.materials),self.tile(x,z))
            finally:level.close()

    def test_checkpoint_resumes_existing_chunks_and_does_not_publish_partial_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'world';first=self.run_export(root,chunk_limit=1)
            self.assertEqual(first['status'],'partial_checkpoint');self.assertFalse((root/'park.mcworld').exists())
            second=self.run_export(root)
            self.assertEqual(second['resumed_verified_chunks'],1);self.assertEqual(second['new_chunks'],2)
            package=(root/'park.mcworld').read_bytes()
            third=self.run_export(root)
            self.assertEqual(third['world_sha256'],second['world_sha256'])
            self.assertEqual(package,(root/'park.mcworld').read_bytes())
            self.assertEqual(json.loads((root/'resume-check.json').read_text())['new_chunks'],0)

    def test_native_flush_before_ready_journal_recovers_without_rewriting_good_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'world'
            def crash(phase,*unused):
                if phase=='after_flush':raise RuntimeError('simulated interruption after native flush')
            with self.assertRaisesRegex(RuntimeError,'native flush'):self.run_export(root,fault=crash)
            self.assertFalse((root/'park.mcworld').exists())
            with sqlite3.connect(root/'export-state.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM chunks WHERE ready=0').fetchone()[0],2)
            result=self.run_export(root)
            self.assertEqual(result['recovered_flushed_chunk_intents'],2)
            self.assertEqual(result['resumed_verified_chunks'],2);self.assertEqual(result['new_chunks'],1)

    def test_changed_source_contract_and_native_material_fault_reject_resume(self):
        for fault in ('contract','native','factory'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'world';self.run_export(root,chunk_limit=1)
                if fault=='contract':
                    with self.assertRaisesRegex(ValueError,'contract'):
                        export(root,{'fixture':'changed'},[(0,0),(1,0),(-1,-1)],self.tile,self.materials,[0,65,0],{'name':'test'})
                elif fault=='factory':
                    def changed(x,z):
                        a=self.tile(x,z);a[0,128,0]=2;return a
                    with self.assertRaisesRegex(ValueError,'pinned source'):
                        export(root,{'fixture':'dense-native'},[(0,0),(1,0),(-1,-1)],changed,self.materials,[0,65,0],{'name':'test'})
                else:
                    level=amulet.load_level(str(root/'bedrock-world'))
                    try:
                        chunk=level.get_chunk(-1,-1,'minecraft:overworld')
                        chunk.blocks[0,64,0]=chunk.block_palette.get_add_block(material_block('stone'))
                        chunk.changed=True;level.put_chunk(chunk,'minecraft:overworld');level.save()
                    finally:level.close()
                    with self.assertRaisesRegex(ValueError,'native chunk'):self.run_export(root)
                self.assertFalse((root/'park.mcworld').exists())

    def test_unknown_palette_invalid_tile_and_unbounded_settings_do_not_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for limit in (0,True,-1):
                with self.subTest(limit=limit),self.assertRaises(ValueError):self.run_export(root/str(limit),chunk_limit=limit)
            def invalid(x,z):
                array=self.tile(x,z);array[0,100,0]=1000;return array
            with self.assertRaisesRegex(ValueError,'known material'):
                export(root/'bad',{},[(0,0)],invalid,self.materials,[0,65,0],{'name':'bad'})
            self.assertFalse((root/'bad/park.mcworld').exists())


class ScaleSourceTests(unittest.TestCase):
    def fixture(self,root):
        anchor=[407952,343264];grid=ROOT/'docs/evidence/world-pilot/alton-ostn15-grid.tif'
        def pin(p):return {'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        operation={'method':'ostn15-bng-v1','path':str(grid),'sha256':pin(grid)['sha256']}
        coordinate=OSTN15Transform(4326,27700,operation)
        values=np.full((64,64),180,dtype='float32');values[:32]=181;values[:,32:]+=2
        for name,array in [('ground',values),('surface',values+6)]:
            with rasterio.open(root/(name+'.tif'),'w',driver='GTiff',width=64,height=64,count=1,
                               dtype='float32',crs='EPSG:27700',transform=from_origin(anchor[0]-32,anchor[1]+32,1,1),nodata=-9999) as ds:ds.write(array,1)
        nodes=[];ways=[];index=1
        def way(points,tags,identifier):
            nonlocal index
            refs=[]
            for x,z in points:
                lon,lat=coordinate.inverse(anchor[0]+x,anchor[1]+z)
                nodes.append(f'<node id="{index}" lon="{lon}" lat="{lat}"/>');refs.append(index);index+=1
            if len(points)>2 and points[0]==points[-1]:refs[-1]=refs[0]
            ways.append('<way id="'+str(identifier)+'">'+''.join(f'<nd ref="{i}"/>' for i in refs)+
                        ''.join(f'<tag k="{k}" v="{v}"/>' for k,v in tags.items())+'</way>')
        way([(-25,-3),(25,-3)],{'highway':'footway','surface':'asphalt','width':'2'},1001)
        way([(4,4),(12,4),(12,12),(4,12),(4,4)],{'building':'yes','height':'6'},1002)
        way([(-4,-10),(4,-10)],{'highway':'footway','bridge':'yes','layer':'1'},1003)
        way([(-12,8),(-6,8),(-6,14),(-12,14),(-12,8)],{'natural':'water'},1004)
        payload=('<osm>'+''.join(nodes+ways)+'</osm>').encode();osm=root/'osm.xml.gz';osm.write_bytes(gzip.compress(payload,mtime=0))
        job={'version':'real-area-scale-trial-v1','name':'Synthetic nested source trial','area':{'name':'test'},
             'anchor_bng_m':anchor,'stages':[2,4],'terrain':pin(root/'ground.tif'),'surface':pin(root/'surface.tif'),
             'osm':{**pin(osm),'xml_sha256':hashlib.sha256(payload).hexdigest()},'horizontal_grid':pin(grid),
             'budgets':{'max_feature_columns':100000,'max_overlay_voxels':2000000,'max_native_blocks':200000000},
             'sources':[]}
        path=root/'job.json';path.write_text(json.dumps(job));return path,job

    def test_real_raster_and_xml_pipeline_has_identical_nested_chunks_and_withholds_bridge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,_=self.fixture(root);output=root/'out'
            _,_,compiled=prepare(path,output)
            self.assertEqual(compiled['terrain_coverage_fraction'],1)
            self.assertEqual(compiled['emitted_features_by_kind']['building'],1)
            self.assertTrue(any(d['id']=='osm/way/1003' and d['status']=='withheld' for d in compiled['decisions']))
            small=run_stage(path,output,2);large=run_stage(path,output,4)
            self.assertEqual(small['verified_chunks'],4);self.assertEqual(large['verified_chunks'],16)
            self.assertEqual(small['spawn_native_xyz'],large['spawn_native_xyz'])
            level=amulet.load_level(str(output/'stage-4/bedrock-world'))
            try:
                for x,z in [(-21,-21),(-21,21),(21,-21),(21,21)]:
                    source_y=180+int(z<0)+2*int(x>=0)
                    y=source_y+compiled['vertical_offset_blocks']
                    self.assertEqual(level.get_block(x,y,z,'minecraft:overworld').base_name,'grass_block')
                    self.assertEqual(level.get_block(x,y+1,z,'minecraft:overworld').base_name,'air')
            finally:level.close()
            with sqlite3.connect(output/'stage-2/export-state.sqlite') as a,sqlite3.connect(output/'stage-4/export-state.sqlite') as b:
                larger={(x,z):sha for x,z,sha in b.execute('SELECT cx,cz,sha FROM chunks')}
                for x,z,sha in a.execute('SELECT cx,cz,sha FROM chunks'):self.assertEqual(sha,larger[x,z])
            self.assertEqual(compiled['accepted_planning_components'],0)
            self.assertEqual(compiled['training_labels_generated'],0)

    def test_nodata_changed_input_and_oversized_stages_cannot_publish(self):
        for fault in ('nodata','checksum','stages','budget'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);path,job=self.fixture(root)
                if fault=='nodata':
                    with rasterio.open(root/'ground.tif','r+') as ds:
                        a=ds.read(1);a[0,0]=-9999;ds.write(a,1)
                    job['terrain']['sha256']=hashlib.sha256((root/'ground.tif').read_bytes()).hexdigest()
                elif fault=='checksum':(root/'osm.xml.gz').write_bytes(b'changed')
                elif fault=='stages':job['stages']=[1500]
                else:job['budgets']['max_overlay_voxels']=2000001
                path.write_text(json.dumps(job))
                with self.assertRaises(ValueError):run_stage(path,root/'out',2)
                self.assertFalse((root/'out/stage-2/park.mcworld').exists())
