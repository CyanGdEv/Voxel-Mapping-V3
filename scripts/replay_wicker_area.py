"""Replay retained SW8 and path-amendment evidence; never approves world geometry."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.linework_boundaries import run as recover
from voxel_mapper.mapped_sheet_placement import run as place
from voxel_mapper.drawing_footprints import reviewed_feature


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','candidates','references','reference-report','output'): p.add_argument('--'+name,required=True)
    a=p.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    corpus=Corpus(a.corpus)
    try:
        applications={'SMD/2016/0315','SMD/2017/0111'}; docs=[]
        for url,record,sha in corpus.db.execute('SELECT d.url,d.record,x.sha FROM documents d JOIN downloads x ON d.url=x.url WHERE x.status="downloaded" ORDER BY x.sha,d.id'):
            r=json.loads(record)
            if r.get('applicationReference',r.get('application_reference')) not in applications: continue
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha: raise ValueError('Source PDF checksum mismatch')
            docs.append({'document_sha256':sha,'application_reference':r.get('applicationReference',r.get('application_reference')),'title':r.get('title'),'drawing_state':r.get('state','unknown'),'url':url})
        shas={d['document_sha256'] for d in docs}; selected=set(); raw=Counter(); promotion=Counter(); extraction=Counter()
        for sha,result in corpus.db.execute('SELECT sha,result FROM geometry_pages'):
            if sha in shas: extraction[json.loads(result)['report'].get('status','unknown')]+=1
        for line in Path(a.candidates).open():
            r=json.loads(line)
            if r['document_sha256'] in shas:
                selected.add((r['document_sha256'],r['page'])); raw[r['geometry']['type']]+=1
                try: reviewed_feature(r,{'candidate_id':r['id']},None,{},'EPSG:27700')
                except ValueError as error: promotion[str(error)]+=1
                else: raise AssertionError('Unreviewed geometry unexpectedly promoted')
        sheets=[list(x) for x in sorted(selected)]
        if not sheets: raise ValueError('No retained area candidates')
        selection=out/'selected-sheets.json'; selection.write_text(json.dumps(sheets,indent=2)+'\n')
        print(json.dumps({'documents':len(shas),'candidate_pages':len(sheets),'raw_records':dict(raw)}),flush=True)
        recovery=recover(corpus,a.candidates,out/'boundaries',sheets=sheets)
        print(json.dumps({'recovered_faces':recovery['counts'].get('recovered_faces',0),'combined_records':recovery['records']}),flush=True)
        refs=json.loads(Path(a.reference_report).read_text())
        def progress(r):
            if r['completed_pages']%5==0: print(json.dumps(r),flush=True)
        placement=place(out/'boundaries'/'boundary-candidates.jsonl',a.references,refs['reference_crs'],refs['boundary_crs'],out/'placement',corpus,sheets=sheets,progress=progress)
        assert recovery==recover(corpus,a.candidates,out/'boundaries',sheets=sheets)
        assert placement==place(out/'boundaries'/'boundary-candidates.jsonl',a.references,refs['reference_crs'],refs['boundary_crs'],out/'placement',corpus,sheets=sheets)
        outcomes=[json.loads(x) for x in (out/'placement'/'sheet-placements.jsonl').read_text().splitlines()]
        states=Counter(r['status'] for r in outcomes)
        report={'area':'Wicker Man / SW8 and woodland path amendments','applications':sorted(applications),'documents':docs,'distinct_pdf_blobs':len(shas),'candidate_pages':len(sheets),'raw_geometry_records':dict(raw),'retained_extraction_status_counts':dict(extraction),'unreviewed_raw_promotion_rejections':dict(promotion),'selection_sha256':file_hash(selection),'recovery':recovery,'placement':placement,'sheet_status_counts':dict(states),'identical_completed_resume':True,'verified_world_geometry_additions':0,'world_export_status':'withheld; no independently verified registration or physical feature promotion','remaining_requirements':['Separate pre-construction existing plans, proposed ride and later amendments','Review physical identities, line roles and construction revisions','Three noncollinear controls and two separately sourced checkpoints with exact attachment points','Measured widths/heights/materials and valid terrain/ride elevation evidence','Compile accepted features, export bounded world and read back saved blocks']}
        (out/'area-validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'sheet_status_counts':dict(states),'placement_counts':placement['counts'],'identical_completed_resume':True}),flush=True)
    finally: corpus.close()

if __name__=='__main__': main()
