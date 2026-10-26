"""Prepare the Mutiny Bay/Katanga original-plan handoff, without world placement."""
import argparse
import hashlib
import json
from pathlib import Path

from .generation_cycles import atomic_json
from .planning_area_pilot import _preview, validate as validate_pilot

PROFILE_PATH=Path(__file__).with_name('data')/'alton-mutiny-katanga-plan-review.json'
MAX_BYTES=24_000_000


def profile():
    value=json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
    if (value.get('version')!='mutiny-katanga-plan-review-v1'
            or value.get('world_placement_eligible') is not False or value.get('training_eligible') is not False
            or not 1<=len(value.get('sources',[]))<=16):
        raise ValueError('Bounded source-only area review required')
    excluded={r['sha256'] for r in value.get('excluded_sources',[])}
    seen=set()
    for row in value['sources']:
        if row['area_id'] not in ('mutiny-bay','katanga-canyon') or row['sha256'] in excluded or row['sha256'] in seen:
            raise ValueError('Distinct source in the reviewed physical area required')
        seen.add(row['sha256'])
        # Reuse the worker contract for paths, hashes, roles and same-resource fallback.
        request=pilot_request(row['area_id'],[row]);validate_pilot(request)
        if row['file']!=row['sha256']+'.pdf':raise ValueError('Hash-named source file required')
    rasters=value.get('raster_sources',[])
    if len(value['sources'])+len(rasters)>16:raise ValueError('Source-count budget exceeded')
    from .alton import official_request_url
    for row in rasters:
        if (row['area_id'] not in ('mutiny-bay','katanga-canyon') or row['sha256'] in seen|excluded
                or row['file']!=row['sha256']+'.jpg' or row['geographic_registration_verified'] is not False
                or len(row['pixel_dimensions'])!=2 or any(type(n) is not int or n<1 for n in row['pixel_dimensions'])
                or row['pixel_dimensions'][0]*row['pixel_dimensions'][1]>40_000_000):
            raise ValueError('Bounded original raster review required')
        official_request_url(row['url'],row.get('transport_url'),row['sha256']);seen.add(row['sha256'])
    return value


def pilot_request(area,rows):
    docs=[{k:v for k,v in r.items() if k not in ('area_id','coverage_notes')} for r in rows]
    return {'version':'planning-area-pilot-v1','area_id':area+'-expansion-source-review','source_directory':'files',
            'application_references':sorted({r['application_reference'] for r in docs}),
            'development_exposure':'previously_inspected','documents':docs}


def prepare(source_directory,output):
    """Verify available originals and explicitly retain unavailable plan references.

    A pack is not a completed reconstruction. Scans, proposed fencing and printed
    drawing coordinates receive no implicit placement or training authority.
    """
    import pymupdf
    p=profile();source=Path(source_directory).resolve();root=Path(output)
    root.mkdir(parents=True,exist_ok=False);(root/'files').mkdir();(root/'previews').mkdir()
    report={'version':'planning-expansion-source-pack-v1','sources':[],
        'world_placement_eligible':False,'training_eligible':False,'park_world_blocks_added':0,
        'excluded_sources':p['excluded_sources'],'historical_references':p['historical_references'],
        'related_applications':p['related_applications'],'raster_sources':[]}
    for row in p['sources']:
        path=source/row['file'];record={**row,'status':'source_unavailable','pages':[]};report['sources'].append(record)
        if not path.is_file():continue
        if path.stat().st_size>MAX_BYTES:
            record.update(status='source_withheld',reason='Original exceeds bounded PDF size');continue
        raw=path.read_bytes()
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            record.update(status='source_withheld',reason='Original source checksum mismatch');continue
        try:
            with pymupdf.open(stream=raw,filetype='pdf') as doc:
                selected=row.get('pages',list(range(1,len(doc)+1)))
                if len(doc)>64 or not 1<=len(selected)<=8 or any(not 1<=i<=len(doc) for i in selected):
                    raise ValueError('Source page budget exceeded; select pages explicitly')
                record['total_document_pages']=len(doc)
                for number in selected:
                    i=number-1;page=doc[i]
                    name=row['sha256']+'-page-'+str(i+1)+'.png'
                    _preview(page,root/'previews'/name,1200)
                    record['pages'].append({'page':i+1,'display_rect_points':list(page.rect),
                        'text':page.get_text()[:8000],'preview':'previews/'+name,
                        'has_text':bool(page.get_text().strip()),'geographic_registration_verified':False})
        except Exception as error:
            record.update(status='source_withheld',reason=str(error));continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Source changed during handoff')
        (root/'files'/row['file']).write_bytes(raw);record['status']='original_verified_and_included'
    for row in p.get('raster_sources',[]):
        from PIL import Image
        record={**row,'status':'source_unavailable'};report['raster_sources'].append(record)
        if row['file']!=row['sha256']+'.jpg':raise ValueError('Hash-named original JPEG required')
        path=source/row['file']
        if not path.is_file():continue
        if path.stat().st_size>MAX_BYTES:raise ValueError('Original raster byte budget exceeded')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:
            record.update(status='source_withheld',reason='Original raster checksum mismatch');continue
        with Image.open(path) as im:
            if list(im.size)!=row['pixel_dimensions'] or im.width*im.height>40_000_000:
                raise ValueError('Reviewed raster dimensions required')
            im.thumbnail((1200,1200));im.convert('RGB').save(root/'previews'/(row['sha256']+'.png'))
        (root/'files'/row['file']).write_bytes(raw)
        record.update(status='original_verified_and_included',preview='previews/'+row['sha256']+'.png')
    report['included_raster_originals']=sum(r['status']=='original_verified_and_included' for r in report['raster_sources'])
    report['withheld_raster_originals']=sum(r['status']=='source_withheld' for r in report['raster_sources'])
    report['unavailable_raster_originals']=sum(r['status']=='source_unavailable' for r in report['raster_sources'])
    for area in ('mutiny-bay','katanga-canyon'):
        rows=[r for r in p['sources'] if r['area_id']==area];request=pilot_request(area,rows);validate_pilot(request)
        atomic_json(root/(area+'-pilot.json'),request)
    report['included_originals']=sum(r['status']=='original_verified_and_included' for r in report['sources'])
    report['unavailable_originals']=sum(r['status']=='source_unavailable' for r in report['sources'])
    report['withheld_originals']=sum(r['status']=='source_withheld' for r in report['sources'])
    report['status']='source_handoff_with_open_reconstruction_blockers'
    atomic_json(root/'source-review.json',p)
    atomic_json(root/'manifest.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv);r=prepare(args.source_directory,args.output)
    print(json.dumps({k:r[k] for k in ('status','included_originals','included_raster_originals','unavailable_originals','withheld_originals')}))


if __name__=='__main__':main()
