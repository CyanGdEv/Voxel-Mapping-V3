"""Verified original raster drawings paired with explicit source-pixel reviews."""
import argparse
from collections import Counter
import copy
from html import escape
import json
from pathlib import Path
import shutil
import tempfile
from PIL import Image
from .building_spec import digest
from .generation_cycles import atomic_json
from . import study_component_learning as reader
from .study_dataset import _geometry,_pair,connected_groups,file_hash

VERSION='reviewed-raster-study-v1'


def build(review_path,source_directory,output,*,cancelled=lambda:False):
    review_path=Path(review_path);source_directory=Path(source_directory).resolve();output=Path(output)
    review,raw=reader._json(review_path,8_000_000)
    if not isinstance(review,dict) or review.get('version')!=VERSION:raise ValueError('Reviewed raster source contract required')
    sources=review.get('sources');annotations=review.get('records')
    if not isinstance(sources,list) or not 1<=len(sources)<=64 or not isinstance(annotations,list) or not 1<=len(annotations)<=reader.MAX_RECORDS:
        raise ValueError('Bounded raster source and review inventory required')
    if output.exists():raise ValueError('Fresh raster dataset output required')
    by_id={s['id']:s for s in sources}
    if len(by_id)!=len(sources):raise ValueError('Unique raster source identities required')
    if len({a['id'] for a in annotations})!=len(annotations):raise ValueError('Unique raster review identities required')
    output.parent.mkdir(parents=True,exist_ok=True);review_pin=reader._sha(raw)
    with tempfile.TemporaryDirectory(prefix='raster-study-',dir=output.parent) as tmp:
        stage=Path(tmp)/'result';stage.mkdir();(stage/'reviews').mkdir();shutil.copy2(review_path,stage/'reviews/source-review.json')
        rows=[];documents=[];total_bytes=0
        for key,source in by_id.items():
            reader._check(cancelled)
            path=reader._asset(source_directory,source['file']);pin=source.get('sha256')
            if not reader._hash(pin) or not path.is_file() or path.stat().st_size>20_000_000 or file_hash(path)!=pin:
                raise ValueError('Pinned original raster bytes required')
            if not isinstance(source.get('url'),str) or not source['url'].startswith('https://') or not source.get('rights_advisory'):
                raise ValueError('Source URL and scoped rights advisory required')
            if source.get('source_state') not in ['existing','proposed','unknown']:raise ValueError('Explicit source state required')
            with Image.open(path) as original:
                if original.format not in ['JPEG','PNG','TIFF'] or getattr(original,'n_frames',1)!=1 or original.width*original.height>8_000_000:
                    raise ValueError('Bounded single-frame original drawing raster required')
                if list(original.size)!=source.get('size_pixels'):raise ValueError('Source raster dimensions changed')
                rgb=original.convert('RGB');samples_pin=reader._sha(rgb.tobytes());image=rgb.convert('L');rgb.close()
            suffix=path.suffix.lower();name='sources/'+pin+suffix;dest=stage/name;dest.parent.mkdir(exist_ok=True);shutil.copy2(path,dest)
            if file_hash(dest)!=pin or file_hash(path)!=pin:raise ValueError('Original raster changed while copying')
            total_bytes+=path.stat().st_size
            if total_bytes>128_000_000:raise ValueError('Original raster byte budget exceeded')
            documents.append({'document_sha256':pin,'source_format':'original_raster','file':name,'url':source['url'],
                'rights_advisory':source['rights_advisory'],'survey_epoch':source.get('survey_epoch','unknown'),'sheet':source.get('sheet')})
            for index,annotation in enumerate(annotations):
                if annotation.get('source_id')!=key:continue
                reader._check(cancelled)
                if annotation.get('review_status')!='reviewed_source_trace':raise ValueError('Unreviewed or generated targets cannot enter raster supervision')
                for field in ['id','building_id','kind','review_basis','target_role']:
                    reader._identifier(annotation.get(field),field)
                uncertainty=annotation.get('trace_uncertainty_pixels')
                if type(uncertainty) not in [int,float] or not 0<uncertainty<=20:raise ValueError('Explicit bounded raster trace uncertainty required')
                geometry=_geometry(annotation['target_geometry']);crop,mask,transform=_pair(image,geometry)
                folder=stage/'examples'/digest(annotation['id'])[:24];folder.mkdir(parents=True)
                crop.save(folder/'input.png');mask.save(folder/'target-mask.png');crop.close();mask.close()
                target={'source_geometry':annotation['target_geometry'],'source_coordinate_frame':'original_raster_pixels_xy_down',
                    'trace_uncertainty_pixels':uncertainty,'crop_transform':transform,'supervision_scope':'Source drawing trace/class only; not metric or current as-built geometry.'}
                atomic_json(folder/'target.json',target)
                row={'id':annotation['id'],'building_id':annotation['building_id'],'kind':annotation['kind'],
                    'source':{'document_sha256':pin,'page':1,'coordinate_frame':'render_pixels','source_format':'original_raster',
                        'render_size_pixels':source['size_pixels'],'render_samples_sha256':samples_pin},
                    'target_geometry':copy.deepcopy(annotation['target_geometry']),'target_role':annotation['target_role'],
                    'review_refs':[{'path':'source-review.json','sha256':review_pin,'pointer':'/records/'+str(index)}],
                    'evidence_level':'reviewed_source_trace','assumptions':[annotation['review_basis'],'Trace uncertainty '+str(uncertainty)+' original pixels; no metric dimensions inferred.'],
                    'source_state':source['source_state'],'original_pdf_verified':False,'original_raster_verified':True,
                    'source_render_samples_sha256':samples_pin,'learning_eligible':True,'physical_geometry_verified':False,'world_placement_eligible':False,**transform}
                row['input_source']='Unmarked original raster drawing crop, grayscale and aspect-preserving resize; target overlay excluded.'
                for field,file in [('input','input.png'),('target_mask','target-mask.png'),('target','target.json')]:
                    row[field+'_file']=(folder/file).relative_to(stage).as_posix();row[field+'_sha256']=file_hash(folder/file)
                rows.append(row)
            image.close()
        if len(rows)!=len(annotations):raise ValueError('Every reviewed record must resolve to one original raster')
        groups=connected_groups(rows);owners={rid:g['group_id'] for g in groups for rid in g['record_ids']}
        for r in rows:r['group_id']=owners[r['id']];r['record_sha256']=digest(r)
        cards=''.join('<article><h3>'+escape(r['id'])+' — '+escape(r['kind'])+'</h3><img src="'+r['input_file']+'" alt="unmarked source crop"><img src="'+r['target_mask_file']+'" alt="separate reviewed target mask"></article>' for r in rows)
        (stage/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Reviewed raster source pairs</title><h1>Original drawing crops and reviewed targets</h1><p>Source-pixel geometry only. All views of one building remain one group. No accepted 3D reconstruction is implied.</p>'+cards,encoding='utf-8')
        manifest={'version':reader.DATASET_VERSION,'dataset_kind':'reviewed_original_raster_sources','records':rows,'groups':groups,
            'documents':documents,'review_sha256':review_pin,'summary':{'source_paired_examples':len(rows),'source_groups':len(groups),
                'original_rasters_verified':len(documents),'building_or_object_identities':len({r['building_id'] for r in rows}),
                'kinds':dict(sorted(Counter(r['kind'] for r in rows).items()))},
            'physical_geometry_verified':False,'world_placement_eligible':False,'model_weights_updated':False,
            'limitations':['Pixel traces are manually reviewed approximations, not original CAD vertices or metric geometry.',
                'The source survey epoch is retained; no claim about current as-built condition is made.',
                'Reference crops use reviewed bounds; automatic object discovery is not assessed.']}
        manifest['output_sha256']={f.relative_to(stage).as_posix():file_hash(f) for f in sorted(stage.rglob('*')) if f.is_file()}
        if sum(f.stat().st_size for f in stage.rglob('*') if f.is_file())>128_000_000:raise ValueError('Raster dataset byte budget exceeded')
        manifest['id']=digest(manifest);atomic_json(stage/'dataset.json',manifest);reader.read_dataset(stage,cancelled=cancelled)
        reader._check(cancelled);shutil.move(stage,output)
    return manifest


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review',required=True);p.add_argument('--sources',required=True);p.add_argument('--output',required=True)
    a=p.parse_args(argv);r=build(a.review,a.sources,a.output);print(json.dumps({'id':r['id'],**r['summary']}))

if __name__=='__main__':main()
