"""Reopen original PDFs, verify whole-object lineage and compare a fresh view pack."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape

from voxel_mapper.area_reconstruction import run as run_area
from voxel_mapper.building_raster_views import placements
from voxel_mapper.drawing_view_candidates import run as discover_views
from voxel_mapper.generation_cycles import file_hash,atomic_json
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(job,output):
    job=Path(job).resolve();configuration=json.loads(job.read_text())
    if len(configuration['areas'])!=1:raise ValueError('One bounded area required')
    area=configuration['areas'][0]['id'];work=(job.parent/configuration['work_directory']).resolve()/area
    entry=run_area(job,stage='extract')['areas'][area];report=entry['drawing_views'];root=Path(report['directory'])
    corpus=Corpus(work/'corpus')
    try:
        with tempfile.TemporaryDirectory(prefix='view-pack-fresh-replay-') as temporary:
            replay=discover_views(corpus,work/'drawing-geometry',Path(temporary)/'views',settings=report['contract']['options'])
            assert report['output_sha256']==replay['output_sha256']
        source_pages={}
        with (work/'drawing-geometry/geometry-candidates.jsonl').open() as stream:
            for line in stream:
                source=json.loads(line);key=(source['document_sha256'],source['page'])
                source_pages.setdefault(key,{})[source['id']]={'id':source['id'],
                    'document_sha256':key[0],'page':key[1],'kind':'native_vector',
                    'geometry':source['geometry'],'parent_record_sha256':digest(source)}
        data=json.loads((root/'view-candidates.json').read_text());views=[];counts=Counter();objects=Counter();checked=0
        for page in data['pages']:
            sha=page['document_sha256'];number=page['page'];path=corpus.root/'files'/(sha+'.pdf')
            assert file_hash(path)==sha
            sources=source_pages.get((sha,number),{})
            with pymupdf.open(path) as original:
                for source in placements(original[number-1],sha,number)['placements']:
                    sources[source['id']]={**source,'kind':'raster_placement'}
            assert set(sources)=={m['source_id'] for m in page['source_membership']}
            membership={m['source_id']:m for m in page['source_membership']}
            counts.update(m['status'] for m in membership.values())
            for m in membership.values():assert digest(sources[m['source_id']])==m['source_record_sha256']
            for view in page['views']:
                assert not view['view_scope_verified'] and not view['scale_application_verified'] and not view['world_placement_eligible']
                region=shape(view['geometry']);factor=view['nominal_metres_per_pdf_point']
                for source in view['whole_sources']:
                    raw=sources[source['id']];m=membership[source['id']]
                    assert m['status']=='one_whole_source_candidate' and m['contained_candidate_ids']==[view['id']]
                    assert digest(raw['geometry'])==digest(source['geometry_pdf_native'])
                    assert region.covers(shape(raw['geometry']))
                    if factor is not None:
                        a,b,d,e,x,y=view['native_to_nominal_local_affine'];det=a*e-b*d
                        inverse=[e/det,-b/det,-d/det,a/det,(b*y-e*x)/det,(d*x-a*y)/det]
                        recovered=affine_transform(shape(source['geometry_nominal_local']),inverse)
                        assert recovered.equals_exact(shape(raw['geometry']),1e-8)
                    objects[source['kind']]+=1;checked+=1
                receipt=json.loads((root/view['render']['receipt']).read_text())
                assert receipt['document_sha256']==sha and receipt['page']==number
                assert file_hash(root/view['render']['png'])==receipt['png_sha256']==view['render']['png_sha256']
                views.append({'document_sha256':sha,'page':number,'id':view['id'],'caption':view['caption_text'],
                    'printed_claim':view['printed_claim'],'whole_sources':len(view['whole_sources']),
                    'nominal_metres_per_pdf_point':factor,'png_sha256':receipt['png_sha256'],
                    'source_view_scope_verified':False})
    finally:corpus.close()
    result={'version':'automatic-drawing-view-audit-v1','status':'passed','job_sha256':file_hash(job),
        'pages':report['pages'],'view_candidates':report['views'],'nominal_scaled_views':report['nominal_scaled_views'],
        'whole_source_objects_checked':checked,'whole_source_kinds':dict(objects),'source_membership_counts':dict(counts),
        'views':views,'fresh_replay_artifact_hashes_identical':len(report['output_sha256']),
        'sheet_title_claims':[{'document_sha256':p['document_sha256'],'page':p['page'],
            'text':t['text'],'printed_claim':t['printed_claim'],'fragment_count':len(t.get('caption_fragments',[])),
            'view_scope_verified':False} for p in data['pages'] for t in p['source_sheet_titles']
            if t['glyph_screen']['status']=='raster_consistent_candidate'],
        'output_sha256':report['output_sha256'],'source_contract':report['contract'],
        'world_geometry_additions':0,'accepted_physical_components':0,'training_labels_generated':0,
        'limits':'Candidate review scopes and nominal source measurements; no physical building, mesh assembly or geographic placement is accepted.'}
    atomic_json(output,result);print(json.dumps({k:result[k] for k in ('status','pages','view_candidates','whole_source_objects_checked','fresh_replay_artifact_hashes_identical')}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();audit(args.job,args.output)
