"""Thicken steep track steps without moving their corrected running heights."""
import argparse
from concurrent.futures import CancelledError
import json
import math
from pathlib import Path
import shutil
import tempfile

from .generation_cycles import atomic_json,file_hash

PROFILE=Path(__file__).with_name('data')/'wicker-steep-track-deck.json'


def surface_top(key,material):
    return key[1]+(.5 if material.endswith('_slab') else 1)


def thicken(track,structures,terrain,head,samples,centre_keys,profile):
    core={k:m for k,m in track.items() if m in ['oak_slab','oak_slab_top','spruce_slab','spruce_slab_top']}
    if len(samples)!=len(centre_keys) or any(tuple(k) not in core for k in centre_keys):
        raise ValueError('Exact saved centre samples and slab deck required')
    selected=set();transitions=[];edge_pairs=[]
    by_xy={}
    for key in core:by_xy.setdefault((key[0],key[2]),[]).append(key)
    for key,m in core.items():
        x,h,y=key
        for xy in [(x+1,y),(x,y+1)]:
            for other in by_xy.get(xy,[]):
                rise=abs(surface_top(key,m)-surface_top(other,core[other]))
                if profile['minimum_steep_rise_m']<=rise<=1.5:
                    selected.update([key,other]);edge_pairs.append([list(key),list(other)])
    for i,(a,b) in enumerate(zip(centre_keys,centre_keys[1:])):
        rise=abs(surface_top(a,core[tuple(a)])-surface_top(b,core[tuple(b)]))
        if rise<profile['minimum_steep_rise_m']:continue
        if abs(a[0]-b[0])+abs(a[2]-b[2])>2:raise ValueError('Disconnected steep step')
        transitions.append({'sample_index':i,'rise_m':rise,'station_m':samples[i]['station_m']})
        for j in range(max(0,i-profile['sample_padding']),min(len(samples),i+profile['sample_padding']+2)):
            centre=tuple(centre_keys[j]);top=surface_top(centre,core[centre])
            for x,y in samples[j]['cells_xy']:
                candidates=[k for k in core if k[0]==x and k[2]==y and abs(surface_top(k,core[k])-top)<=1.5]
                if candidates:selected.add(min(candidates,key=lambda k:abs(surface_top(k,core[k])-top)))
    changes={};receipts=[];held=[]
    for key in sorted(selected):
        old=core[key];wood=old.split('_slab')[0];x,h,y=key
        if old.endswith('_slab_top'):
            proposal={key:wood+'_planks'};kind='full_block'
        else:
            # A bottom slab's surface sits at a half-height. A top slab in the
            # cell below forms one metre of solid wood without raising it.
            proposal={(x,h-1,y):wood+'_slab_top'};kind='paired_half_slabs'
        reason=None
        for k,m in proposal.items():
            if k in head:reason='lower_track_headroom';break
            if k!=key and k in structures:reason='existing_geometry';break
            if (k[0],k[2]) not in terrain or k[1]<=terrain[k[0],k[2]]['y']:
                reason='retained_terrain';break
        if reason:
            held.append({'deck_source_xyz':list(key),'reason':reason});continue
        changes.update(proposal)
        receipts.append({'deck_source_xyz':list(key),'old_material':old,'kind':kind,
                         'writes':[{'source_xyz':list(k),'material':m} for k,m in proposal.items()]})
    new_track={**track,**changes};new_core={k:new_track[k] for k in core}
    if any(surface_top(k,m)!=surface_top(k,new_core[k]) for k,m in core.items()):
        raise ValueError('Steep-deck construction moved a running surface')
    if changes.keys()&head:raise ValueError('Thick deck obstructs track headroom')
    if len(changes)>profile['max_changes']:raise ValueError('Steep deck write budget exceeded')
    return new_track,new_core,changes,{'steep_transitions':transitions,'steep_edge_pairs':edge_pairs,'thickened_deck_cells':receipts,
        'withheld_deck_cells':held,'write_count':len(changes),'running_heights_unchanged':True,
        'new_supports':0,'terrain_changed':False}


