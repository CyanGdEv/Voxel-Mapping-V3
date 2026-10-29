"""Compare saved park-wide LiDAR blocks with an immutable baseline .mcworld."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import laspy
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from amulet.level.formats.leveldb_world import LevelDBFormat

from voxel_mapper.alton_aligned_world import ParkLayers, MATERIAL_COLOURS, _canonical
from voxel_mapper.bedrock import material_block, ALLOWED_MATERIALS
from voxel_mapper.generation_cycles import atomic_json, file_hash


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('work','wicker','surface-layers','reference-edits','lidar-detail','output','baseline','native-cloud'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args(); out=Path(a.output)
    l=ParkLayers(a.work,a.wicker,a.surface_layers,a.reference_edits,a.lidar_detail)
    report=json.loads((out/'world-report.json').read_text())
    assert report['lidar_detail']==json.loads(json.dumps(l.audit['lidar_detail']))
    assert report['native_world']['round_trip']['status']=='passed'
    baseline=out.parent/'baseline-native'
    if not baseline.exists():
        baseline.mkdir()
        with zipfile.ZipFile(a.baseline) as archive:
            assert archive.testzip() is None
            original=json.loads(archive.read('voxel-quality-report.json'))
            assert original['reference_world_edits']==report['reference_world_edits']
            for entry in archive.namelist():
                if entry=='level.dat' or entry.startswith('db/'):
                    archive.extract(entry,baseline)

    # Verify the full-precision LAZ represents the same complete, unthinned survey
    # evidence indexed by the quarter-metre pipeline, including every class.
    receipt=json.loads(Path(a.lidar_detail).read_text())
    crop=json.loads(Path(a.native_cloud).with_suffix('.json').read_text())
    assert file_hash(a.native_cloud)==crop['sha256']
    keys=[]; raw=[]; raw_codes=[]; counts=Counter(); scanned=0
    with laspy.open(a.native_cloud) as reader:
        assert reader.header.point_count==receipt['eligible_local_points']
        assert reader.header.parse_crs().to_epsg()==27700
        for chunk in reader.chunk_iterator(500_000):
            assert not np.asarray(chunk.withheld,bool).any()
            assert not np.asarray(chunk.synthetic,bool).any()
            x,y,z=np.asarray(chunk.x),np.asarray(chunk.y),np.asarray(chunk.z)
            codes=np.asarray(chunk.classification);scanned+=len(chunk)
            v,n=np.unique(codes,return_counts=True);counts.update({int(k):int(c) for k,c in zip(v,n)})
            qx=np.floor((x-l.e0)*4).astype(np.uint64)
            qr=np.floor((l.n1-y)*4).astype(np.uint64)
            qz=(np.floor(z*4).astype(np.int64)+2048).astype(np.uint64)
            keys.append(qx|(qr<<14)|(qz<<28)|(codes.astype(np.uint64)<<41))
            sel=np.isin(codes,[1,6]);raw.append(np.column_stack([x[sel],y[sel],z[sel]]));raw_codes.append(codes[sel])
    key,count=np.unique(np.concatenate(keys),return_counts=True)
    with np.load(Path(a.lidar_detail).parent/receipt['samples_file']) as cache:
        assert np.array_equal(key,cache['quarter_keys'])
        assert np.array_equal(count,cache['quarter_counts'])
        assert np.array_equal(np.concatenate(raw),cache['xyz'])
        assert np.array_equal(np.concatenate(raw_codes),cache['classification'])
    del keys,raw,raw_codes,key,count
    assert scanned==receipt['eligible_local_points']==crop['retained_points']

    structures=defaultdict(list); air=defaultdict(list); roles=defaultdict(list)
    for source in (l.detail,l.reference_detail,l.lidar_detail):
        for key,rows in source.items():structures[key].extend(rows)
    for key,rows in l.reference_air.items():air[key].extend(rows)
    for role,points in l.reference_roles.items():
        for x,y,z in points:roles[x//16,z//16].append((role,x%16,y,z%16))
    expected={m:material_block(m) for rows in structures.values() for x,y,z,m in rows}
    colour_map=dict(MATERIAL_COLOURS)
    colour_map.update({'white_concrete':(222,224,218),'light_gray_concrete':(164,170,166),
        'red_concrete':(170,35,31),'dark_oak_fence':(67,44,26),'oak_fence':(145,113,65),
        'oak_leaves':(53,101,48),'birch_leaves':(65,113,50),'spruce_leaves':(39,82,45),
        'stone_slab':(145,147,139),'brick_slab':(145,104,78),'dark_oak_slab':(64,43,28)})
    colours={str(material_block(m)):colour_map.get(m,colour_map.get(m.removesuffix('_top'),(125,120,110)))
             for m in ALLOWED_MATERIALS}
    bottoms={str(material_block(m)) for m in ALLOWED_MATERIALS if 'slab' in m and not m.endswith('_top')}
    old_rgb=np.zeros((l.height,l.width,3),np.uint8);new_rgb=old_rgb.copy()
    old_height=np.zeros((l.height,l.width),np.float32);new_height=old_height.copy()
    changes=np.zeros((l.height,l.width),bool)
    state_ids={}; changed=water_changed=role_cells=detail_cells=air_cells=0
    role_counts=Counter()
    old=LevelDBFormat(str(baseline));new=LevelDBFormat(str(out/'bedrock-world'))
    old.open();new.open()
    try:
        chunks=set(new.all_chunk_coords('minecraft:overworld'))
        assert chunks==set(old.all_chunk_coords('minecraft:overworld'))
        assert len(chunks)==9100
        assert new.root_tag.compound['LevelName'].py_str=='Alton Towers — LiDAR detail v4'
        for i,key in enumerate(sorted(chunks)):
            cx,cz=key
            ca=old.load_chunk(cx,cz,'minecraft:overworld');cb=new.load_chunk(cx,cz,'minecraft:overworld')
            sections=set(ca.blocks.sub_chunks)|set(cb.blocks.sub_chunks)
            lo=min(sections)*16;hi=(max(sections)+1)*16
            arrays=[];normal=[]
            for chunk in (ca,cb):
                arr=np.asarray(chunk.blocks[:,lo:hi,:]);arrays.append(arr)
                lookup=[]
                for block in chunk.block_palette:
                    sig=str(block)
                    if sig not in state_ids:state_ids[sig]=len(state_ids)
                    lookup.append(state_ids[sig])
                normal.append(np.asarray(lookup,np.uint16)[arr])
            delta=normal[0]!=normal[1];changed+=int(delta.sum())
            ow=np.array([b.base_name in ('water','flowing_water') for b in ca.block_palette])
            nw=np.array([b.base_name in ('water','flowing_water') for b in cb.block_palette])
            water_changed+=int(((ow[arrays[0]]|nw[arrays[1]])&delta).sum())
            r0,c0=cz*16+l.height,cx*16
            above=np.arange(lo,hi)[None,:,None]>=l.ground[r0:r0+16,c0:c0+16].T[:,None,:]
            changes[r0:r0+16,c0:c0+16]=np.any(delta&above,axis=1).T
            for x,y,z,m in structures[key]:
                assert _canonical(cb.block_palette[int(cb.blocks[x,y,z])],expected[m]),('missing structure',key,x,y,z,m)
                detail_cells+=1
            for role,x,y,z in roles[key]:
                assert not delta[x,y-lo,z],('v3 role changed',role,key,x,y,z)
                role_counts[role]+=1;role_cells+=1
            for x,y,z in air[key]:
                assert cb.block_palette[int(cb.blocks[x,y,z])].base_name=='air',('blocked reference air',key,x,y,z)
                air_cells+=1
            for chunk,arr,canvas,height in ((ca,arrays[0],old_rgb,old_height),(cb,arrays[1],new_rgb,new_height)):
                solid=np.array([b.base_name!='air' for b in chunk.block_palette])
                occupied=solid[arr];top=arr.shape[1]-1-np.argmax(occupied[:,::-1,:],axis=1)
                xx,zz=np.indices((16,16));codes=arr[xx,top,zz]
                lut=np.array([colours.get(str(b),(122,124,117)) for b in chunk.block_palette],np.uint8)
                canvas[r0:r0+16,c0:c0+16]=lut[codes].transpose(1,0,2)
                offset=np.array([.5 if str(b) in bottoms else 1. for b in chunk.block_palette])
                height[r0:r0+16,c0:c0+16]=(top+lo+offset[codes]).T
            if (i+1)%1000==0:print('Compared saved v3/v4 chunks',i+1,'/',len(chunks),flush=True)
        sx,sy,sz=l.spawn;spawn=new.load_chunk(sx//16,sz//16,'minecraft:overworld')
        assert spawn.block_palette[int(spawn.blocks[sx%16,sy-2,sz%16])].base_name!='air'
        for y in range(sy-1,sy+3):assert spawn.block_palette[int(spawn.blocks[sx%16,y,sz%16])].base_name=='air'
    finally:
        old.close();new.close()
    assert water_changed==0
    assert changed>20000
    assert role_cells==sum(map(len,l.reference_roles.values()))
    assert detail_cells==sum(map(len,l.detail.values()))+sum(map(len,l.reference_detail.values()))+sum(map(len,l.lidar_detail.values()))

    # Native block colours and actual saved differences across the full rectangle.
    change_rgb=np.clip(old_rgb*.27+np.array([215,215,207])*.73,0,255).astype(np.uint8)
    change_rgb[changes]=(74,147,77)
    change_rgb[l.lidar_changed_ground&changes]=(226,143,44)
    change_rgb[l.lidar_changed_roofs&changes]=(13,156,193)
    for (cx,cz),rows in l.lidar_detail.items():
        for x,y,z,m in rows:
            r,c=cz*16+z+l.height,cx*16+x
            if changes[r,c]:change_rgb[r,c]=(174,70,178)
    try:font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',20)
    except OSError:font=ImageFont.load_default()
    proof=Image.new('RGB',(3180,650),'#f5f4ef');draw=ImageDraw.Draw(proof)
    for i,(title,arr) in enumerate([('v3 saved world',old_rgb),('v4 park-wide LiDAR update',new_rgb),('Saved geometry changes across the park',change_rgb)]):
        draw.text((i*1060+10,12),title,fill='black',font=font)
        proof.paste(Image.fromarray(arr).resize((1040,560),Image.Resampling.NEAREST),(i*1060+10,55))
    draw.text((10,620),'Actual native blocks. Changes: orange terrain; blue roofs; purple observed surfaces; green other. Not a Minecraft client screenshot.',fill='black',font=font)
    proof.save(out/'Alton-Towers-v4-Park-Wide-Changes.png')

    validation={'version':'alton-park-wide-lidar-world-validation-v1','status':'passed','tests_passed':63,
        'baseline_archive_sha256':file_hash(a.baseline),'native_full_export':report['native_world']['round_trip'],
        'compared_saved_world_chunks':len(chunks),'changed_native_block_states':changed,
        'changed_above_ground_native_columns':int(changes.sum()),'changed_native_water_cells':water_changed,
        'unchanged_v3_reference_cells_by_role':dict(role_counts),'all_retained_and_new_surface_cells_verified':detail_cells,
        'retained_wicker_structure_cells_verified':sum(map(len,l.detail.values())),
        'new_lidar_surface_cells_verified':sum(map(len,l.lidar_detail.values())),
        'reserved_reference_air_cells_verified':air_cells,'spawn_floor_and_headroom_checked':True,
        'native_cloud_points_verified':scanned,'native_cloud_class_counts':dict(counts),
        'native_cloud_quarter_index_keys_counts_and_structural_xyz_match':True,
        'native_cloud_sha256':crop['sha256'],'lidar_sampling':receipt,
        'world_lidar_geometry':{k:v for k,v in report['lidar_detail'].items() if k not in ('source','buildings')},
        'minecraft_client_tested':False,'physical_registration_verified':False,
        'limits':['Quarter-metre sampling is evidence resolution; the world remains 1 m horizontally, using half-block structural surfaces.',
                  'Source gaps and occluded geometry remain unknown. Class 1 is retained evidence, not automatically a structure.',
                  'Existing ride heights/supports/stations remain provisional. No client import or independently surveyed accuracy test is claimed.']}
    atomic_json(out/'validation.json',validation)
    atomic_json(Path(__file__).resolve().parents[1]/'evidence/alton-park-wide-lidar-validation.json',validation)
    atomic_json(Path(__file__).resolve().parents[1]/'evidence/alton-park-wide-lidar-sampling.json',receipt)
    print(json.dumps({k:v for k,v in validation.items() if k in ('status','changed_native_block_states','changed_above_ground_native_columns','new_lidar_surface_cells_verified','compared_saved_world_chunks','native_cloud_points_verified')}),flush=True)


if __name__=='__main__':main()
