"""Replay spatial annotation evidence against four exact retained Wicker PDF versions."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.drawing_annotations import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-shop-plans',action='store_true',help='Include the two pinned revised shop plan sheets')
    parser.add_argument('--pdf-directory',required=True);parser.add_argument('--output')
    parser.add_argument('--catalogue-only',action='store_true')
    args=parser.parse_args()
    if not args.catalogue_only and not args.output:parser.error('--output is required unless --catalogue-only is selected')
    repo=Path(__file__).resolve().parents[1];root=Path(args.pdf_directory).resolve()
    selected=[]
    images=(163937,163939,160146,160147)+((163935,163940) if args.include_shop_plans else ())
    for name in ('wicker-shop-drawing-sources','wicker-architectural-extra-sources','wicker-site-section-sources'):
        for row in json.loads((repo/'evidence'/f'{name}.json').read_text())['documents']:
            if row.get('image',row.get('attachment_id')) in images:
                selected.append({**row,'file':row['sha256']+'.pdf'})
    if len(selected)!=len(images):raise ValueError('Exact retained source records required')
    selected.sort(key=lambda row:images.index(row.get('image',row.get('attachment_id'))))
    catalogue=root/('wicker-shop-face-documents.json' if args.include_shop_plans else 'wicker-annotation-documents.json');catalogue.write_text(json.dumps(selected,indent=2)+'\n')
    if args.catalogue_only:print(catalogue);return
    print(json.dumps(run(catalogue,args.output),indent=2))


if __name__=='__main__':main()
