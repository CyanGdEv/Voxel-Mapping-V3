"""Extract complete native paint primitives from bounded overlapping page regions.

Regions are extraction windows, never geographic areas or accepted world frames.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .drawing_geometry import extract_page, validated_options, VERSION as GEOMETRY_VERSION
from .drawing_page_tools import native_inverse
from .mapped_alignment_checks import printed_scale_review

VERSION='regional-drawing-geometry-v1'


def run(pdf,output,*,page_number=1,columns=4,rows=4,overlap_points=24,**overrides):
    import pymupdf
    if any(type(v) is not int or not 1<=v<=8 for v in (columns,rows)):
        raise ValueError('Grid dimensions must be 1..8')
    if type(overlap_points) not in (int,float) or not 0<=overlap_points<=100:
        raise ValueError('Overlap must be 0..100 native PDF points')
    options=validated_options(overrides)
    if 'region_native_points' in options:raise ValueError('Grid supplies extraction regions')
    pdf=Path(pdf);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with pdf.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    scale=printed_scale_review(pdf,page_number)
    reports=[];counts=Counter();unique=set();duplicates=0
    destination=output/'geometry-candidates.jsonl';temporary=destination.with_suffix('.jsonl.partial')
    with pymupdf.open(pdf) as document,temporary.open('w') as stream:
        if type(page_number) is not int or not 1<=page_number<=len(document):raise ValueError('Valid page required')
        page=document[page_number-1];matrix=native_inverse(page);angle=page.rotation
        try:
            page.set_rotation(0);frame=page.rect*matrix
        finally:page.set_rotation(angle)
        paths=page.get_cdrawings(extended=True)
        for row in range(rows):
            for column in range(columns):
                bounds=[max(frame.x0,frame.x0+frame.width*column/columns-overlap_points),
                        max(frame.y0,frame.y0+frame.height*row/rows-overlap_points),
                        min(frame.x1,frame.x0+frame.width*(column+1)/columns+overlap_points),
                        min(frame.y1,frame.y0+frame.height*(row+1)/rows+overlap_points)]
                candidates,report=extract_page(page,digest,page_number,_paths=paths,**options,region_native_points=bounds)
                report.update(row=row,column=column,region_native_points=bounds)
                reports.append(report)
                for candidate in candidates:
                    if candidate['id'] in unique:duplicates+=1;continue
                    unique.add(candidate['id']);counts[candidate['geometry']['type']]+=1
                    stream.write(json.dumps(candidate,sort_keys=True)+'\n')
    with pdf.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:
            temporary.unlink(missing_ok=True);raise ValueError('Source PDF changed during regional extraction')
    temporary.replace(destination)
    with destination.open('rb') as stream:candidate_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'version':VERSION,'geometry_version':GEOMETRY_VERSION,'document_sha256':digest,'page':page_number,
            'status':'unplaced_regional_geometry_only','grid':[columns,rows],'overlap_points':overlap_points,
            'options':options,'regions':reports,'unique_candidates':len(unique),'geometry_types':dict(counts),
            'overlap_duplicates':duplicates,'candidate_file_sha256':candidate_sha,'printed_scale_review':scale,
            'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0,
            'limitations':['Complete paint primitives crossing every window remain deferred.',
                           'Partial candidate/point budgets remain explicit in each regional report.',
                           'Paper scale does not establish survey registration or component identity.']}
    (output/'regional-geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--page',type=int,default=1);parser.add_argument('--columns',type=int,default=4)
    parser.add_argument('--rows',type=int,default=4);parser.add_argument('--overlap-points',type=float,default=24)
    args=parser.parse_args()
    report=run(args.pdf,args.output,page_number=args.page,columns=args.columns,rows=args.rows,overlap_points=args.overlap_points)
    print(json.dumps({k:v for k,v in report.items() if k not in ('regions','printed_scale_review')},indent=2))

if __name__=='__main__':main()
