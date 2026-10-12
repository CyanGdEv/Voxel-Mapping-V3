"""Source-linked placement triage; reasons and title hints are not object identity."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from .boundary_registration import file_hash
from .footprint_matching import lines

VERSION='placement-diagnostics-v1'


def diagnose(result, queued):
    hypotheses=result.get('hypotheses',[]);objects=result['verification_objects']
    if len(hypotheses)>1:reason='competing_mapped_placements'
    elif len(hypotheses)==1:reason='single_provisional_placement'
    elif objects<3:reason='fewer_than_three_polygon_objects'
    elif not result['seed_fit_attempts']:reason='no_compatible_boundary_seeds'
    else:reason='no_shared_outline_agreement'
    flags=list(result['review_flags']);sources=queued.get('sources',[])
    if any(re.search(r'\b(elevations?|sections?|floor\s+plans?)\b',s.get('title',''),re.I) for s in sources):flags.append('non_location_title_hint; review_original_page')
    if any(s.get('drawing_state')!='existing' for s in sources):flags.append('source_state_not_confirmed_existing')
    return {'document_sha256':result['document_sha256'],'page':result['page'],'reason':reason,'rank':queued.get('rank'),'sources':sources,'polygon_objects':objects,'seed_fit_attempts':result['seed_fit_attempts'],'hypothesis_count':len(hypotheses),'support_counts':[len(h['supports']) for h in hypotheses],'centroid_rms_m':[h['centroid_rms_m'] for h in hypotheses],'review_flags':sorted(set(flags)),'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0}


def run(placement_directory,queue,output):
    directory=Path(placement_directory);report=json.loads((directory/'placement-report.json').read_text());feed=directory/'sheet-placements.jsonl'
    if file_hash(feed)!=report['output_sha256']['sheet-placements.jsonl']:raise ValueError('Placement feed checksum mismatch')
    queued={}
    for row in lines(queue):
        key=(row['document_sha256'],row['page'])
        if key in queued:raise ValueError('Duplicate queue page')
        queued[key]=row
        if len(queued)>10000:raise ValueError('Diagnostic sheet budget exceeded')
    records=[];seen=set();counts=Counter();flags=Counter()
    for result in lines(feed):
        key=(result['document_sha256'],result['page'])
        if key in seen or key not in queued:raise ValueError('Placement page not unique or absent from queue')
        seen.add(key);record=diagnose(result,queued[key]);records.append(record);counts[record['reason']]+=1;flags.update(record['review_flags'])
    records.sort(key=lambda r:(r['rank'] if r['rank'] is not None else 10001,r['document_sha256'],r['page']))
    output=Path(output);output.mkdir(parents=True,exist_ok=True);path=output/'placement-triage.jsonl';temp=path.with_suffix('.partial');temp.write_text(''.join(json.dumps(r)+'\n' for r in records));temp.replace(path)
    summary={'version':VERSION,'sheets':len(records),'reason_counts':dict(counts),'flag_counts':dict(flags),'placement_receipt_sha256':file_hash(directory/'placement-report.json'),'placement_feed_sha256':file_hash(feed),'queue_sha256':file_hash(queue),'triage_sha256':file_hash(path),'world_geometry_additions':0,'limitations':['Reasons describe this bounded search, not proof that correct placement does not exist','Title/state hints require original-page and current-state review']}
    (output/'triage-report.json').write_text(json.dumps(summary,indent=2)+'\n');return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('placement-directory','queue','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(run(a.placement_directory,a.queue,a.output),indent=2))

if __name__=='__main__':main()
