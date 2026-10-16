"""Cold-reopen the packaged scale worlds and compare source terrain and nested chunks."""
import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

import amulet
import numpy as np
import rasterio
from rasterio.windows import from_bounds

from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.native_tile_export import read_tile,tile_hash,DIMENSION
from voxel_mapper.scale_trial import prepare,load_job,TileFactory


def validate(job_path,output):
    output=Path(output);job,identity,compiled=prepare(job_path,output)
    _,paths,_,_=load_job(job_path)
    with rasterio.open(paths['terrain']) as source:
        window=from_bounds(*compiled['bounds_bng_m'],source.transform).round_offsets().round_lengths()
        original=source.read(1,window=window,masked=True)
    heights=np.load(output/'prepared/heights.npy')
    assert original.count()==original.size
    np.testing.assert_array_equal(np.floor(original.data).astype(np.int16),heights)
    factory=TileFactory(output/'prepared',compiled)
    receipts={};previous={};comparisons=0
    native_top_material=native_top_height=None
    try:
        for side in job['stages']:
            if side==max(job['stages']):
                native_top_material=np.zeros((side*16,side*16),dtype=np.uint16)
                native_top_height=np.zeros((side*16,side*16),dtype=np.int16)
            stage=output/('stage-'+str(side));report=json.loads((stage/'scale-report.json').read_text())
            assert report['status']=='native_complete' and report['verified_chunks']==side*side
            assert report['contract']['inputs']==identity['inputs']
            assert file_hash(stage/'park.mcworld')==report['world_sha256']
            with sqlite3.connect(stage/'export-state.sqlite') as state:
                committed={(x,z):(sha,ready) for x,z,sha,ready in state.execute('SELECT cx,cz,sha,ready FROM chunks')}
            expected_coords={(x,z) for x in range(-side//2,side//2) for z in range(-side//2,side//2)}
            assert committed.keys()==expected_coords and all(ready==1 for _,ready in committed.values())
            checked=seams=0;hashes={}
            with tempfile.TemporaryDirectory(prefix='scale-package-cold-check-') as temporary:
                root=Path(temporary)
                with zipfile.ZipFile(stage/'park.mcworld') as archive:
                    assert archive.testzip() is None
                    archive.extractall(root)
                embedded=json.loads((root/'voxel-scale-report.json').read_text())
                assert embedded['status']=='native_complete'
                assert embedded['verified_chunks']==side*side
                assert embedded['contract']==report['contract']
                level=amulet.load_level(str(root))
                try:
                    assert set(level.all_chunk_coords(DIMENSION))==expected_coords
                    stored=level.level_wrapper.root_tag.compound
                    assert [int(stored['Spawn'+axis]) for axis in 'XYZ']==report['spawn_native_xyz']
                    for cx,cz in sorted(expected_coords):
                        actual=read_tile(level,cx,cz,factory.materials)
                        planned=factory(cx,cz)
                        np.testing.assert_array_equal(actual,planned)
                        digest=tile_hash(actual);assert digest==committed[cx,cz][0]
                        hashes[cx,cz]=digest;checked+=actual.size
                        # Independent raw-raster seam check: unmodified boundary
                        # columns must end at their sampled terrain, without a
                        # chunk-specific offset, transpose, gap or flat landing.
                        boundary=np.zeros((16,16),dtype=bool)
                        boundary[0,:]=True;boundary[-1,:]=True;boundary[:,0]=True;boundary[:,-1]=True
                        for x,z in factory.db.execute('SELECT DISTINCT x,z FROM voxels WHERE cx=? AND cz=?',(cx,cz)):
                            boundary[x%16,z%16]=False
                        row,col=cz*16+factory.half,cx*16+factory.half
                        source_ground=np.floor(original.data[row:row+16,col:col+16]).T+compiled['vertical_offset_blocks']
                        top=319-np.argmax(actual[:,::-1,:]!=0,axis=1)
                        np.testing.assert_array_equal(top[boundary],source_ground[boundary])
                        if native_top_material is not None:
                            native_top_material[row:row+16,col:col+16]=np.take_along_axis(actual,(top+64)[:,None,:],axis=1)[:,0,:].T
                            native_top_height[row:row+16,col:col+16]=top.T
                        seams+=int(np.count_nonzero(boundary))
                    x,y,z=report['spawn_native_xyz'];tile=read_tile(level,x//16,z//16,factory.materials)
                    assert tile[x%16,y+63,z%16] and not np.any(tile[x%16,y+64:y+66,z%16])
                finally:level.close()
            assert previous.keys()<=hashes.keys()
            for coordinate,digest in previous.items():assert hashes[coordinate]==digest
            comparisons+=len(previous);previous=hashes
            receipts[str(side)]={'status':'passed','world_sha256':report['world_sha256'],
                'native_chunks_cold_checked':len(hashes),'native_cell_positions_cold_checked':checked,
                'bare_terrain_boundary_columns_checked':seams,'nested_previous_chunk_hashes_identical':True,
                'composed_blocks':report['composed_blocks'],'package_bytes':report['package_bytes'],
                'elapsed_export_seconds':report['elapsed_seconds'],'peak_process_rss_mib':report['peak_process_rss_mib'],
                'resumed_verified_chunks':report['resumed_verified_chunks']}
            print(json.dumps({'side':side,'status':'cold_verified','chunks':len(hashes),'cell_positions':checked}),flush=True)
    finally:factory.close()
    np.save(output/'native-top-material.npy',native_top_material)
    np.save(output/'native-top-height.npy',native_top_height)
    result={'version':'real-area-scale-cold-validation-v1','status':'passed','area':job['area'],
            'source_identity':identity,'stages':receipts,
            'native_cell_positions_cold_checked':sum(r['native_cell_positions_cold_checked'] for r in receipts.values()),
            'bare_terrain_boundary_columns_checked':sum(r['bare_terrain_boundary_columns_checked'] for r in receipts.values()),
            'nested_chunk_pairs_identical':comparisons,'raw_terrain_window_matches_prepared_heights':True,
            'native_height_range_inclusive':[-64,319],'minecraft_playtest':'not_performed',
            'validation_script_sha256':file_hash(Path(__file__)),
            'native_preview_arrays_sha256':{name:file_hash(output/name) for name in ('native-top-material.npy','native-top-height.npy')},
            'accepted_planning_components':0,'training_labels_generated':0}
    atomic_json(output/'cold-validation.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=validate(args.job,args.output)
    print(json.dumps({k:r[k] for k in ('status','native_cell_positions_cold_checked','nested_chunk_pairs_identical')}))
