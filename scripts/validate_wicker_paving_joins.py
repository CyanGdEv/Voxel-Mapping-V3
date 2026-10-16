"""Cold-check estimated planning paving joins against the packaged paving baseline."""
import argparse
import json
import math
from pathlib import Path
import tempfile
import zipfile

import amulet
from amulet.api.block import Block
import numpy as np
from shapely.geometry import Point,box,shape

from voxel_mapper.bedrock import material_block
from voxel_mapper.pilot_access import (SURFACE_STEP_FEATURE,_read_inputs,_scene,_mapped_nodes,
                                       _review_surface_nodes)
from voxel_mapper.pilot_navigation import _walking_nodes
from validate_wicker_path_steps import digest,load,_route,_clear,_standing_heights
from validate_wicker_planning_surfaces import REPLAY_FILES as PAVING_FILES

DIMENSION='minecraft:overworld'
REPLAY_FILES=(*PAVING_FILES,'planning-paving-joins-review.json','planning-paving-levels-review.json')


def validate(before,after,replay):
    old,new=load(before/'pilot-report.json'),load(after/'pilot-report.json')
    assert old['inputs']['assets']==new['inputs']['assets']
    assert old['world']['spawn']==new['world']['spawn']
    offset=new['world']['vertical_offset_blocks']
    assert old['world']['vertical_offset_blocks']==offset
    retained,additions=[],[]
    with (after/'voxels.jsonl').open('rb') as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('feature')==SURFACE_STEP_FEATURE:additions.append(row)
            else:retained.append(line)
    assert b''.join(retained)==(before/'voxels.jsonl').read_bytes()
    report=new['planning_paving_joins_review']
    assert 0<len(additions)==report['verified_joins']<=512
    assert all(r['material']=='stone_slab' and r['accepted_physical_geometry'] is False for r in additions)
    for name in ('review-component.json','planning-surfaces-source.geojson','planning-surfaces-local.geojson'):
        assert (before/name).read_bytes()==(after/name).read_bytes(),name
    for name,sha in new['output_sha256'].items():assert digest(after/name)==sha,name
    for name in REPLAY_FILES:assert (after/name).read_bytes()==(replay/name).read_bytes(),name
    assert digest(after/'park.mcworld')==new['world']['sha256']
    forms=load(after/'playtest-results.json')
    assert forms['world']['sha256']==new['world']['sha256']
    assert all(c['outcome']=='not_run' for c in forms['checks'])
    assert sum(c['id'].startswith('plaza-entrance/') for c in forms['checks'])==9
    assert new['readiness']['planning_components_voxelized']==0
    assert report['training_labels_generated']==0 and report['accepted_physical_geometry'] is False
    levels=new['planning_paving_levels_review']
    assert levels['proposed_plus_claims']==22 and levels['floor_claims']==3
    assert levels['absolute_finished_levels_applied']==0 and levels['review_floor_datum_verified'] is False
    assert all(c['applied_to_world'] is False and c['vertical_datum_verified'] is False for c in levels['claims'])
    withheld=old['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert withheld==new['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert len(withheld)==9
    assert all(f['emitted_voxel_records']==0 for f in new['geographic_features'] if f['id'] in withheld)
    prior,_,prior_paths,bounds=_read_inputs(before,old['review_component'],whole_area=True)
    records,_,paths,new_bounds=_read_inputs(after,new['review_component'],whole_area=True)
    assert bounds==new_bounds and prior_paths==paths
    old_scene,new_scene=_scene(prior,bounds),_scene(records,bounds)
    old_mapped,new_mapped=_mapped_nodes(old_scene,paths,prior),_mapped_nodes(new_scene,paths,records)
    assert old_mapped==new_mapped
    old_review,new_review=_review_surface_nodes(old_scene,prior),_review_surface_nodes(new_scene,records)
    adjusted={tuple(j['before_local_x_z_half_y']):tuple(j['after_local_x_z_half_y']) for j in report['joins']}
    assert {adjusted.get(p,p):identity for p,identity in old_review.items()}==new_review
    walking=_walking_nodes(new_scene,new_mapped,records)
    expected={(r['x'],r['y']+offset,-r['z']) for r in additions}
    assert len(expected)==len(additions)
    cells,changed,route_points,route_count,gaps=0,set(),0,0,0
    with tempfile.TemporaryDirectory(prefix='paving-join-cold-check-') as temporary:
        root=Path(temporary)
        for label,directory in [('before',before),('after',after)]:
            with zipfile.ZipFile(directory/'park.mcworld') as archive:archive.extractall(root/label)
        embedded=load(root/'after/voxel-quality-report.json')
        assert embedded['planning_paving_joins_review']==report
        assert embedded['planning_paving_levels_review']==levels
        worlds=[]
        try:
            for label in ('before','after'):worlds.append(amulet.load_level(str(root/label)))
            a,b=worlds
            coordinates=set(a.all_chunk_coords(DIMENSION))
            assert coordinates==set(b.all_chunk_coords(DIMENSION))
            assert len(coordinates)==new['world']['chunks']
            palette={Block('universal_minecraft','air'):0}
            def canonical(block):return palette.setdefault(block,len(palette))
            for cx,cz in sorted(coordinates):
                ca,cb=a.get_chunk(cx,cz,DIMENSION),b.get_chunk(cx,cz,DIMENSION)
                la=np.array([canonical(block) for block in ca.block_palette]);lb=np.array([canonical(block) for block in cb.block_palette])
                for section in range(-4,20):
                    aa=la[ca.blocks.get_sub_chunk(section)] if section in ca.blocks.sub_chunks else np.zeros((16,16,16),dtype=int)
                    bb=lb[cb.blocks.get_sub_chunk(section)] if section in cb.blocks.sub_chunks else np.zeros((16,16,16),dtype=int)
                    cells+=aa.size
                    for x,y,z in np.argwhere(aa!=bb):
                        point=cx*16+int(x),section*16+int(y),cz*16+int(z)
                        assert point in expected and aa[x,y,z]==0,point
                        block=cb.block_palette[int(cb.blocks[x,section*16+y,z])];slab=material_block('stone_slab')
                        assert block.namespaced_name==slab.namespaced_name
                        assert all(block.properties.get(k)==v for k,v in slab.properties.items())
                        changed.add(point)
                a.unload();b.unload()
            assert changed==expected
            native_adjustments={(x,z,y):y+.5 for x,y,z in expected}
            cache={}
            for x,y,z in sorted(expected):
                for nx,nz in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)):
                    if not a.has_chunk(nx//16,nz//16,DIMENSION):continue
                    if (nx,nz) not in cache:cache[nx,nz]=_standing_heights(a,nx,nz)
                    for old_feet in cache[nx,nz]:
                        if old_feet==y:continue
                        feet=native_adjustments.get((nx,nz,old_feet),old_feet)
                        assert abs(y+.5-feet)<=abs(y-old_feet)
                        assert _clear(b,nx,nz,feet)
                        gaps+=1
            # Independently check every surviving source walking surface in the
            # saved database, including each newly raised source-linked node.
            for x,z,height in new_mapped.keys()|new_review.keys():
                one={'route_local_x_z_half_y':[[x,z,height]],
                     'route_native_xyz':[[x+.5,height/2+offset,-z+.5]]}
                _route(b,one,offset)
            component=new['review_component']
            footprint=shape(next(f['geometry'] for f in load(after/'features-local.geojson')['features'] if f['id']==component['feature_id']))
            openings={o['id']:o for o in component['access_openings']}
            def entrance(route,identifier,paved=False):
                nonlocal route_points,route_count
                assert route['status']=='native_route_ready'
                route_points+=_route(b,route,offset);route_count+=1
                columns={tuple(p) for p in openings[identifier]['columns_local_xz']}
                prefix=route['route_local_x_z_half_y'][:route['doorway_index']+1]
                for x,z,height in prefix:
                    assert (x,z) in columns or footprint.intersection(box(x,z,x+1,z+1)).area<=1e-8
                    if paved:assert (x,z) in columns or (x,z,height) in walking
                x,z,height=route['route_local_x_z_half_y'][-1]
                assert footprint.buffer(-1).contains(Point(x+.5,z+.5))
                assert height==2*round(component['floor_elevation_m'])
            for opening in new['access_review']['native_readback']['openings']:entrance(opening['walkthrough'],opening['id'])
            for route in new['access_review']['whole_area_navigation']['walkthroughs']:
                route_points+=_route(b,route,offset);route_count+=1
            plazas={}
            for feature in new['planning_surfaces_review']['features']:
                if feature['surface_role']!='labelled_plaza':continue
                assert feature['native_supported_footprint_cells']==feature['reachable_cells_on_walking_surfaces']
                route=feature['walkthrough'];assert route['surface_scope']=='walking_surfaces_only'
                assert all(tuple(p) in walking for p in route['route_local_x_z_half_y'])
                route_points+=_route(b,route,offset);route_count+=1
                plazas[feature['feature_id']]=route['route_local_x_z_half_y'][-1]
            assert len(plazas)==3
            for route in report['plaza_entrance_connections']:
                if route['status']=='native_route_ready':
                    assert route['route_local_x_z_half_y'][0]==plazas[route['plaza_feature_id']]
                    entrance(route,route['opening_id'],paved=True)
                else:assert not route['route_native_xyz']
            stored=b.level_wrapper.root_tag.compound
            assert [int(stored['Spawn'+axis]) for axis in 'XYZ']==new['world']['spawn']
        finally:
            for level in worlds:level.close()
    return {'version':'wicker-planning-paving-join-cold-check-v1','status':'passed',
        'baseline_world_sha256':old['world']['sha256'],'world_sha256':new['world']['sha256'],
        'native_cells_compared':cells,'native_height_range_inclusive':[-64,319],
        'native_added_bottom_stone_slabs':len(changed),'native_original_blocks_modified_or_removed':0,
        'native_nonzero_adjacent_height_gaps_checked':gaps,'preexisting_nonzero_height_gaps_enlarged':0,
        'source_records_byte_identical':True,'source_polygon_files_byte_identical':True,
        'source_component_byte_identical':True,'original_input_assets_identical':True,
        'mapped_supports_native_checked':len(new_mapped),'planning_paving_supports_native_checked':len(new_review),
        'native_route_count':route_count,'native_route_points_checked':route_points,
        'ready_paved_plaza_entrance_routes':report['ready_plaza_entrance_connections'],
        'unresolved_paved_plaza_entrance_routes':report['unresolved_plaza_entrance_connections'],
        'unresolved_connections':[{'plaza_feature_id':r['plaza_feature_id'],'opening_id':r['opening_id']}
            for r in report['plaza_entrance_connections'] if r['status']!='native_route_ready'],
        'replay_identical_files':list(REPLAY_FILES),'artifact_hashes_checked':len(new['output_sha256']),
        'before':report['before'],'native_after':report['native_after'],
        'retained_level_claims':len(levels['claims']),'absolute_finished_levels_applied':0,
        'world_spawn_native_xyz':new['world']['spawn'],
        'withheld_feature_ids_remain_without_geometry':withheld,
        'minecraft_playtest':'not_performed','accepted_physical_geometry':False,'training_labels_generated':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','replay','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=validate(args.before,args.after,args.replay)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ('status','native_cells_compared','native_added_bottom_stone_slabs','native_route_points_checked')}))


if __name__=='__main__':main()
