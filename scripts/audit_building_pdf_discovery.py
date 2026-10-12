"""Replay model-free PDF discovery on three pinned Mutiny source sheets."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from voxel_mapper.building_pdf_discovery import prepare,VERSION
from voxel_mapper.generation_cycles import atomic_json

SOURCES=['f12239c04faecc10973483ac4f559f763300facb8fd9c1b3a1002f9c5666e58b',
         '90ecfc6b13f95eb5a911f11b7f481ae8eb25900d9fac7518160cecd5944468a1',
         '581e0fb0b88ceabd526f5d56decafd21e37945bf49ae433117be2c94bbabcaf4']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config={'version':VERSION,'buildings':[{'building_id':'mutiny-courtyard','sources':[
        {'path':str((args.sources/(sha+'.pdf')).resolve()),'sha256':sha} for sha in SOURCES]}]}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        first=prepare(config,lambda p:Path(p),root/'first');second=prepare(config,lambda p:Path(p),root/'second')
        names=('contract.json','discovery-pages.jsonl','discovery-index.json','source-queue.json','report.json')
        if first!=second or any((root/'first'/n).read_bytes()!=(root/'second'/n).read_bytes() for n in names):
            raise ValueError('Unchanged source discovery replay differs')
        if first['discovered_pages']!=3 or any(b['status']!='source_inventory_prepared' for b in first['buildings']):
            raise ValueError('Complete pinned discovery required')
        pages=[]
        for raw in (root/'first/discovery-pages.jsonl').read_bytes().splitlines(keepends=True):
            row=json.loads(raw)
            if row['world_placement_eligible'] or row['shared_spec_generated']:raise ValueError('Raw source geometry promoted')
            pages.append({'document_sha256':row['document_sha256'],'page':row['page'],'counts':row['counts'],
                'source_graph_counts':row['source_graph_counts'],'assembly_state':row['assembly_state'],
                'visible_printed_states':row['visible_printed_states'],'record_sha256':hashlib.sha256(raw).hexdigest(),
                'printed_view_claims':[{'text':v['text'],'claim':v['printed_claim'],'glyph_status':v['glyph_screen']['status']}
                    for v in row['caption_layout']['view_captions']],
                'scope_verified':row['caption_layout']['view_scope_verified']})
        receipt={'version':VERSION,'source_pdf_sha256':sorted(SOURCES),'pages':pages,
            'discovered_pages':first['discovered_pages'],'source_records':first['source_records'],
            'closed_source_faces':sum(p['counts']['closed_source_faces'] for p in pages),
            'pages_sha256':first['pages_sha256'],'output_bytes':first['output_bytes'],
            'unchanged_replay_identical':True,'model_or_manual_trace_input_required':False,
            'shared_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0,
            'limitations':['Automatic source inventory only: drawing regions are not verified building parts.',
                'Roof state remains unknown where visible captions do not establish existing/proposed state.',
                'View scopes, cross-view dimensions, heights, component identity and geographic placement remain unresolved.']}
        atomic_json(args.output,receipt)
        print(json.dumps({'discovered_pages':receipt['discovered_pages'],'source_records':receipt['source_records'],
                          'closed_source_faces':receipt['closed_source_faces'],'unchanged_replay_identical':True}))


if __name__=='__main__':main()
