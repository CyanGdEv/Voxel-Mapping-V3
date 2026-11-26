"""Prepare, inspect and propose registered surface repairs across two runtimes.

prepare: GIS environment. inspect: isolated Bedrock environment. plan: standard
Python. Proposals still require a hash-bound scoped review before block writes.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

from voxel_mapper.ground_surface import assess_lawn_column


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_fresh(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False)


def prepare(args):
    import numpy as np
    from PIL import Image
    from affine import Affine
    from scipy.ndimage import binary_erosion
    import rasterio
    reg=json.loads(args.registration.read_text())
    grid=Affine(*reg['world_grid_edge_to_bng_affine'])
    if reg['blocks_per_metre']!=1:raise ValueError('Only 1m native grids supported')
    with zipfile.ZipFile(args.dataset) as z:
        m=json.loads(z.read('manifest.json'));r=next(r for r in m['samples'] if r['sample_id']==args.sample)
        if r['georef']['crs']!=reg['horizontal_crs']:raise ValueError('Align source CRS before planning')
        if m.get('label_map',{}).get('1')!='grass_unspecified':raise ValueError('Canonical reviewed grass class required')
        tf=Affine(*r['georef']['transform']);a=np.asarray(Image.open(io.BytesIO(z.read(r['labels']))))
    mapping=~grid*tf
    if not np.allclose([mapping.a,mapping.b,mapping.d,mapping.e],[1,0,0,1],atol=1e-8):
        raise ValueError('Use an already aligned 1m label grid')
    include_paving=getattr(args,'include_paving',False)
    if include_paving and m.get('label_map',{}).get('9')!='paving_unspecified':raise ValueError('Canonical generic paving class required')
    mask=(a==1)|((a==9)&include_paving)
    safe=binary_erosion(a==1,iterations=2)
    if include_paving:safe |= binary_erosion(a==9,iterations=2)
    rows=[]
    for y,x in zip(*np.where(mask)):
        wx,wz=mapping*(int(x)+.5,int(y)+.5)
        if not np.allclose([wx%1,wz%1],[.5,.5],atol=1e-7):raise ValueError('Native pixel centres differ')
        e,n=tf*(int(x)+.5,int(y)+.5)
        rows.append({'x':int(math.floor(wx)),'z':int(math.floor(wz)), 'easting':e,'northing':n,
                     'label':int(a[y,x]),'safe_interior':bool(safe[y,x])})
    for role,path in [('dtm',args.dtm),('dsm',args.dsm)]:
        with rasterio.open(path) as source:
            if source.crs.to_string()!=reg['horizontal_crs']:raise ValueError('Raster CRS mismatch')
            if not source.crs.is_projected or abs(source.crs.linear_units_factor[1]-1)>1e-8:
                raise ValueError('Metre projected evidence required')
            raster_grid=~grid*source.transform
            if not np.allclose([raster_grid.a,raster_grid.b,raster_grid.d,raster_grid.e],[1,0,0,1],atol=1e-8):
                raise ValueError('Roof absence requires aligned 1m surface/terrain evidence')
            for cell,value in zip(rows,source.sample([(c['easting'],c['northing']) for c in rows],masked=True)):
                cell[role]=None if np.ma.is_masked(value[0]) or not math.isfinite(float(value[0])) else float(value[0])
    return {'schema':'registered-surface-candidates-v1','accepted_for_block_edits':False,
      'surface_offset_m':reg['vertical_ground_surface']['rounded_surface_offset_m'],
      'registration_sha256':sha(args.registration),'dataset_sha256':sha(args.dataset),
      'source_sample':args.sample,'paving_roof_only':include_paving,'dtm_sha256':sha(args.dtm),'dsm_sha256':sha(args.dsm),
      'label_counts':{str(k):int(np.count_nonzero(a==k)) for k in np.unique(a)},'cells':rows}


def merge_area_requests(requests):
    """One proposal location per native cell; disagreements stay unknown."""
    if not requests:raise ValueError('No registered samples selected')
    base=dict(requests[0]);merged={};sources=[]
    identity=('surface_offset_m','registration_sha256','dataset_sha256','dtm_sha256','dsm_sha256','paving_roof_only')
    observations=0
    for request in requests:
        if any(request[k]!=base[k] for k in identity):raise ValueError('Area evidence identity mismatch')
        sources.append(request['source_sample'])
        for c in request['cells']:
            observations+=1;key=(c['x'],c['z']);group=request.get('source_split_group')
            if key not in merged:
                merged[key]={**c,'source_sample_count':1,'source_groups':[group] if group else []}
                continue
            old=merged[key]
            if any(old[k]!=c[k] for k in ('easting','northing','dtm','dsm')):
                raise ValueError('Overlapping cells disagree on alignment or heights')
            old['source_sample_count']+=1
            if group and group not in old['source_groups']:old['source_groups'].append(group)
            if old['label']!=c['label']:
                old['label']=255;old['safe_interior']=False
            elif old['label']!=255:
                old['safe_interior']=old['safe_interior'] or c['safe_interior']
    cells=[merged[k] for k in sorted(merged)]
    base.pop('source_split_group',None)
    for c in cells:c['source_groups'].sort()
    base.update(source_sample='merged_registered_areas',source_samples=sorted(sources),cells=cells,
       accepted_for_block_edits=False,
       source_split_groups=sorted({r['source_split_group'] for r in requests if r.get('source_split_group')}),
       source_label_observations=observations,unique_native_cells=len(cells),
       overlapping_observations_deduplicated=observations-len(cells),
       conflicting_cells_ignored=sum(c['label']==255 for c in cells),
       label_counts={str(k):sum(c['label']==k for c in cells) for k in sorted({c['label'] for c in cells})})
    return base


def prepare_area(args):
    """Reuse single-chip validation/erosion and deduplicate geographic overlap."""
    with zipfile.ZipFile(args.dataset) as z:manifest=json.loads(z.read('manifest.json'))
    groups=set(args.group or [])
    selected=[r for r in manifest['samples'] if not groups or r.get('split_group') in groups]
    if not selected or len(selected)>256:raise ValueError('Select 1..256 registered samples')
    if groups-{r.get('split_group') for r in selected}:raise ValueError('Requested group absent')
    requests=[]
    for record in selected:
        options=argparse.Namespace(**vars(args));options.sample=record['sample_id']
        request=prepare(options);request['source_split_group']=record.get('split_group')
        requests.append(request)
    return merge_area_requests(requests)


def inspect(args):
    from voxel_mapper.bedrock_patch import inspect_columns
    request=json.loads(args.requests.read_text())
    return {'schema':'native-surface-observations-v1','requests_sha256':sha(args.requests),
      'baseline_sha256':sha(args.baseline),'surface_offset_m':request['surface_offset_m'],
      'paving_roof_only':request.get('paving_roof_only',False),
      'cells':inspect_columns(args.baseline,request['cells'],request['surface_offset_m'])}


def propose(args):
    observations=json.loads(args.observations.read_text());points={};point_path=getattr(args,'cell_returns',None)
    if point_path:
        report=json.loads(point_path.read_text())
        if report.get('schema')!='classified-cell-return-evidence-v1' or report.get('requests_sha256')!=observations['requests_sha256']:
            raise ValueError('Classified returns belong to different registered cells')
        points={(c['x'],c['z']):c for c in report['cells']}
        if len(points)!=len(report['cells']) or set(points)!={(c['x'],c['z']) for c in observations['cells']}:
            raise ValueError('Classified return cell membership mismatch')
    return {'schema':'surface-repair-proposals-v1','accepted_for_block_edits':False,
      'observations_sha256':sha(args.observations),'requests_sha256':observations['requests_sha256'],
      'point_evidence_sha256':sha(point_path) if point_path else None,
      'baseline_sha256':observations['baseline_sha256'],'cells':[
       {'x':c['x'],'z':c['z'],**({'label':c['label']} if observations.get('paving_roof_only',False) else {}),
        **assess_lawn_column(c,surface_offset_m=observations['surface_offset_m'],
           allow_paving_roof_only=observations.get('paving_roof_only',False),point_evidence=points.get((c['x'],c['z'])))}
       for c in observations['cells']]}


def accept(args):
    proposals=json.loads(args.proposals.read_text());review=json.loads(args.review.read_text())
    if review.get('proposals_sha256')!=sha(args.proposals) or review.get('accepted_for_scoped_preview') is not True:
        raise ValueError('Hash-bound scoped review required')
    accepted={tuple(p) for p in review['accepted_columns']}
    available={(c['x'],c['z']) for c in proposals['cells'] if c['status']=='candidate'}
    if not accepted or not accepted<=available:raise ValueError('Review includes unqualified cells')
    edits=[];heights=[]
    for c in proposals['cells']:
        if (c['x'],c['z']) not in accepted:continue
        edits.extend({**e,'accepted':True,'evidence_sha256':sha(args.review)} for e in c['edits'])
        heights.append(c['height_update'])
    plan={'schema':'bedrock-scoped-patch-v1','baseline_sha256':proposals['baseline_sha256'],
          'registration':{'accepted_for_this_patch':True,'evidence_sha256':sha(args.review)},
          'edits':edits,'height_updates':heights}
    from voxel_mapper.bedrock_patch import validate_plan
    validate_plan(plan,proposals['baseline_sha256'])
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True)
    for mode,names in [('prepare',['dataset','registration','dtm','dsm']),('prepare_area',['dataset','registration','dtm','dsm']),('inspect',['requests','baseline']),
                       ('propose',['observations']),('accept',['proposals','review'])]:
        p=sub.add_parser(mode)
        for name in names:p.add_argument('--'+name,type=Path,required=True)
        if mode in ('prepare','prepare_area'):
            if mode=='prepare':p.add_argument('--sample',required=True)
            else:p.add_argument('--group',action='append',help='Repeat to select source groups; default all')
            p.add_argument('--include-paving',action='store_true',help='Also propose roof-only corrections over reviewed generic paving')
        if mode=='propose':p.add_argument('--cell-returns',type=Path,help='Hash-bound raw classified-cell evidence; original raster values remain unchanged')
        p.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();result=globals()[a.mode](a);write_fresh(a.output,result)
    print(json.dumps({'output':str(a.output),'schema':result['schema']}))


if __name__=='__main__':main()
