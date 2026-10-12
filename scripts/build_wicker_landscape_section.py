"""Source-linked paving, planting beds and rock edges for the provisional section."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pyproj import datadir
from shapely.geometry import Point,box,mapping
from shapely.ops import transform,unary_union
from voxel_mapper.wickerman import inspect_drawings,BBOX
from voxel_mapper.wicker_registration import inspect_alignment,apply_candidate
from voxel_mapper.wicker_surfaces import extract_surfaces
from voxel_mapper.wicker_patterns import extract_pattern_surfaces
from voxel_mapper.wicker_details import legend_fills,straightened
from voxel_mapper.terrain import Terrain
from voxel_mapper.bedrock import export_world

PDF='1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d'
GRID='5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa'
LABEL_MATERIAL={'brick paving':'bricks','brick':'bricks','tarmac':'black_concrete','tar mac':'black_concrete',
                'gravel':'gravel','stone':'stone','stone paving':'stone',
                'concrete':'light_gray_concrete','concrete paving':'light_gray_concrete'}
# User's whole-polygon policy: specific finishes beat generic stone/concrete.
PAVING_PRECEDENCE=('bricks','black_concrete','gravel','light_gray_concrete','stone')


def recover_paving(vectors, annotations, scale):
    original,receipt=extract_surfaces(vectors,annotations,scale)
    candidates,flattened=extract_surfaces([straightened(v) for v in vectors],annotations,scale)
    known={r['vector_sequence'] for r in original}
    receipt['curve_recovery']={'method':'existing bounded 0.2 PDF-point cubic flattening; same legend/clip/hole checks',
                              'original_candidates':len(original),'recovered_sequences':[r['vector_sequence'] for r in candidates if r['vector_sequence'] not in known],
                              'withheld_fill_paths_after_flattening':flattened['withheld_fill_paths']}
    return candidates,receipt


def paving_spawn(rows, shop_columns):
    """Put a new review visit on a broad paving patch near the shop."""
    paving={(r['x'],r['z']):r for r in rows if r['kind']=='path' and r['material']!='dirt'}
    if not paving or not shop_columns:
        raise ValueError('Visible paving and shop columns required for review spawn')
    sx=sum(x for x,z in shop_columns)/len(shop_columns)
    sz=sum(z for x,z in shop_columns)/len(shop_columns)
    broad=[r for (x,z),r in paving.items()
           if all((x+dx,z+dz) in paving and abs(paving[x+dx,z+dz]['y']-r['y'])<=1
                  for dx in (-1,0,1) for dz in (-1,0,1))]
    if not broad:
        raise ValueError('No broad paving patch available for review spawn')
    row=min(broad,key=lambda r:((r['x']-sx)**2+(r['z']-sz)**2,r['x'],r['z']))
    return [row['x'],row['y']+2,row['z']]


def material_for_polygon(polygon,annotations,state):
    # Apply the requested whole-polygon rule to existing and proposed areas.
    # Brick wins a brick/tarmac tie so annotation ordering cannot change output.
    labels=[a['text'].strip().lower() for a in annotations
            if a['text'].strip().lower() in LABEL_MATERIAL and
            polygon.covers(Point((a['bbox'][0]+a['bbox'][2])/2,(a['bbox'][1]+a['bbox'][3])/2))]
    choices={LABEL_MATERIAL[label] for label in labels}
    for material in PAVING_PRECEDENCE:
        if material in choices:
            return material,'polygon material label; user precedence rule; Minecraft proxy',labels
    return 'stone','unconfirmed material; neutral review placeholder',labels


def overlay(features,terrain,bounds,protected):
    rows={};outcomes=[]
    boundary=box(*bounds)
    for index,feature in enumerate(features):
        polygon=feature['polygon'].intersection(boundary)
        generated=skipped=missing=0
        if polygon.is_empty:continue
        xmin,zmin,xmax,zmax=polygon.bounds
        for x in range(math.floor(xmin),math.ceil(xmax)):
            for z in range(math.floor(zmin),math.ceil(zmax)):
                if not polygon.covers(Point(x+.5,z+.5)):continue
                if (x,z) in protected:skipped+=1;continue
                ground=terrain.sample(x+.5,z+.5)
                if ground is None:missing+=1;continue
                base=math.floor(ground);kind=feature['kind']
                if kind=='paving':cells=[(base,feature['material'],'path')]
                elif kind=='planting_bed':cells=[(base,'dirt','path')]+([(base+1,'oak_leaves','structure')] if (x+z)%3==0 else [])
                else:cells=[(base+1,'stone','structure')]
                for y,material,rowkind in cells:
                    key=x,y,z
                    # Rock edges take precedence over planting; paving never
                    # changes a higher detail cell or a protected shop column.
                    rows[key]={'x':x,'y':y,'z':z,'kind':rowkind,'material':material,'feature':f'landscape/{index}',
                               'source_document':PDF,'material_status':feature['material_status']}
                    generated+=1
        outcomes.append({'feature':index,'kind':feature['kind'],'emitted_cells':generated,'protected_columns_skipped':skipped,'missing_terrain_columns':missing,
                         'material':feature['material'],'material_status':feature['material_status']})
    return list(rows.values()),outcomes


def build(base,pdf,osm,grid,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);base=Path(base)
    if (out/'park.mcworld').exists() or (out/'Wicker_V10_Paths_Ground_Audit.mcworld').exists():raise ValueError('Refusing to overwrite exported section')
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    if sha(pdf)!=PDF or sha(grid)!=GRID:raise ValueError('Pinned planning PDF and datum grid required')
    datadir.append_data_dir(str(Path(grid).resolve().parent))
    document={'applicationReference':'SMD/2017/0111','title':'373-95-7B Site Plan Proposed showing Woodland path','url':'http://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=176955',
              'role':'site-plan','sha256':PDF,'local_pdf':str(Path(pdf).resolve())}
    evidence=inspect_drawings([document],out)
    alignment=inspect_alignment(evidence,json.loads(Path(osm).read_text()),out,BBOX)
    if alignment['status']!='shop_track_alignment_hypothesis':raise ValueError('Planning alignment unavailable: '+alignment.get('reason',''))
    page=evidence['documents'][0]['pages'][0]
    with gzip.open(out/page['vector_file'],'rt') as stream:vectors=json.load(stream)
    scale=alignment['printed_scale_m_per_pdf_point'];annotations=page['annotations']
    paving,paving_receipt=recover_paving(vectors,annotations,scale)
    patterns,pattern_receipt=extract_pattern_surfaces(Path(pdf),annotations,scale,PDF)
    paving+=patterns
    features=[];failures=[]
    def project(x,y,z=None):
        xy=apply_candidate(list(zip(x,y)),alignment['candidate']);return xy[:,0],xy[:,1]
    for candidate in paving:
        material,status,labels=material_for_polygon(candidate['polygon'],annotations,candidate['state'])
        features.append({'polygon':transform(project,candidate['polygon']),'kind':'paving','material':material,'material_status':status,
                         'state':candidate['state'],'material_labels':labels,'vector_sequence':candidate.get('vector_sequence')})
    try:
        beds,bed_receipt=extract_pattern_surfaces(Path(pdf),annotations,scale,PDF,label_text='New mainly indigenous ground cover ')
        for candidate in beds:features.append({'polygon':transform(project,candidate['polygon']),'kind':'planting_bed','material':'dirt',
                                               'material_status':'legend-bound planted area; soil, foliage and heights are visual estimates'})
    except (ValueError,StopIteration) as error:failures.append({'kind':'planting_bed','reason':str(error)});bed_receipt=None
    try:
        rocks=legend_fills(vectors,annotations,'New rock edges to match existing.',scale)
        for candidate in rocks:features.append({'polygon':transform(project,candidate['polygon']),'kind':'rock_edge','material':'stone',
                                                'material_status':'legend-bound rock outline; stone type and one-block height are estimates','vector_index':candidate['vector_index']})
    except (ValueError,StopIteration) as error:failures.append({'kind':'rock_edge','reason':str(error)})
    report=json.loads((base/'quality-report.json').read_text());bounds=report['bounds_bng_m']
    boundary=box(*bounds)
    paving_union=unary_union([f['polygon'] for f in features if f['kind']=='paving'])
    ground_audit={'recovered_paving':[], 'grassed_areas':[], 'withheld_details':[]}
    recovered=set(paving_receipt['curve_recovery']['recovered_sequences'])
    for f in features:
        if f.get('vector_sequence') in recovered:
            ground_audit['recovered_paving'].append({'vector_sequence':f['vector_sequence'],
                'area_in_section_m2':f['polygon'].intersection(boundary).area,'material':f['material']})
    try:
        for candidate in legend_fills(vectors,annotations,'New and existing grassed areas to be ',scale):
            polygon=transform(project,candidate['polygon']).intersection(boundary)
            if not polygon.is_empty:
                ground_audit['grassed_areas'].append({'vector_index':candidate['vector_index'],
                    'area_in_section_m2':polygon.area,'paving_overlap_m2':polygon.intersection(paving_union).area,
                    'handling':'retain grass terrain; report overlap rather than erase mapped paving'})
    except (ValueError,StopIteration) as error:
        ground_audit['withheld_details'].append({'kind':'grassed_area','reason':str(error)})
    understorey=legend_fills(vectors,annotations,'New mainly indigenous understorey ',scale)
    if not understorey:
        ground_audit['withheld_details'].append({'kind':'understorey','reason':'No clipped plan fill of at least 2 square metres matches the legend; small hatch fragments do not establish an area boundary.'})
    ground_audit['unbound_grading_annotations']=[a['text'] for a in annotations if 'graded' in a['text'].lower() or 'lowered' in a['text'].lower()]
    (out/'ground-detail-audit.json').write_text(json.dumps(ground_audit,indent=2)+'\n')
    original=[json.loads(line) for line in (base/'voxels.jsonl').read_text().splitlines()]
    if len(original)>200000:raise ValueError('Bounded base section required')
    protected={(r['x'],r['z']) for r in original if r['kind']=='building'}
    settings=json.loads((base/'terrain-config.json').read_text())['terrain'];settings['path']=str((base/settings['path']).resolve())
    terrain=Terrain(settings,'EPSG:27700',{'ea-dtm':{}})
    try:rows,outcomes=overlay(features,terrain,bounds,protected)
    finally:terrain.close()
    with (out/'voxels.jsonl').open('w') as stream:
        for row in original+rows:stream.write(json.dumps(row)+'\n')
    result={'status':'provisional plan landscape section','input_sha256':{'base_rows':sha(base/'voxels.jsonl'),'pdf':PDF,'osm':sha(osm),'datum_grid':GRID},
            'alignment':alignment,'paving_receipt':paving_receipt,'pattern_receipt':pattern_receipt,'bed_receipt':bed_receipt,'ground_detail_audit':ground_audit,
            'overlay_cells':len(rows),'features_by_kind':dict(Counter(r['kind'] for r in outcomes if r['emitted_cells'])),
            'outcomes':outcomes,'failures':failures,'raised_planters':'No independently bound raised planter structures; planted beds only.',
            'accepted_controls':0,'accepted_checkpoints':0,'production_placement_eligible':False,
            'limitations':['2017 proposed geometry and older survey material labels are not current/as-built verification.',
                           'Unknown paving uses neutral stone as an explicitly unconfirmed review placeholder.',
                           'Path edges follow source polygons; heights follow sampled 2022 terrain, not accepted design levels.',
                           'Rock/planting block shapes, soil and foliage are estimated Minecraft proxies.']}
    (out/'landscape-review.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'landscape-features.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','geometry':mapping(f['polygon']),
         'properties':{k:v for k,v in f.items() if k!='polygon'}} for f in features],'crs':{'type':'name','properties':{'name':'EPSG:27700'}}},indent=2)+'\n')
    report.update(status='provisional_grounded_shop_and_landscape_review',landscape=result)
    report['limitations']+=result['limitations']
    report['spawn_local_xyz_m']=paving_spawn(rows,protected)
    report['world']=export_world(out/'voxels.jsonl',out,report,name='Wicker V10 PATHS — recovered curve — provisional',ground_depth=4)
    direct=out/'Wicker_V10_Paths_Ground_Audit.mcworld'
    (out/'park.mcworld').rename(direct)
    report['world']['file']=direct.name
    (out/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'README.txt').write_text('WICKER PATHS AND LANDSCAPE V10 — PROVISIONAL 1:1\nImport Wicker_V10_Paths_Ground_Audit.mcworld and open Wicker V10 PATHS. Recovered curved paving and whole-polygon material rule. Grounded shop and plaza spawn retained.\n'
        'Paving, planted beds and rock edges follow the 2017 proposal. Documented brick/tarmac/gravel classes use Minecraft proxies.\n'
        'Neutral stone paving means material unconfirmed. Planting soil/foliage and rock heights are estimates. No raised planter structures are claimed.\n'
        'Read landscape-review.json for feature-specific material status and unresolved alignment.\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','pdf','osm','grid','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();r=build(a.base,a.pdf,a.osm,a.grid,a.output)
    print(json.dumps({'overlay_cells':r['landscape']['overlay_cells'],'features_by_kind':r['landscape']['features_by_kind'],'world':r['world']}))
