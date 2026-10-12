"""Match targeted Mutiny requirements against checksum-pinned acquired native PDFs."""
import argparse
import hashlib
import json
from pathlib import Path
from voxel_mapper.retained_evidence_matching import match

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input-root',type=Path,required=True)
p.add_argument('--catalogue',type=Path,required=True)
p.add_argument('--queue',type=Path,default=Path('evidence/mutiny-reconstruction-evidence-queue-audit.json'))
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();queue_raw=a.queue.read_bytes();queue=json.loads(queue_raw)
raw=a.catalogue.read_bytes();catalogue=json.loads(raw);records=catalogue.get('entries',catalogue.get('documents',[]))
documents={};missing=[]
for record in records:
 sha=record.get('sha256');path=a.input_root/(str(sha)+'.pdf')
 link={k:record[k] for k in ('url','title','state','applicationReference') if k in record}
 if sha and path.is_file():
  row=documents.setdefault(sha,{'sha256':sha,'path':str(path),'source_links':[]})
  if link not in row['source_links']:row['source_links'].append(link)
 else:missing.append(link)
result=match(queue,list(documents.values()))
result['input_pins']={'requirement_file_sha256':hashlib.sha256(queue_raw).hexdigest(),
 'catalogue_sha256':hashlib.sha256(raw).hexdigest()}
result['unavailable_document_links']=missing
if a.queue.read_bytes()!=queue_raw or a.catalogue.read_bytes()!=raw:raise ValueError('Replay input changed')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'status':result['status'],'pdfs':len(documents),'pages':result['pages_examined'],
 'hits':len(result['hits']),'counts':result['counts'],'unavailable_links':len(missing),
 'tasks_with_leads':sum(bool(t['candidate_hit_ids']) for t in result['task_results'])}))
