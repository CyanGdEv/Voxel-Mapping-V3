"""Recompute source reviews and export two explicitly isolated shop surface studies."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_wicker_elevation_openings import run as source_review
from build_wicker_shop_walls import build, SOURCE
from review_wicker_opening_correspondence import numerically_equal
from voxel_mapper.shop_study import run

MODEL_SHA='5d791eb4dd6665fce7d889d6a32f5f65672cf8db82628d307cde864f89e9ab22'


def build_studies(pdf_directory, output, preview=False):
    output=Path(output)
    if output.exists():raise ValueError('Use a new output directory')
    review=source_review(pdf_directory)
    rebuilt=build(Path(pdf_directory)/(SOURCE+'.pdf'),'evidence/wicker-shop-vertical-annotations.json','evidence/wicker-shop-local-preview.json')
    if not numerically_equal(rebuilt,json.loads(Path('evidence/wicker-shop-wall-model.json').read_text())):
        raise ValueError('Retained source wall model failed reproduction')
    output.mkdir(parents=True);reports=[]
    for scale in (1,4):
        report=run('evidence/wicker-shop-wall-model.json',MODEL_SHA,output/f'study-{scale}',scale)
        reports.append(report)
    (output/'source-review.json').write_text(json.dumps(review,sort_keys=True,indent=2)+'\n')
    notes='''WICKER SHOP — ISOLATED PROPOSED-DRAWING REVIEW

Import Wicker_Shop_Local_Study_1to1.mcworld for one block per source metre.
Import Wicker_Shop_Local_Study_4to1.mcworld for four blocks per source metre.
The enlarged world is a detail study, not a 1:1 park reconstruction.

Both are artificial local platforms. No geographic position, bearing or ODN
floor elevation is assigned. The roof/wall centring and 180-degree source
correspondence remain hypotheses. These are source surface studies, not
accepted watertight construction shells. Wall and roof thickness and palette
are display proxies; canopy, fascia, interiors and bunding are omitted.

The northwest door keeps the earlier manual 0.901 m normalized opening. The
recovered 1.011 m cap span remains unresolved and is not silently substituted.
The 1:1 block grid can lose sub-metre doorway/facade details; inspect 4:1 too.

Native export reopens and verifies every written block and unwritten air cell.
In-game visual appearance and player movement remain to be checked by you.
Source and geometry details are in the included quality reports/source review.
'''
    (output/'README.txt').write_text(notes)
    if preview:
        from render_wicker_shop_study import render
        render(output,output/'preview.png')
    package=output/'Wicker_Shop_Local_Review.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for scale in (1,4):
            archive.write(output/f'study-{scale}'/'park.mcworld',f'Wicker_Shop_Local_Study_{scale}to1.mcworld')
            archive.write(output/f'study-{scale}'/'quality-report.json',f'quality-report-{scale}to1.json')
        archive.write(output/'source-review.json','source-review.json');archive.write(output/'README.txt','README.txt')
        if preview:archive.write(output/'preview.png','preview.png')
    receipt={'model_sha256':MODEL_SHA,'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
             'reports':reports,'geographic_placement':'withheld','park_world_blocks_added':0,
             'export_scope':'isolated proposed-source surface study only'}
    (output/'validation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf-directory',required=True);p.add_argument('--output',required=True)
    p.add_argument('--preview',action='store_true')
    a=p.parse_args();print(json.dumps(build_studies(a.pdf_directory,a.output,a.preview)))
