"""Complete plan-centreline timber track-only prototype; no supports."""
import argparse
from collections import defaultdict
from concurrent.futures import CancelledError
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.geometry import LineString, Point, shape

from .generation_cycles import atomic_json, file_hash
from . import timber_track_world as timber

PROFILE = Path(__file__).with_name('data') / 'wicker-full-track-layout.json'


def complete_route(line, controls, profile):
    """Close the small drafting gap explicitly; don't silently extrapolate levels."""
    gap = math.dist(line.coords[0], line.coords[-1])
    if gap > profile['max_closure_gap_m']:
        raise ValueError('Plan endpoint gap exceeds the reviewed closure budget')
    route = LineString(list(line.coords) + [line.coords[0]]) if gap else line
    top = profile['station_display_top_m']
    estimated = [
        {'label':'estimated_station_start', 'station_m':0., 'height_m':top, 'estimated':True},
        {'label':'estimated_lift_start', 'station_m':profile['estimated_lift_start_station_m'], 'height_m':profile.get('estimated_lift_start_top_m',top), 'estimated':True},
        {'label':'estimated_station_return', 'station_m':line.length, 'height_m':top, 'estimated':True},
    ]
    if gap:
        estimated.append({'label':'estimated_gap_closure', 'station_m':route.length, 'height_m':top, 'estimated':True})
    estimated.extend(profile.get('crossing_display_controls',[]))
    result = sorted(controls + estimated, key=lambda r:r['station_m'])
    if any(a['station_m'] >= b['station_m'] for a,b in zip(result,result[1:])):
        raise ValueError('Height controls must have distinct ordered chainages')
    return route, result, {'original_source_length_m':line.length, 'drafting_gap_closed_m':gap,
                           'closure_is_estimated':True, 'estimated_controls':estimated}


def sample_route(route, controls, cancelled=lambda:False, *, clearance_blocks=3):
    """Keep separate vertical visits to the same XY column at track crossings."""
    visits=defaultdict(list); samples=[]
    for s in np.linspace(0, route.length, math.ceil(route.length/.2)+1):
        if cancelled():raise CancelledError('Full track sampling cancelled')
        p,t,n=timber.frame(route,float(s));top=round(2*timber.height_at(float(s),controls))/2
        cells=[]
        for off in [-1,0,1]:
            xy=tuple(map(math.floor,p+off*n));cells.append(xy)
            visits[xy].append({'station_m':float(s),'top':top,'wood':'spruce' if off==0 else 'oak'})
        samples.append({'station_m':float(s),'running_top_m':top,'cells_xy':cells,'normal':n.tolist()})
    groups={};core={};aliases=0
    for xy,entries in visits.items():
        entries.sort(key=lambda r:r['station_m']);parts=[]
        for r in entries:
            if not parts or r['station_m']-parts[-1][-1]['station_m']>4:
                parts.append([])
            parts[-1].append(r)
        # One physical visit straddles chainage zero in the closed circuit.
        if len(parts)>1 and parts[0][0]['station_m']+route.length-parts[-1][-1]['station_m']<=4:
            parts[0]=parts[-1]+parts[0];parts.pop()
        groups[xy]=[]
        for part in parts:
            top=max(r['top'] for r in part)
            wood='spruce' if any(r['wood']=='spruce' for r in part) else 'oak'
            key=(xy[0],math.ceil(top)-1,xy[1]);material=wood+('_slab' if top%1 else '_slab_top')
            if key in core:aliases+=1
            core[key]=material
            group={'top':top,'key':key,'stations':[r['station_m'] for r in part]}
            groups[xy].append(group)
    def group_at(xy,s):
        return min(groups[xy], key=lambda g:min(min(abs(v-s),route.length-abs(v-s)) for v in g['stations']))
    blocks=dict(core);head=set();centre_keys=[];rails={};doors={}
    for sample in samples:
        s=sample['station_m'];cells=sample['cells_xy'];centre=group_at(cells[1],s)
        x,b,y=centre['key'];centre_keys.append([x,b,y])
        head.update((x,h,y) for h in range(math.ceil(centre['top']),math.ceil(centre['top'])+clearance_blocks))
        for sign,xy in zip([-1,1],[cells[0],cells[2]]):
            g=group_at(xy,s);x,b,y=g['key'];rails[x,math.ceil(g['top']),y]='oak_fence'
            if int(s/2)==int((s-.2)/2):continue
            n=np.array(sample['normal']);d=np.array([sign*(1 if n[0]>0 else -1),0]) if abs(n[0])>=abs(n[1]) else np.array([0,sign*(1 if n[1]>0 else -1)])
            xx,yy=(np.array([x,y])+d).tolist()
            # Omit trapdoors against any slab at this level, including crossings.
            if (xx,b,yy) in core:continue
            facing='east' if d[0]>0 else 'west' if d[0]<0 else 'north' if d[1]>0 else 'south'
            doors[xx,b,yy]='oak_trapdoor_'+facing
    if set(core)&head:
        raise ValueError('Profile creates a deck collision in centre clearance: '+str([(k,[(round(min(g['stations']),1),round(max(g['stations']),1),g['top']) for g in groups[k[0],k[2]]]) for k in sorted(set(core)&head)]))
    for k,m in {**doors,**rails}.items():
        if k not in head and k not in blocks:blocks[k]=m
    connectivity=deck_connectivity(core,centre_keys)
    return blocks,core,head,samples,{'connectivity':connectivity,'vertical_visits_per_xy':{str(k):len(v) for k,v in groups.items() if len(v)>1},
        'deck_aliases':aliases,'centre_sample_keys':centre_keys,'supports_constructed':0}


