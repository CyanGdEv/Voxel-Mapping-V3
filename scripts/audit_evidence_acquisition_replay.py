"""Run a real area source pass, then prove unchanged replay needs no HTTP."""
import argparse
import json
from pathlib import Path
import time
from unittest.mock import patch

from voxel_mapper.area_reconstruction import run
from voxel_mapper.generation_cycles import atomic_json,file_hash


def audit(job,output):
    job=Path(job).resolve();configuration=json.loads(job.read_text())
    if len(configuration['areas'])!=1:raise ValueError('One bounded source investigation required')
    area=configuration['areas'][0]['id'];start=time.perf_counter()
    first=run(job,stage='extract')['areas'][area]
    first_seconds=time.perf_counter()-start
    with patch('voxel_mapper.planning_bulk.requests.Session',side_effect=AssertionError('Unchanged replay attempted HTTP')):
        start=time.perf_counter();second=run(job,stage='extract')['areas'][area]
        replay_seconds=time.perf_counter()-start
    assert second['evidence_acquisition']['run_attempts']==0
    assert second['evidence_acquisition']['run_network_bytes']==0
    assert first['available_planning_sha256']==second['available_planning_sha256']
    assert first['world_geometry_additions']==second['world_geometry_additions']==0
    assert first['reconstruction_evidence_queue']['output_sha256']==second['reconstruction_evidence_queue']['output_sha256']
    source=Path(__file__).resolve().parents[1]
    report={'version':'evidence-acquisition-real-replay-v1','status':'passed',
        'job_sha256':file_hash(job),'area_id':area,'first_seconds':first_seconds,
        'replay_seconds':replay_seconds,'first_acquisition':first['evidence_acquisition'],
        'replay_acquisition':second['evidence_acquisition'],
        'available_planning_sha256':first['available_planning_sha256'],
        'native_extracted_pages':first['extraction']['pages'],
        'architectural_pages':first['architectural_interpretation']['pages'],
        'missing_evidence_tasks':first['reconstruction_evidence_queue']['task_count'],
        'retained_text_leads':first['retained_evidence_matching']['candidate_hits'],
        'unchanged_replay_http_blocked':True,'world_geometry_additions':0,
        'requirements_resolved':0,'accepted_planning_components':0,'training_labels_generated':0,
        'code_sha256':{name:file_hash(source/name) for name in [
            'voxel_mapper/evidence_acquisition.py','voxel_mapper/planning_bulk.py',
            'voxel_mapper/area_reconstruction.py','voxel_mapper/area_cycles.py',
            'scripts/audit_evidence_acquisition_replay.py']},
        'scope':'Known official Wicker attachment catalogue; no new application/URL discovery or physical reconstruction is claimed.'}
    atomic_json(output,report)
    print(json.dumps({key:report[key] for key in ('status','area_id','native_extracted_pages','missing_evidence_tasks','retained_text_leads','unchanged_replay_http_blocked')}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();audit(args.job,args.output)
