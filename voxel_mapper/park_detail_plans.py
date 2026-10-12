"""Extract bounded path-detail candidates from provisionally aligned plan pages."""
import argparse
import hashlib
import json
from pathlib import Path

from .park_details import detail_semantics,labelled_faces
from .park_paving_plans import cached_paving_faces,labels_from_page,surface_boundaries


def recover_candidates(cache,paving_audit,output):
    import pymupdf
    cache,output=map(Path,(cache,output));output.mkdir(parents=True,exist_ok=True)
    audit=json.loads(Path(paving_audit).read_text());pages=[];features=[];withheld=[];seen=set()
    for document in audit['documents']:
        if 'alignment' not in document:continue
        digest=document['document_id'];page_index=document.get('page',1)-1
        if (digest,page_index) in seen:continue
        seen.add((digest,page_index))
        if len(seen)>160:raise ValueError('Detail page inspection budget exceeded')
        path=cache/'files'/(digest+'.pdf')
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Detail source PDF hash mismatch')
        scale=document['alignment']['candidate']['scale_m_per_pdf_point']
        with pymupdf.open(path) as pdf:
            if not 0<=page_index<len(pdf):raise ValueError('Detail page does not exist')
            page=pdf[page_index];labels=labels_from_page(page)
            if not any(detail_semantics(label['text']) for label in labels):continue
            key=hashlib.sha256(f'{digest}/{page_index}/{scale}/path-details-grey-solid-v1'.encode()).hexdigest()
            faces=cached_paving_faces(output/(key+'-faces.json.gz'),lambda:surface_boundaries(page.get_drawings(extended=True),scale,min_area=.15,max_area=1500))
        candidates,failures=labelled_faces(faces['polygons'],labels,scale)
        for candidate in candidates:
            index=candidate['face_index']
            features.append({**candidate,'id':f'planning-detail/{digest[:12]}/{page_index+1}/{index}',
                             'document_id':digest,'page':page_index+1,'application':document['application'],
                             'source_url':document['source_url'],'alignment':document['alignment'],
                             'registration_verified':False,'as_built_verified':False,
                             'status':'candidate_requires_native_drawing_review','geometry_emitted':False})
        withheld.extend({**f,'document_id':digest,'page':page_index+1} for f in failures)
        pages.append({'document_id':digest,'page':page_index+1,'bounded_candidates':len(candidates),'unbound_labels':len(failures)})
        (output/'park-detail-candidates.json').write_text(json.dumps({'status':'unverified_native_geometry_candidates','pages':pages,'features':features,'unbound_labels':withheld,'geometry_emitted':False,'limitations':['Exact closed linework and nearby/contained labels are candidates only, not verified physical semantics','Legend, title-block, ride-platform and building ambiguities require native-page review before inclusion','Source alignment is provisional; historical and proposed drawings do not establish present-day details']},indent=2))
    return features,pages


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--planning-cache',required=True);parser.add_argument('--paving-audit',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();features,pages=recover_candidates(args.planning_cache,args.paving_audit,args.output);print(json.dumps({'inspected_pages':len(pages),'bounded_candidates':len(features),'geometry_emitted':False},indent=2))

if __name__=='__main__':main()