def deck_connectivity(core,centre_keys):
    by_xy=defaultdict(list)
    tops={k:k[1]+(.5 if m.endswith('_slab') else 1) for k,m in core.items()}
    for k in core:by_xy[k[0],k[2]].append(k)
    if not core:raise ValueError('Empty full route deck')
    seen={next(iter(core))};pending=list(seen)
    while pending:
        k=pending.pop();x,h,y=k
        for xy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            for q in by_xy.get(xy,[]):
                if q not in seen and abs(tops[k]-tops[q])<=1.5:
                    seen.add(q);pending.append(q)
    if len(seen)!=len(core):raise ValueError('Full deck has disconnected slab cells')
    # Every source sample must have a slab and remain near the next sample;
    # comparing ordered samples avoids a false shortcut through an overpass.
    pairs=list(zip(centre_keys,centre_keys[1:]))
    if any(tuple(k) not in core for k in centre_keys):raise ValueError('Missing sampled centre slab')
    maximum=max((abs(tops[tuple(a)]-tops[tuple(b)]) for a,b in pairs),default=0)
    if maximum>1.5 or any(abs(a[0]-b[0])+abs(a[2]-b[2])>2 for a,b in pairs):
        raise ValueError('Ordered source samples have a track discontinuity')
    return {'all_deck_cells_cardinally_connected':True,'slab_cells_checked':len(core),
            'ordered_centre_samples_checked':len(centre_keys),'maximum_adjacent_sample_top_change_m':maximum}


