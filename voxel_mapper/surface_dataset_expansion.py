"""Source-bound surface additions with whole-park evaluation reservations."""
import argparse
import json
import re
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
from scipy import ndimage

from . import layered_surface_benchmark as data, connected_surfaces as surfaces
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash
from .mapping_layers import _asset, _read

VERSION='surface-expansion-additions-v1'


def literal_masks(annotation,size):
    """Unknown ground and hidden canopy remain separate from observed labels."""
    if not isinstance(annotation.get('ground_regions'),list) or not 1<=len(annotation['ground_regions'])<=128:
        raise ValueError('Bounded literal surface regions required')
    raw=np.zeros((4,size[1],size[0]),bool);explicit_unknown=np.zeros(raw.shape[1:],bool)
    for region in annotation['ground_regions']:
        mask=surfaces.raster(data._polygon(region,size),size)
        value=data.GROUND[region['label']]
        if value==255:explicit_unknown|=mask
        else:raw[value]|=mask
    ground=np.full(raw.shape[1:],255,np.uint8)
    unambiguous=raw.sum(axis=0)==1
    for value,mask in enumerate(raw):
        # Sparse polygon margins are source-uncertain. Dense partitions below
        # explicitly retain known class interfaces where visible evidence exists.
        ground[ndimage.binary_erosion(mask,iterations=1)&unambiguous]=value
    ground[explicit_unknown]=255
    item={'dense_windows':annotation.get('dense_windows',[]),'canopy':annotation.get('canopy',[])}
    g,c,windows=data.targets(item,size,size,[[1,0,0],[0,1,0]],ground,np.zeros_like(ground))
    return g,c,windows


def build(parent,request_file,output):
    parent=Path(parent).resolve();request_file=Path(request_file).resolve();out=Path(output)
    old=data.validate(parent);request=_read(request_file)
    if request.get('version')!=VERSION or request.get('parent_dataset_id')!=old['id'] or request.get('independent_human_review') is not False:
        raise ValueError('Versioned parent-bound provisional additions required')
    additions=request.get('records',[]);reserved=request.get('reserved_evaluation_site_ids',[])
    if not 1<=len(additions)<=8-len(old['records']) or not isinstance(reserved,list) or len(reserved)!=1:
        raise ValueError('Bounded additions and one prospectively reserved park required')
    if set(reserved)&{r['site_id'] for r in old['records']}:
        raise ValueError('Previously fitted parks cannot become a new reserved park')
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}',r.get(k,'')) for r in additions for k in ('id','site_id')):
        raise ValueError('Bounded local source identities required')
    ids=[r['id'] for r in old['records']]+[r['id'] for r in additions]
    if len(ids)!=len(set(ids)):
        raise ValueError('Distinct source record identities required')
    if out.exists():raise ValueError('Fresh expanded dataset required')
    out.mkdir(parents=True);records=[]
    for original in old['records']:
        row=dict(original);row['evaluation_only']=False
        for key in ('image','receipt','ground','canopy','dense_windows','inferred'):
            src=parent/original[key+'_file'];dest=out/original[key+'_file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        records.append(row)
    for entry in additions:
        image=_asset(request_file.parent,entry,'image_file');receipt_path=_asset(request_file.parent,entry,'receipt_file');annotation_path=_asset(request_file.parent,entry,'annotation_file')
        receipt=_read(receipt_path);annotation=_read(annotation_path)
        with Image.open(image) as im:
            size=im.size
            if im.width*im.height>1048576 or min(size)<128 or size!=(receipt['width'],receipt['height']) or file_hash(image)!=receipt['image_sha256']:
                raise ValueError('Bounded original aerial image and receipt required')
        if annotation.get('version')!='literal-park-surface-annotations-v1' or annotation.get('site_id')!=entry['site_id'] or annotation.get('source_image_sha256')!=receipt['image_sha256'] or annotation.get('image_size')!=list(size) or annotation.get('independent_human_review') is not False:
            raise ValueError('Annotations must bind the unmarked source image')
        ground,canopy,windows=literal_masks(annotation,size);folder=out/entry['id'];folder.mkdir()
        row={'id':entry['id'],'site_id':entry['site_id'],'source_original_sha256':file_hash(image),
             'evaluation_only':entry['site_id'] in reserved,'annotation_sha256':file_hash(annotation_path)}
        for key,src,name in [('image',image,'clean.bin'),('receipt',receipt_path,'receipt.json')]:
            target=folder/name;shutil.copy2(src,target);row[key+'_file']=str(target.relative_to(out));row[key+'_sha256']=file_hash(target)
        for key,array in [('ground',ground),('canopy',canopy),('dense_windows',windows.astype(np.uint8)*255),('inferred',np.zeros_like(ground))]:
            target=folder/(key+'.png');Image.fromarray(array).save(target);row[key+'_file']=str(target.relative_to(out));row[key+'_sha256']=file_hash(target)
        shutil.copy2(annotation_path,folder/'annotations.json')
        row['ground_counts']={name:int((ground==value).sum()) for name,value in data.GROUND.items()}
        row['canopy_counts']={name:int((canopy==value).sum()) for name,value in data.CANOPY.items()}
        if any(row['ground_counts'][name]==0 for name in ('paving','building_structure','grass_island','water')):
            raise ValueError('Every added source must supply visible examples of all four ground classes')
        records.append(row)
    if not set(reserved)<={r['site_id'] for r in records} or len({r['image_sha256'] for r in records})!=len(records):
        raise ValueError('Unique source images and reserved park coverage required')
    recipe={'version':VERSION,'parent_recipe':_read(parent/'recipe.json'),'request':request,
            'annotation_sha256':{r['id']:r['annotation_sha256'] for r in records if 'annotation_sha256' in r}}
    atomic_json(out/'recipe.json',recipe)
    manifest={'version':data.VERSION,'source_dataset_id':old['id'],'parent_dataset_id':old['id'],
        'recipe_sha256':file_hash(out/'recipe.json'),'ground_labels':data.GROUND,'canopy_labels':data.CANOPY,
        'records':records,'reserved_evaluation_site_ids':reserved,'independent_human_review':False,
        'production_eligible':False,'hidden_ground_used_as_observed_truth':False}
    manifest['id']=digest(manifest);atomic_json(out/'dataset.json',manifest);data.validate(out);return manifest


def training_records(manifest,excluded_sites=()):
    reserved=set(manifest.get('reserved_evaluation_site_ids',[]))
    return [r for r in manifest['records'] if not r.get('evaluation_only',False) and r['site_id'] not in reserved|set(excluded_sites)]


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',required=True);p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(build(a.parent,a.request,a.output)))
