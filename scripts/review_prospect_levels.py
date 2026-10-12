"""Verify retained relative height references against the reviewed AL3.06 PDF."""
import argparse,hashlib,json
from pathlib import Path
import pymupdf as fitz


def verify(pdf, review):
    path=Path(pdf);data=json.loads(Path(review).read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest()!=data['source_sha256']:raise ValueError('Elevation source hash changed')
    doc=fitz.open(path)
    try:
        drawings=doc[0].get_drawings();rows=data['relative_levels'];base=rows[0]['paper_y_pt'];scale=data['scale_denominator']*.0254/72
        for row in rows:
            y=row['paper_y_pt']
            if abs(row['height_above_reference_m']-(base-y)*scale)>1e-8:raise ValueError('Relative height differs from scale')
            if not row['path_indices']:raise ValueError('Missing reference paths')
            for index in row['path_indices']:
                d=drawings[index]
                matches=any(it[0]=='l' and abs(it[1].y-y)<.01 and abs(it[2].y-y)<.01 for it in d['items'])
                matches |= bool(d['fill']) and abs(d['rect'].y0-y)<.01
                if not matches:raise ValueError('Referenced vector edge changed')
        return {'verified_relative_levels':len(rows),'absolute_registration':data['absolute_registration'],'world_geometry_additions':0}
    finally:doc.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',required=True);p.add_argument('--review',default='voxel_mapper/data/prospect-elevation-review.json');args=p.parse_args();print(json.dumps(verify(args.pdf,args.review)))