def prepare_park(terrain,old,blocks,core,head,profile,base,*,samples=()):
    """Open declared covered track slots; preserve outdoor terrain and roofs."""
    terrain={k:dict(r) for k,r in terrain.items()};old=dict(old);cuts=[];removed=[]
    fit=profile.get('height_fit')
    covered_cells=set()
    if fit:
        for sample in samples:
            if any(z['start_m']<=sample['station_m']<=z['end_m'] for z in fit['covered_zones']):
                for x,y in sample['cells_xy']:
                    covered_cells.update((x+dx,y+dy) for dx in [-1,0,1] for dy in [-1,0,1])
    lowest={}
    for x,h,y in blocks:
        lowest[x,y]=min(lowest.get((x,y),h),h)
    for (x,y),h in lowest.items():
        if (x,y) not in terrain:raise ValueError('Full track leaves retained terrain')
        r=terrain[x,y]
        if r['y']>=h:
            depth=r['y']-(h-1)
            if fit and ((x,y) not in covered_cells or depth>fit['maximum_covered_cut_m']):raise ValueError('Outdoor terrain excavation forbidden: '+str((x,h,y,depth)))
            if depth>profile['max_terrain_cut_m']:raise ValueError('Track cut exceeds terrain budget')
            # Existing source guides remain the terrain material after lowering.
            cuts.append({'source_cell_xy':[x,y],'old_row':dict(r),'new_y':h-1,'cut_depth_m':depth})
            r['y']=h-1
    # Track can open provisional station/maintenance mesh on its own plan path.
    # Shop and other facades remain protected, even if a profile is changed.
    eligible=[shape(r['wall_geometry_nominal_local']).buffer(1.5) for r in base['parts']]
    eligible.append(shape(base['maintenance']['wall_geometry_nominal_local']).buffer(1.5))
    lower_geometry=shape(base['undercroft_geometry_nominal_local']).buffer(1) if fit and base.get('undercroft_geometry_nominal_local') else None
    protected={tuple(k) for o in base.get('shop_ground_fit',{}).get('openings',[]) for k in o.get('source_cells_xy',[])}
    queue=base.get('queue_deck')
    if queue:
        from .planning_station_preshow_world import grid_cells
        cells=grid_cells(shape(queue['source_polygon_nominal_local']))-{tuple(r['source_cell_xy']) for r in queue['preserved_geometry_aliases']}
        cells|={tuple(k) for k in queue['bounded_cardinal_connector_columns']}
        if (set(blocks)|head)&{(x,h,y) for x,y in cells for h in [183,184,185]}:
            raise ValueError('Track would obstruct retained queue surfaces or headroom')
    clearance=set(head)
    for x,b,y in core:clearance.update((x,h,y) for h in range(b,b+(fit['clearance_blocks']+1 if fit else 3)))
    for key in sorted((set(blocks)|clearance)&old.keys()):
        x,h,y=key
        if fit and h>=fit['protected_building_height_m'] and old[key]!='oak_fence':raise ValueError('Track would cut a protected roof: '+str((key,old[key])))
        allowed=any(g.covers(Point(x+.5,y+.5)) for g in eligible)
        if lower_geometry and lower_geometry.covers(Point(x+.5,y+.5)):
            if h==183:raise ValueError('Track would cut the preserved undercroft ceiling: '+str(key))
            if h<183:allowed=True
        if old[key]=='oak_fence':allowed=allowed or any(g.distance(Point(x+.5,y+.5))<=1.5 for g in eligible)
        if (x,y) in protected or not allowed:
            raise ValueError('Track would alter protected park geometry: '+str(key))
        removed.append({'source_xyz':list(key),'material':old.pop(key),'reason':'source-plan track passage through provisional building mesh or adjacent fence'})
    if len(removed)>profile['max_structure_removals']:raise ValueError('Building passage budget exceeded')
    return terrain,old,cuts,removed


