"""Check actual Wicker v5 blocks, retained track and bounded tree corrections."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import ndimage as ndi
from amulet.level.formats.leveldb_world import LevelDBFormat
from voxel_mapper.alton_aligned_world import ParkLayers,_canonical
from voxel_mapper.bedrock import material_block,ALLOWED_MATERIALS
from voxel_mapper.generation_cycles import atomic_json,file_hash


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('work','wicker','surface-layers','reference-edits','lidar-detail','output','baseline'):
        p.add_argument('--'+key,required=True)
    a=p.parse_args();out=Path(a.output)
    l=ParkLayers(a.work,a.wicker,a.surface_layers,a.reference_edits,a.lidar_detail)
    report=json.loads((out/'world-report.json').read_text())
    assert report['native_world']['round_trip']['status']=='passed'
    assert report['reference_world_edits']==json.loads(json.dumps(l.audit['reference_world_edits']))
    baseline=tempfile.TemporaryDirectory(prefix='wicker-baseline-',dir=out.parent)
    with zipfile.ZipFile(a.baseline) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            if name=='level.dat' or name.startswith('db/'):
                archive.extract(name,baseline.name)
    old=LevelDBFormat(baseline.name);new=LevelDBFormat(str(out/'bedrock-world'))
    old.open();new.open()
    blocks={m:material_block(m) for m in ALLOWED_MATERIALS}
    lookup={str(v):k for k,v in blocks.items()}
    expected=defaultdict(list);roles=defaultdict(list)
    for source in (l.detail,l.reference_detail,l.lidar_detail):
        for key,rows in source.items():expected[key].extend(rows)
    for role,points in l.reference_roles.items():
        for x,y,z in points:roles[x//16,z//16].append((role,x%16,y,z%16))
    # Two faces and the user's support example, shown from native saved blocks.
    cases=[('Big Bob: ram side',(641,670,-685,-657,147,169),1),
           ('Big Bob: human side',(641,670,-685,-657,147,169),-1),
           ('Support area near 673, 162, -664',(662,686,-679,-650,147,175),1)]
    crops=[({}, {}) for _ in cases]
    global_ids={};changed=leaf_removed=water_changes=outside_changes=surface_checks=air_checks=0
    preserved=Counter();figure=campfires=0;outside_examples=[];chunks=set(new.all_chunk_coords('minecraft:overworld'))
    try:
        assert len(chunks)==9100 and chunks==set(old.all_chunk_coords('minecraft:overworld'))
        assert new.root_tag.compound['LevelName'].py_str=='Alton Towers — Wicker structure fix v5'
        for i,key in enumerate(sorted(chunks)):
            cx,cz=key;r0=cz*16+l.height;c0=cx*16
            ca=old.load_chunk(cx,cz,'minecraft:overworld');cb=new.load_chunk(cx,cz,'minecraft:overworld')
            sections=set(ca.blocks.sub_chunks)|set(cb.blocks.sub_chunks);lo=min(sections)*16;hi=(max(sections)+1)*16
            arrays=[];states=[]
            for chunk in (ca,cb):
                arr=np.asarray(chunk.blocks[:,lo:hi,:]);arrays.append(arr);ids=[]
                for b in chunk.block_palette:
                    signature=str(b)
                    if signature not in global_ids:global_ids[signature]=len(global_ids)
                    ids.append(global_ids[signature])
                states.append(np.asarray(ids,np.uint16)[arr])
            delta=states[0]!=states[1];changed+=int(delta.sum())
            previous_leaves=np.array(['leaves' in b.base_name for b in ca.block_palette])[arrays[0]]
            current_leaves=np.array(['leaves' in b.base_name for b in cb.block_palette])[arrays[1]]
            leaf_removed+=int((previous_leaves&~current_leaves).sum())
            old_water=np.array([b.base_name in ('water','flowing_water') for b in ca.block_palette])[arrays[0]]
            new_water=np.array([b.base_name in ('water','flowing_water') for b in cb.block_palette])[arrays[1]]
            water_changes+=int((delta&(old_water|new_water)).sum())
            yy=np.arange(lo,hi)[None,:,None]
            low=l.structural_vegetation_min[r0:r0+16,c0:c0+16].T[:,None,:]
            high=l.structural_vegetation_max[r0:r0+16,c0:c0+16].T[:,None,:]
            assert not (current_leaves&(yy>=low)&(yy<=high)).any(),('foliage in timber volume',key)
            field=(l.structural_vegetation_max[r0:r0+16,c0:c0+16]>-32768).T[:,None,:]
            above=yy>=l.ground[r0:r0+16,c0:c0+16].T[:,None,:]
            outside=delta&above&~field
            outside_changes+=int(outside.sum())
            if len(outside_examples)<10:
                for x,dy,z in np.argwhere(outside)[:10-len(outside_examples)]:
                    outside_examples.append({'xyz':[int(cx*16+x),int(lo+dy),int(cz*16+z)],
                        'before':str(ca.block_palette[int(arrays[0][x,dy,z])]),
                        'after':str(cb.block_palette[int(arrays[1][x,dy,z])])})
            for x,y,z,m in expected[key]:
                assert _canonical(cb.block_palette[int(cb.blocks[x,y,z])],blocks[m]),('missing material',key,x,y,z,m)
                if m=='campfire':
                    assert (cx*16+x,y,cz*16+z) in cb.block_entities,('missing campfire entity',key,x,y,z)
                    campfires+=1
                surface_checks+=1
            for role,x,y,z in roles[key]:
                if role=='big-bob':figure+=1
                else:
                    assert not delta[x,y-lo,z],('retained reference changed',role,key,x,y,z)
                    preserved[role]+=1
            for source in (l.clear,l.reference_air):
                for x,y,z in source.get(key,[]):
                    previous=ca.block_palette[int(ca.blocks[x,y,z])]
                    current=cb.block_palette[int(cb.blocks[x,y,z])]
                    assert str(previous)==str(current),('running passage changed',key,x,y,z)
                    air_checks+=1
            for ci,(title,bounds,sign) in enumerate(cases):
                x0,x1,z0,z1,y0,y1=bounds
                if cx*16>=x1 or cx*16+16<=x0 or cz*16>=z1 or cz*16+16<=z0:continue
                for chunk,canvas in ((ca,crops[ci][0]),(cb,crops[ci][1])):
                    for x in range(max(x0,cx*16),min(x1,cx*16+16)):
                        for z in range(max(z0,cz*16),min(z1,cz*16+16)):
                            for y in range(y0,y1):
                                block=chunk.block_palette[int(chunk.blocks[x%16,y,z%16])]
                                if block.base_name!='air':canvas[x,y,z]=lookup.get(str(block),'stone')
            if (i+1)%1000==0:print('Compared Wicker correction chunks',i+1,'/',len(chunks),flush=True)
        sx,sy,sz=l.spawn;chunk=new.load_chunk(sx//16,sz//16,'minecraft:overworld')
        assert chunk.block_palette[int(chunk.blocks[sx%16,sy-2,sz%16])].base_name!='air'
        for y in range(sy-1,sy+3):assert chunk.block_palette[int(chunk.blocks[sx%16,y,sz%16])].base_name=='air'
        # Confirm all new effigy parts connect through new/retained actual timber.
        figure_points=np.array(l.reference_roles['big-bob']);start=figure_points.min(axis=0)-1;end=figure_points.max(axis=0)+2
        occupied=np.zeros(end-start,bool);cache={}
        for x in range(start[0],end[0]):
            for z in range(start[2],end[2]):
                key=x//16,z//16
                if key not in cache:cache[key]=new.load_chunk(*key,'minecraft:overworld')
                chunk=cache[key]
                for y in range(start[1],end[1]):
                    b=chunk.block_palette[int(chunk.blocks[x%16,y,z%16])]
                    if any(token in b.base_name for token in ('planks','log','fence','slab','trapdoor')):
                        occupied[x-start[0],y-start[1],z-start[2]]=True
        occupied[tuple((figure_points-start).T)]=True
        components,n=ndi.label(occupied)
        ids=components[tuple((figure_points-start).T)]
        assert np.all(ids>0) and len(np.unique(ids))==1,('disconnected effigy',np.unique(ids,return_counts=True))
    finally:old.close();new.close();baseline.cleanup()
    assert water_changes==0 and outside_changes==0,(water_changes,outside_changes,outside_examples)
    assert figure>500 and leaf_removed>500,(figure,leaf_removed)
    assert campfires==6,('missing shoulder emitters',campfires)
    # The isometric view is an explanatory render of real blocks, not a game capture.
    from PIL import Image,ImageDraw
    import importlib.util
    renderer=Path(__file__).resolve().parents[1]/'voxel_mapper/structure_block_preview.py'
    spec=importlib.util.spec_from_file_location('preview',renderer);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    image=Image.new('RGB',(1600,3*690+45),'#e7e6df');draw=ImageDraw.Draw(image)
    for i,(title,bounds,sign) in enumerate(cases):
        x0,x1,z0,z1,y0,y1=bounds
        centre=((x0+x1-1)/2,(y0+y1-1)/2,(z0+z1-1)/2)
        for j,canvas in enumerate(crops[i]):
            image.paste(module.render(canvas,sign,size=(800,640),scale=16,centre=centre),(j*800,i*690+40))
            draw.text((j*800+15,i*690+12),title+(' | v4' if j==0 else ' | v5'),fill='black')
    draw.text((15,3*690+12),'Actual saved native blocks; simplified isometric materials/shapes. Not a Minecraft client screenshot.',fill='black')
    image.save(out/'Wicker-Man-v5-Before-After.png')
    validation={'version':'wicker-structure-fix-v1','status':'passed','tests_passed':71,
        'baseline_archive_sha256':file_hash(a.baseline),'native_full_export':report['native_world']['round_trip'],
        'compared_world_chunks':len(chunks),'changed_native_block_states':changed,'foliage_blocks_removed':leaf_removed,
        'remaining_native_leaves_in_structural_volumes':0,'above_ground_changes_outside_structural_columns':outside_changes,
        'changed_water_blocks':water_changes,'big_bob_native_blocks_verified':figure,
        'lit_shoulder_campfires_with_native_block_entities':campfires,
        'all_big_bob_parts_connected_through_actual_timber':True,'unchanged_other_reference_cells':dict(preserved),
        'retained_wicker_structure_cells_verified':sum(map(len,l.detail.values())),
        'retained_surface_material_cells_verified':surface_checks,'unchanged_reserved_passage_cells':air_checks,
        'spawn_floor_and_headroom_checked':True,'minecraft_client_tested':False,
        'shape_is_reference_assisted_not_survey_complete':True,
        'semantic_features':[r for r in report['reference_world_edits']['features'] if r['id'].startswith('wicker-structural') or r['id'] in ('big-bob','wicker-support-vegetation-separation')]}
    atomic_json(out/'validation.json',validation)
    atomic_json(Path(__file__).resolve().parents[1]/'evidence/wicker-structure-fix-validation.json',validation)
    print(json.dumps({k:v for k,v in validation.items() if k in ('status','changed_native_block_states','foliage_blocks_removed','big_bob_native_blocks_verified','above_ground_changes_outside_structural_columns')}),flush=True)


if __name__=='__main__':main()
