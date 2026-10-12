"""Full park draft from retained inputs, with current Wicker Man preview."""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
import rasterio

from .cli import build
from .bedrock import export_world
from .survey import activate_retained_grid
from .wicker_reconstruction import emit_preview, verify_preview


def merge_raster(base_path, patch_path, destination):
    """Replace only finite cells of an aligned patch; retain explicit lineage."""
    with rasterio.open(base_path) as base,rasterio.open(patch_path) as patch:
        if (base.crs!=patch.crs or base.res!=(1.,1.) or patch.res!=(1.,1.)
                or base.transform.b or base.transform.d or patch.transform.b or patch.transform.d):
            raise ValueError('Matched north-up one-metre raster CRS/resolution required')
        col,row=(~base.transform)*(patch.bounds.left,patch.bounds.top)
        if abs(col-round(col))>1e-6 or abs(row-round(row))>1e-6:
            raise ValueError('Patch raster must align to base cells')
        col,row=round(col),round(row)
        if col<0 or row<0 or col+patch.width>base.width or row+patch.height>base.height:
            raise ValueError('Patch lies outside full-park raster')
        values=base.read(1);observations=patch.read(1,masked=True)
        valid=~np.ma.getmaskarray(observations)&np.isfinite(observations.data)
        region=values[row:row+patch.height,col:col+patch.width]
        region[valid]=observations.data[valid]
        with rasterio.open(destination,'w',**base.profile) as result:result.write(values,1)
    return {'base_sha256':hashlib.sha256(Path(base_path).read_bytes()).hexdigest(),
            'patch_sha256':hashlib.sha256(Path(patch_path).read_bytes()).hexdigest(),
            'merged_sha256':hashlib.sha256(Path(destination).read_bytes()).hexdigest(),
            'replaced_cells':int(valid.sum()),'patch_missing_cells_preserved_from_base':int((~valid).sum()),
            'method':'Aligned finite 2022 Wicker Man patch over retained EA composite; dates are not homogeneous'}


def generate_park(source, wicker, output, max_blocks=80000000):
    source,wicker,output=map(Path,(source,wicker,output))
    if output.exists():raise ValueError('Refusing to overwrite full park output')
    output.mkdir(parents=True)
    config=json.loads((source/'resolved-config.json').read_text())
    patch_config=json.loads((wicker/'resolved-config.json').read_text())
    config['location']='Alton Towers — full park draft'
    config['clip_to_boundary']=True
    if not config.get('boundary_geojson'):raise ValueError('Mapped park boundary required')
    activate_retained_grid(next(s for s in config['sources'] if s['id']=='ea-dtm'))
    lineage={}
    for kind in ('terrain','surface'):
        name='alton-'+kind+'-mosaic'
        destination=output/(name+'.tif')
        lineage[kind]=merge_raster(config[kind]['path'],patch_config[kind]['path'],destination)
        lineage[kind]['base_source']=next(s for s in config['sources'] if s['id']==config[kind]['source_id'])
        lineage[kind]['patch_source']=next(s for s in patch_config['sources'] if s['id']==patch_config[kind]['source_id'])
        config['sources'].append({'id':name,'url':'https://environment.data.gov.uk/',
                                  'license':'OGL-UK-3.0','attribution':'Contains Environment Agency information; retained composite with dated Wicker Man patch',
                                  'lineage':lineage[kind]})
        config[kind]={**config[kind],'path':str(destination.resolve()),'source_id':name}
    # Planning evidence contains source PDFs, drawing vectors and registered candidates.
    for path in wicker.iterdir():
        if path.is_file() and (path.name.startswith('wicker-man-') or path.name.endswith('-vectors.json.gz')):
            shutil.copy2(path,output/path.name)
    (output/'resolved-config.json').write_text(json.dumps(config,indent=2))
    collection=json.loads((source/'input.geojson').read_text())
    print('Building park boundary terrain and mapped features',flush=True)
    quality=build(config,collection,output)
    quality['full_park_generation']={'status':'draft','boundary':'retained mapped park polygon',
                                    'raster_lineage':lineage,'other_ride_geometry':'Not reconstructed; attraction extents are not physical tracks'}
    raw=json.loads((source/'osm-raw.json').read_text())
    print('Integrating current Wicker Man preview in park coordinate frame',flush=True)
    reconstruction=emit_preview(config,quality,raw,output)
    print('Exporting full park Bedrock world',quality['voxel_records'],'records',flush=True)
    world=export_world(output/'voxels.jsonl',output,quality,name='Alton Towers — FULL PARK DRAFT',
                       max_blocks=max_blocks,foundation_mode='chunk')
    reconstruction=verify_preview(output,world,reconstruction)
    quality.update(world=world,estimated_reconstruction=reconstruction)
    from .wickerman import acceptance_report
    evidence=json.loads((output/'wicker-man-planning-evidence.json').read_text())
    acceptance=acceptance_report(evidence,quality,output/'voxels.jsonl')
    acceptance['estimated_reconstruction']=reconstruction
    (output/'wicker-man-acceptance.json').write_text(json.dumps(acceptance,indent=2))
    (output/'bedrock-world'/'voxel-quality-report.json').write_text(json.dumps({k:v for k,v in quality.items() if k!='world'},indent=2))
    with zipfile.ZipFile(output/'park.mcworld','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((output/'bedrock-world').rglob('*')):
            if path.is_file() and path.name!='LOCK':archive.write(path,path.relative_to(output/'bedrock-world'))
    world['sha256']=hashlib.sha256((output/'park.mcworld').read_bytes()).hexdigest()
    (output/'quality-report.json').write_text(json.dumps(quality,indent=2))
    print(json.dumps({'world':world,'plaza_connection_check':reconstruction['plaza_connection_check']}),flush=True)
    return quality


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-output',required=True)
    parser.add_argument('--wicker-output',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--max-blocks',type=int,default=80000000)
    args=parser.parse_args()
    generate_park(args.source_output,args.wicker_output,args.output,args.max_blocks)


if __name__=='__main__':main()
