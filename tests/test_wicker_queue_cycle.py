import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import amulet
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from voxel_mapper.bedrock import export_world,material_block
from voxel_mapper.reconstruction.batch import GeometryStore
from scripts.build_wicker_queue_cycle import build


class NativeQueueCycleTests(unittest.TestCase):
    def test_source_review_publishes_native_cycle_with_terrain_pin_and_protected_columns(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'base';base.mkdir()
            rows=base/'voxels.jsonl';rows.write_text(''.join(json.dumps({'x':x,'y':0,'z':-z,'material':'grass_block','kind':'terrain'})+'\n' for x in range(9) for z in range(9)))
            quality={'voxel_size_m':1,'sources':[],'crs':'EPSG:27700','axis':{},'limitations':[]}
            quality['world']=export_world(rows,base,quality);(base/'quality.json').write_text(json.dumps(quality))
            protected=root/'protected.sqlite';store=GeometryStore(protected,{'fixture':'protected'})
            with store.db:store.db.execute('INSERT INTO voxels VALUES(?,?,?,?,?,?,?)',(2,0,-3,0,0,'grass_block',json.dumps({'kind':'building','feature':'wicker/shop'})))
            store.close()
            station={'station_review':{'parts':[{'id':'station','rotation_degrees':0,'anchor_bng_m':[5,5],'source_outline':{'geometry':box(0,0,10,10).__geo_interface__}}]}}
            (root/'station.json').write_text(json.dumps(station));(root/'floor.pdf').write_bytes(b'synthetic fixture source; extraction tested separately')
            raster=root/'terrain.tif'
            with rasterio.open(raster,'w',driver='GTiff',width=30,height=30,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(-10,10,1,1)) as dst:dst.write(np.zeros((30,30),dtype='float32'),1)
            (root/'terrain.json').write_text(json.dumps({'terrain':{'path':str(raster),'source_id':'terrain','units':'m','vertical_datum':'ODN'},'sources':[{'id':'terrain'}]}))
            job={'output':str(root/'output'),'floor_pdf':str(root/'floor.pdf'),'wicker_quality':str(root/'station.json'),
                 'base_package':str(base/'park.mcworld'),'base_quality':str(base/'quality.json'),'protected_geometry':str(protected),
                 'grid_directory':str(root),'terrain_config':str(root/'terrain.json'),'terrain_raster':str(raster),'review_rails':True}
            p=root/'job.json';p.write_text(json.dumps(job))
            with patch('scripts.build_wicker_queue_cycle.source_walkway',return_value=(box(2,-6,5,-2),{'fixture':'explicit source geometry fixture'})):
                report=build(p)
            self.assertEqual(report['cycle_receipt']['status'],'native_review_batch_export_verified')
            self.assertFalse(report['production_placement_eligible']);self.assertEqual(report['raster']['protected_or_missing_columns'],1)
            self.assertIn('terrain_raster',report['input_sha256'])
            reopened=root/'reopened'
            with zipfile.ZipFile(root/'output/Alton_Towers_V24_Wicker_Queue_Review.mcworld') as archive:archive.extractall(reopened)
            world=amulet.load_level(str(reopened));offset=quality['world']['vertical_offset_blocks']
            try:
                self.assertEqual(world.get_block(2,offset,3,'minecraft:overworld'),material_block('grass_block'))
                self.assertEqual(world.get_block(3,offset,3,'minecraft:overworld'),material_block('stone'))
                self.assertEqual(world.get_block(0,offset,0,'minecraft:overworld'),material_block('grass_block'))
            finally:world.close()