def run(base_directory,markings_path,pdf_path,output,*,allow_provisional=False,cancelled=lambda:False):
    if not allow_provisional:raise ValueError('Conditional full-layout opt-in required')
    if cancelled():raise CancelledError('Full layout cancelled')
    base_directory=Path(base_directory);output=Path(output)
    if output.exists():raise ValueError('Fresh full track output required')
    profile=json.loads(PROFILE.read_text())
    for name,sha in profile['base_pins'].items():
        if file_hash(base_directory/name)!=sha:raise ValueError('Pinned pre-track park required')
    line,controls,_,source=timber.source_geometry(markings_path,pdf_path,profile,cancelled)
    for actual,expected in zip(controls,profile['controls']):
        if abs(actual['station_m']-expected['candidates'][0]['station_m'])>.05:
            raise ValueError('Source crossing branch changed')
    route,controls,closure=complete_route(line,controls,profile)
    base=json.loads((base_directory/'quality-report.json').read_text())
    rows=[json.loads(l) for l in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'}
    old={(r['x'],r['y'],r['z']-1):r['material'] for r in rows if r['kind']=='structure'}
    from . import track_elevation
    fitted,elevation_review=track_elevation.fit_profile(route,controls,terrain,profile['height_fit'],old)
    blocks,core,head,samples,topology=sample_route(route,fitted,cancelled,clearance_blocks=profile['height_fit']['clearance_blocks'])
    terrain,old,cuts,removed=prepare_park(terrain,old,blocks,core,head,profile,base,samples=samples)
    elevation_review['actual_deck_terrain_check']=track_elevation.check_terrain(terrain,blocks,core,samples,profile['height_fit'])
    if (set(blocks)|head)&old.keys():raise ValueError('Unresolved retained park collision')
    if any(h<=terrain[x,y]['y'] for x,h,y in blocks):raise ValueError('Track remains buried')
    if len(blocks)>profile['max_added_blocks']:raise ValueError('Full track block budget exceeded')
    report=dict(base)
    report.update(version='full-track-elevation-fit-v2',status='complete_track_only_prototype',implementation_sha256=file_hash(__file__),profile_sha256=file_hash(PROFILE),
        elevation_implementation_sha256=file_hash(track_elevation.__file__),source_replay_implementation_sha256=file_hash(timber.__file__),source_parent_world_sha256=base['world']['sha256'])
    report['full_track']={'route_length_m':route.length,'controls':controls,'source_review':source,'closure':closure,
        'elevation_review':elevation_review,'added_structure_records':len(blocks),'deck_columns':len(core),'supports_constructed':0,'terrain_cuts':cuts,
        'building_passage_removals':removed,'topology':topology,'banking_verified':False,'operable_ride':False,
        'limitations':['All 14 source HP/LP levels replayed; interpolated vertical profile is provisional, not surveyed.',profile['estimated_heights_note'],
            'A short drafting gap is explicitly bridged to close the layout.',
            'Outdoor terrain and building roofs restored from the pre-track park. Only declared covered track slots allow local bed cuts and lower wall/floor openings; no support frames are added.',
            'Oak/spruce slabs, oak fences and outward oak trapdoors follow user mockups; vanilla raster curves and integer fence placement approximate the reference.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='full-track-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxels=root/'voxels.jsonl'
        with voxels.open('w') as stream:
            for r in terrain.values():stream.write(json.dumps(r)+'\n')
            for (x,h,y),m in sorted({**old,**blocks}.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':m})+'\n')
        from . import bedrock,planning_station_preshow_world as checkers
        from .planning_world_preview import _spawn_check,_verify_archive
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('World offset changed')
            report['spawn_validation']=_spawn_check(path,spawn)
            report['track_clearance_native']=checkers._native_air(path,offset,head)
            report['track_surfaces_native']=checkers._native_surfaces(path,offset,[{'source_cell_xy':[x,y],'walking_top_m':h+(.5 if m.endswith('_slab') else 1)} for (x,h,y),m in core.items()])
            atomic_json(path/'FULL-TRACK-ASSUMPTIONS.json',report['full_track'])
        world=bedrock.export_world(voxels,root,report,name='Wicker TRACK HEIGHT FIX - roof restored no supports',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-full-track.mcworld');report['world']['file']='wicker-full-track.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'quality-report.json',report)
        atomic_json(root/'track-blocks.json',[{'source_xyz':list(k),'material':m} for k,m in sorted(blocks.items())])
        atomic_json(root/'track-samples.json',samples)
        atomic_json(root/'running-clearance-air.json',[list(k) for k in sorted(head)])
        timber.preview(root/'full-track-preview.png',terrain,blocks,controls,track_only=True)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Full Wicker Man track layout — no supports</h1><a href="wicker-full-track.mcworld">Download world</a><p>Complete mapped route in the reference slab/fence/trapdoor style. Outdoor track clears original terrain and banks. Preshow track is lowered beneath the retained upper floor; roofs are restored. Source/terrain height differences and covered bed cuts are recorded. No functional ride or support frames.</p><img style="max-width:100%" src="full-track-preview.png">')
        shutil.move(root,output)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['base-directory','markings-path','pdf-path','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--allow-provisional',action='store_true');a=p.parse_args(argv)
    r=run(a.base_directory,a.markings_path,a.pdf_path,a.output,allow_provisional=a.allow_provisional)
    print(json.dumps({'world_sha256':r['world']['sha256'],'route_m':r['full_track']['route_length_m'],'supports':0}))


if __name__=='__main__':main()
