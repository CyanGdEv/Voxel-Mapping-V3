"""First 1:1 station/pre-show exterior review through the shop mesh pipeline."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.wicker_building_models import station_parts
from voxel_mapper.reconstruction.local_buildings import rotate_model
from voxel_mapper.shop_slabs import assemble
from voxel_mapper.shop_wall_details import decorate
from voxel_mapper.shop_foundations import level_pad
from voxel_mapper.shop_shell import opening_columns
from voxel_mapper.terrain import Terrain
from voxel_mapper.bedrock import export_world

PINS={'preshow':('253b79f214ab673f5ff868d0be5e9d306770ea29089f1dccf012e3a797f4668f',163938),
      'basement':('e442e7fa1ebc1b020cfa1a8254470d541ddb4d51c5448fa252deef5b43eb0a6c',163936),
      'floor':('08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3',163935),
      'roof':('6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047',163940)}


def placement(review,anchor):
    hypothesis=max(review['shop_only_drawing_correspondence_hypotheses'],
                   key=lambda h:h['plan_correspondence_checks']['station']['roof_vs_site_inner']['iou'])
    source=next(m for m in review['measurements'] if m['role']=='station_main_roof')['geometry']['coordinates'][0][:-1]
    target=hypothesis['native_geometries']['station_main_roof']['coordinates'][0][:-1]
    coefficients=np.linalg.lstsq(np.c_[source,np.ones(len(source))],target,rcond=None)[0]
    matrix=coefficients[:2].T
    if not np.allclose(matrix.T@matrix,np.eye(2),atol=1e-7) or np.linalg.det(matrix)<0:
        raise ValueError('Review placement requires a rigid rotation without scaling/reflection')
    shop=hypothesis['native_geometries']['shop_main_roof']['coordinates'][0][:-1]
    correction=np.asarray(anchor)-np.mean(shop,axis=0)
    return matrix,coefficients[2]+correction,hypothesis


def build(base,terrain_base,sources,retained,output,floor):
    if isinstance(floor,bool) or not math.isfinite(floor) or not 175<=floor<=200:
        raise ValueError('Explicit bounded provisional floor required')
    base=Path(base);terrain_base=Path(terrain_base);sources=Path(sources);retained=Path(retained)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if (out/'quality-report.json').exists():raise ValueError('Refusing to overwrite completed review')
    receipts=[]
    for role,(sha,attachment) in PINS.items():
        path=(sources if role in ('preshow','basement') else retained)/(sha+'.pdf')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch: '+role)
        receipts.append({'id':'wicker-'+role,'role':role,'sha256':sha,
                         'url':f'http://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName={attachment}',
                         'source_state':'2016 proposed revised P1; not as-built verification'})
    review_path=Path(__file__).resolve().parents[1]/'evidence/wicker-architectural-outline-review.json'
    review=json.loads(review_path.read_text());parts=station_parts(review)
    report=json.loads((base/'quality-report.json').read_text())
    matrix,translation,hypothesis=placement(review,report['shop_hypothesis']['anchor_bng_m'])
    angle=math.degrees(math.atan2(matrix[1,0],matrix[0,0]))
    settings=json.loads((terrain_base/'terrain-config.json').read_text())['terrain']
    settings['path']=str((terrain_base/settings['path']).resolve())
    terrain=Terrain(settings,'EPSG:27700',{'ea-dtm':{}})
    original=[json.loads(line) for line in (base/'voxels.jsonl').read_text().splitlines()]
    shop={(r['x'],r['y'],r['z']) for r in original if r['kind']=='building'}
    added={};audits=[];bounds=report['bounds_bng_m'];overlaps=0;apertures=set()
    try:
        for part in sorted(parts,key=lambda p:p['model']['dimensions']['eave_m']):
            model=part['model'];rotated=rotate_model(model,angle)
            cells,shell=assemble(rotated);cells,detail=decorate(rotated,cells)
            anchor=matrix@np.asarray(part['source_plan_centre_m'])+translation
            for (x,z),head in opening_columns(rotated['opening_base_segments'],1).items():
                apertures.update((x+round(anchor[0]),y+round(floor),z+round(anchor[1])) for y in range(head))
            foundations,grounding=level_pad(rotated,cells,anchor,floor,terrain.sample)
            # The model palette is shared with the normal local-building adapter.
            for point,material in list(cells.items()):
                if material.endswith('_trapdoor_north'):cells[point]=material.removesuffix('_north')+'_south'
                elif material.endswith('_trapdoor_south'):cells[point]=material.removesuffix('_south')+'_north'
            for (x,y,z),material in {**foundations,**cells}.items():
                point=(x+round(anchor[0]),y+round(floor),z+round(anchor[1]))
                wx,wy,wz=point
                if not(bounds[0]<=wx<bounds[2] and bounds[1]<=wz<bounds[3]):raise ValueError('New building extends outside section')
                if point in shop:raise ValueError('New building collides with retained shop')
                if point in added:overlaps+=1
                # Taller component wins shared roof/wall joins when emitted last.
                added[point]={'x':wx,'y':wy,'z':wz,'kind':'building','material':material,
                              'feature':'station-review/'+part['id'],'material_status':'planning class; illustrative Minecraft proxy'}
            (out/(part['id']+'-model.json')).write_text(json.dumps(model,indent=2)+'\n')
            audits.append({'id':part['id'],'anchor_bng_m':anchor.tolist(),'rotation_degrees':angle,
                           'provisional_base_m':floor,'source_outline':part['source_outline'],
                           'printed_levels':part['printed_levels'],'height_basis':part['height_basis'],
                           'dimensions':model['dimensions'],'shell':shell,'wall_detail':detail,'grounding':grounding})
    finally:terrain.close()
    # Joining independent source meshes may put a neighbouring wall or detail
    # in another component's aperture. Preserve all declared compound openings.
    removed_aperture_cells=sum(p in added for p in apertures)
    for point in apertures:added.pop(point,None)
    columns={(x,z) for x,y,z in added}
    kept=[r for r in original if not (r.get('feature','').startswith('landscape/') and (r['x'],r['z']) in columns)]
    with (out/'voxels.jsonl').open('w') as stream:
        for row in kept+list(added.values()):stream.write(json.dumps(row)+'\n')
    result={'status':'first station/pre-show exterior reconstruction review','parts':audits,
            'adapter':'same rotate_model / shop_slabs.assemble / shop_wall_details.decorate / shop_foundations.level_pad pipeline',
            'source_pdfs':receipts,'outline_review_sha256':hashlib.sha256(review_path.read_bytes()).hexdigest(),
            'base_rows_sha256':hashlib.sha256((base/'voxels.jsonl').read_bytes()).hexdigest(),
            'building_cells':len(added),'material_counts':dict(Counter(r['material'] for r in added.values())),
            'shared_component_cells':overlaps,'landscape_cells_covered_by_buildings':len(original)-len(kept),
            'compound_aperture_cells_cleared':removed_aperture_cells,'declared_aperture_air_cells':len(apertures),
            'registration_status':'drawing correspondence hypothesis reanchored to provisional shop; not independently accepted',
            'drawing_station_iou':hypothesis['plan_correspondence_checks']['station']['roof_vs_site_inner']['iou'],
            'accepted_controls':0,'accepted_checkpoints':0,'production_placement_eligible':False,
            'limitations':['Exterior first review: rounded eave/ridge heights and aperture sizes require exact cross-sheet binding.',
                           'The provisional floor is chosen explicitly for terrain clearance, not taken as the printed passenger/platform level.',
                           'Inspection 181.25 and undercroft 178.00 are retained as separate levels; basement, excavation, bunding and interior circulation are not yet reconstructed.',
                           'Thatch-effect oak slabs, timber fences/trapdoors and stone foundations are illustrative block proxies.',
                           'Multi-part interfaces are independently rasterized; exact doorway/circulation joins still require review.']}
    (out/'station-review.json').write_text(json.dumps(result,indent=2)+'\n')
    report['station_review']=result;report['sources']+=receipts;report['limitations']+=result['limitations']
    report['status']='provisional_shop_paths_station_preshow_review'
    report['world']=export_world(out/'voxels.jsonl',out,report,name='Wicker V11 STATION and PRESHOW — exterior review',ground_depth=4)
    name='Wicker_V11_Station_Preshow.mcworld';(out/'park.mcworld').rename(out/name);report['world']['file']=name
    (out/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('base','terrain-base','sources','retained','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--floor',required=True,type=float)
    a=parser.parse_args();r=build(a.base,a.terrain_base,a.sources,a.retained,a.output,a.floor)
    print(json.dumps({'world':r['world'],'building_cells':r['station_review']['building_cells']}))