def run(base_directory,output,*,cancelled=lambda:False):
    if cancelled():raise CancelledError('Steep track revision cancelled')
    base_directory=Path(base_directory);output=Path(output)
    if output.exists():raise ValueError('Fresh steep track output required')
    profile=json.loads(PROFILE.read_text())
    for name,sha in profile['base_pins'].items():
        if file_hash(base_directory/name)!=sha:raise ValueError('Exact elevation-fixed world required')
    base=json.loads((base_directory/'quality-report.json').read_text())
    rows=[json.loads(l) for l in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'}
    structures={(r['x'],r['y'],r['z']-1):r['material'] for r in rows if r['kind']=='structure'}
    track={tuple(r['source_xyz']):r['material'] for r in json.loads((base_directory/'track-blocks.json').read_text())}
    if any(structures.get(k)!=m for k,m in track.items()):raise ValueError('Track records do not match saved park')
    head={tuple(k) for k in json.loads((base_directory/'running-clearance-air.json').read_text())}
    samples=json.loads((base_directory/'track-samples.json').read_text());keys=base['full_track']['topology']['centre_sample_keys']
    track,core,changes,review=thicken(track,structures,terrain,head,samples,keys,profile)
    report=dict(base);report.update(version='steep-track-deck-v1',implementation_sha256=file_hash(__file__),profile_sha256=file_hash(PROFILE),source_parent_world_sha256=base['world']['sha256'])
    report['steep_deck']=review
    from . import bedrock,planning_station_preshow_world as checkers,timber_track_world as render
    from .planning_world_preview import _spawn_check,_verify_archive
    report['full_track']=dict(base['full_track']);report['full_track']['added_structure_records']=len(track)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='steep-track-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxel=root/'voxels.jsonl';all_blocks={**structures,**changes}
        with voxel.open('w') as stream:
            for row in terrain.values():stream.write(json.dumps(row)+'\n')
            for (x,h,y),m in sorted(all_blocks.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':m})+'\n')
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('World offset changed')
            report['spawn_validation']=_spawn_check(path,spawn)
            report['track_clearance_native']=checkers._native_air(path,offset,head)
            report['track_surfaces_native']=checkers._native_surfaces(path,offset,[{'source_cell_xy':[x,y],'walking_top_m':surface_top((x,h,y),m)} for (x,h,y),m in core.items()])
            atomic_json(path/'STEEP-DECK-CHANGE-RECEIPTS.json',review)
        world=bedrock.export_world(voxel,root,report,name='Wicker STEEP TRACK - solid steps no supports',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-steep-track.mcworld');report['world']['file']='wicker-steep-track.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'quality-report.json',report)
        atomic_json(root/'track-blocks.json',[{'source_xyz':list(k),'material':m} for k,m in sorted(track.items())])
        for name in ['track-samples.json','running-clearance-air.json']:shutil.copy2(base_directory/name,root/name)
        render.preview(root/'steep-track-preview.png',terrain,all_blocks,base['full_track']['controls'],track_only=True)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Solid timber steps on steep track</h1><a href="wicker-steep-track.mcworld">Download world</a><p>One-block rises use full blocks or paired half slabs. Corrected running heights, terrain and buildings retained. No supports added.</p><img style="max-width:100%" src="steep-track-preview.png">')
        shutil.move(root,output)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-directory',required=True);p.add_argument('--output',required=True);a=p.parse_args(argv)
    r=run(a.base_directory,a.output);print(json.dumps({'world_sha256':r['world']['sha256'],'thickened_cells':len(r['steep_deck']['thickened_deck_cells']),'withheld_cells':len(r['steep_deck']['withheld_deck_cells'])}))


if __name__=='__main__':main()
