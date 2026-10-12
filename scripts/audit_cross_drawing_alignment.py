"""Replay retained real pages through contextual matching and shared evidence memory."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.cross_drawing_alignment import run,VERSION
from voxel_mapper.evidence_memory import EvidenceMemory
from voxel_mapper.generation_cycles import atomic_json
from voxel_mapper.planning_bulk import Corpus


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','geometry','work-directory','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--target-crs',required=True)
    args=parser.parse_args();root=args.work_directory
    if root.exists():raise ValueError('Fresh contextual audit directory required')
    root.mkdir(parents=True);store=root/'evidence-memory.sqlite';corpus=Corpus(args.corpus)
    try:
        first=run(corpus,args.geometry,store,root/'first',target_crs=args.target_crs)
        resumed=run(corpus,args.geometry,store,root/'first',target_crs=args.target_crs)
        replay=run(corpus,args.geometry,store,root/'replay',target_crs=args.target_crs)
        if first['output_sha256']!=resumed['output_sha256'] or first['output_sha256']!=replay['output_sha256']:
            raise ValueError('Unchanged page proposals differ on replay')
        if resumed['run_pages']!=0 or replay['run_pages']!=0 or replay['reused_pages']!=first['pages']:
            raise ValueError('Unchanged contextual pages were recomputed')
        if first['registrations_accepted'] or first['world_geometry_additions'] or first['training_labels_generated']:
            raise ValueError('Contextual hypotheses were promoted')
        with EvidenceMemory(store) as memory:memory_report=memory.report()
        receipt={'version':VERSION,'source_pdf_sha256':sorted({p[0] for p in first['contract']['source_pages']}),
            'source_geometry_sha256':first['contract']['source_geometry_sha256'],
            'pages':first['pages'],'page_statuses':first['page_statuses'],'landmarks':first['landmarks'],
            'page_proposals_sha256':first['output_sha256'],'source_pages':first['contract']['source_pages'],
            'unchanged_resume_identical':True,'fresh_output_reuses_pages':replay['reused_pages'],
            'memory':memory_report,'registrations_accepted':0,'world_geometry_additions':0,'training_labels_generated':0,
            'limitations':['No verified physical anchors are present in this retained-input audit.',
                'Unique synthetic contextual fits remain hypotheses until independent evidence checks pass.',
                'This matcher is deterministic; it does not train or promote a learned model.']}
        atomic_json(args.output,receipt)
        print(json.dumps({k:receipt[k] for k in ('pages','page_statuses','landmarks','fresh_output_reuses_pages')}))
    finally:corpus.close()


if __name__=='__main__':main()
