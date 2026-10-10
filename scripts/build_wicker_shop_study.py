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


def build_studies(pdf_directory, output, preview=False, joined=False, closed=False, slabs=False):
    closed=closed or slabs
    joined=joined or closed
    output=Path(output)
    if output.exists():raise ValueError('Use a new output directory')
    review=source_review(pdf_directory)
    rebuilt=build(Path(pdf_directory)/(SOURCE+'.pdf'),'evidence/wicker-shop-vertical-annotations.json','evidence/wicker-shop-local-preview.json')
    if not numerically_equal(rebuilt,json.loads(Path('evidence/wicker-shop-wall-model.json').read_text())):
        raise ValueError('Retained source wall model failed reproduction')
    model_path='evidence/wicker-shop-wall-model.json';model_sha=MODEL_SHA
    if joined:
        from build_wicker_shop_projection import build as build_projection
        model_path='evidence/wicker-shop-projection-model.json'
        model_sha='4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1'
        if not numerically_equal(build_projection(pdf_directory,'evidence/wicker-shop-wall-model.json'),json.loads(Path(model_path).read_text())):
            raise ValueError('Retained canopy model failed reproduction')
    output.mkdir(parents=True);reports=[]
    for scale in (1,):
        report=run(model_path,model_sha,output/f'study-{scale}',scale,joined,closed,slabs)
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
    if joined:
        notes=notes.replace('Local_Study','Joined_Study').replace('canopy, fascia, interiors and bunding are omitted.',
            'interiors, side fascia and bunding are omitted.')
        notes+='\nJOINED REVIEW MODE\nExisting wall columns extend vertically to the sampled main-roof underside.\nThese added cells are estimated display joins, not measured construction.\nThe source wall/roof meshes are unchanged. Every join is listed in the reports.\nCanopy and front fascia use the provisional NE-height model; the conflicting\nSE height remains unresolved. Fine fascia detail may disappear at 1:1.\n'
    if closed:
        notes=notes.replace('Joined_Study','Boundary_V3_Study')
        notes+='\nBOUNDARY V3 REVIEW\nComplete footprint boundary columns are filled to the main roof, with door\napertures kept clear. Vertical roof step risers are filled as display proxies.\nAn outside-air flood checks all interior air cells under the roof, with the\nfloor and doors temporarily sealed only for the test. Reports retain counts.\nIn Minecraft choose the world named Wicker Shop BOUNDARY V3 REVIEW.\n'
    notes='\n'.join(line for line in notes.splitlines() if '4to1' not in line and 'enlarged world' not in line and 'inspect 4:1' not in line)
    if slabs:
        notes=notes.replace('Boundary_V3_Study','Slabs_V4_Study').replace('BOUNDARY V3 REVIEW','SLABS V4 REVIEW')
        notes+='\nSLAB SHAPES\nRoof/canopy use native half-height dark-oak slabs where half-metre samples\nallow; mixed halves and wall joins keep full blocks. The final native shape\noccupancy passes an outside-air check at half-metre resolution. Materials\nremain illustrative. Fences await supported post/rail geometry.\n'
    (output/'README.txt').write_text(notes)
    if preview:
        from render_wicker_shop_study import render
        render(output,output/'preview.png',boundary=closed)
    prefix='Joined' if joined else 'Local'
    if closed:prefix='Boundary_V3'
    if slabs:prefix='Slabs_V4'
    package=output/f'Wicker_Shop_{prefix}_Review.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for scale in (1,):
            archive.write(output/f'study-{scale}'/'park.mcworld',f'Wicker_Shop_{prefix}_Study_{scale}to1.mcworld')
            archive.write(output/f'study-{scale}'/'quality-report.json',f'quality-report-{scale}to1.json')
        archive.write(output/'source-review.json','source-review.json');archive.write(output/'README.txt','README.txt')
        if preview:archive.write(output/'preview.png','preview.png')
    receipt={'model_sha256':model_sha,'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
             'reports':reports,'geographic_placement':'withheld','park_world_blocks_added':0,
             'export_scope':'isolated 1:1 native slab study with estimated closure and canopy hypothesis' if slabs else 'isolated proposed-source study with estimated boundary closure and canopy hypothesis' if closed else 'isolated proposed-source study with estimated joins and canopy hypothesis' if joined else 'isolated proposed-source surface study only'}
    (output/'validation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf-directory',required=True);p.add_argument('--output',required=True)
    p.add_argument('--preview',action='store_true')
    p.add_argument('--joined',action='store_true',help='Estimated wall-to-roof joins and retained provisional canopy')
    p.add_argument('--closed',action='store_true',help='Complete footprint boundary and roof-step display closure; implies --joined')
    p.add_argument('--slabs',action='store_true',help='1:1 native half-height roof/canopy review; implies --closed')
    a=p.parse_args();print(json.dumps(build_studies(a.pdf_directory,a.output,a.preview,a.joined,a.closed,a.slabs)))
