"""Replay spatial annotation evidence against four exact retained Wicker PDF versions."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.drawing_annotations import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-directory',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[1];root=Path(args.pdf_directory).resolve()
    selected=[]
    for name in ('wicker-shop-drawing-sources','wicker-architectural-extra-sources','wicker-site-section-sources'):
        for row in json.loads((repo/'evidence'/f'{name}.json').read_text())['documents']:
            if row.get('image',row.get('attachment_id')) in (163937,163939,160146,160147):
                selected.append({**row,'file':row['sha256']+'.pdf'})
    if len(selected)!=4:raise ValueError('Exact four retained source records required')
    catalogue=root/'wicker-annotation-documents.json';catalogue.write_text(json.dumps(selected,indent=2)+'\n')
    print(json.dumps(run(catalogue,args.output),indent=2))


if __name__=='__main__':main()
