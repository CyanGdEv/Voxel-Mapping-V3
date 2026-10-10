"""Review floor-sheet reduction using shared page furniture, never building-fit controls."""
import argparse,collections,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pymupdf
from voxel_mapper.drawing_page_tools import native_inverse

FLOOR='08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3'
ROOF='6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047'
HOLDOUT={'01-08-2016','NS','Checker','Alton Towers Resort, Farley Lane, Alton'}

def anchors(pdf,sha):
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest()!=sha:raise ValueError('PDF checksum mismatch')
    result=collections.defaultdict(list)
    with pymupdf.open(pdf) as doc:
        page=doc[0];inverse=native_inverse(page)
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    result[span['text'].strip()].append(list(pymupdf.Point(*span['origin'])*inverse))
    return result

def review(floor_pdf,roof_pdf,floor_review,roof_review):
    f=anchors(floor_pdf,FLOOR);r=anchors(roof_pdf,ROOF)
    rows=[{'text':k,'floor_native_origin':f[k][0],'roof_native_origin':r[k][0],
           'role':'holdout' if k in HOLDOUT else 'fit'} for k in sorted(f.keys()&r.keys())
          if len(f[k])==len(r[k])==1 and not k.isdigit() and not k.startswith('\\')]
    train=[v for v in rows if v['role']=='fit'];check=[v for v in rows if v['role']=='holdout']
    if len(train)<10 or len(check)!=4:raise ValueError('Expected shared furniture anchors missing')
    x=np.array([v['roof_native_origin']+[1] for v in train]);y=np.array([v['floor_native_origin'] for v in train])
    matrix,_,rank,_=np.linalg.lstsq(x,y,rcond=None)
    if rank!=3:raise ValueError('Collinear sheet anchors')
    for v in rows:v['residual_pdf_points']=float(np.linalg.norm(np.array(v['roof_native_origin']+[1])@matrix-v['floor_native_origin']))
    max_check=max(v['residual_pdf_points'] for v in check)
    if max_check>.25:raise ValueError('Shared furniture transform fails held-out labels')
    inverse=np.linalg.inv(matrix[:2])
    floor=json.loads(Path(floor_review).read_text());roof=json.loads(Path(roof_review).read_text())
    if floor['source_sha256']!=FLOOR or roof['source_sha256']!='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6':raise ValueError('Review source mismatch')
    points=np.array(floor['local_outer_corners'])@inverse
    lengths=[float(np.linalg.norm(points[i]-points[(i+1)%4])) for i in range(4)]
    dims=sorted([sum(lengths[::2])/2,sum(lengths[1::2])/2],reverse=True)
    elevation=[roof['profiles'][0]['measurements']['wall_span']['metres'],roof['profiles'][3]['measurements']['wall_span']['metres']]
    differences=[dims[i]-elevation[i] for i in range(2)]
    openings=[]
    for o in floor['openings']:
        endpoints=np.array(o['local_projected_endpoints'])@inverse
        openings.append({**o,'normalized_local_endpoints':endpoints.tolist(),'normalized_width_metres':float(np.linalg.norm(endpoints[1]-endpoints[0]))})
    segments=[{**s,'normalized_start':(np.array(s['start'])@inverse).tolist(),'normalized_end':(np.array(s['end'])@inverse).tolist()} for s in floor['wall_segments']]
    return {'floor_sha256':FLOOR,'roof_plan_sha256':ROOF,'input_review_hashes':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [floor_review,roof_review]},
            'method':'affine native-page furniture correspondence, roof sheet to reduced floor sheet; excludes building geometry',
            'anchors':rows,'roof_to_floor_matrix_row_convention':matrix.tolist(),'floor_to_roof_linear_matrix':inverse.tolist(),
            'linear_singular_values':np.linalg.svd(matrix[:2],compute_uv=False).tolist(),'heldout_max_residual_pdf_points':max_check,
            'normalized_local_outer_corners':points.tolist(),'normalized_wall_segments':segments,'normalized_openings':openings,
            'normalized_dimensions_metres':dims,'normalized_outer_area_metres_squared':floor['outer_area_metres_squared']/float(np.linalg.det(matrix[:2])),
            'normalized_minus_elevation_metres':differences,'dimension_agreement_within_0_25_metres':all(abs(d)<.25 for d in differences),
            'source_scale_reduction_supported':True,'geographic_registration':None,'world_placement_eligible':False,
            'limitations':['Furniture holdouts validate a page-layout transform, not geographic registration.',
                           'Applying furniture scaling to the shop view is provisional; figured dimensions take priority.',
                           'Proposed wall heights, as-built identity, floor datum and geographic checkpoints remain unresolved.'],
            'world_geometry_additions':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('floor-pdf','roof-pdf','floor-review','roof-review','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();r=review(a.floor_pdf,a.roof_pdf,a.floor_review,a.roof_review)
    Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'normalized_dimensions_metres':r['normalized_dimensions_metres'],'heldout_max_residual_pdf_points':r['heldout_max_residual_pdf_points'],'dimension_agreement':r['dimension_agreement_within_0_25_metres']}))

if __name__=='__main__':main()
