"""Reproduce source context cues and compare both shop roof orientations."""
import argparse,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laspy,numpy as np,pymupdf
from shapely.geometry import MultiPoint,shape
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.orientation_cues import compare_cues,northing_direction
from voxel_mapper.point_cloud import is_bng
from review_wicker_roof_plan import PDF,CANDIDATE

PROJECTION='017f2e1f17de2c8965bd947b90b85cb57a924ab5da7dbde9cc6564b74120d080'
INTERIOR='102c8401a3282b973f89faca10c0a059f40417d61deb210144b3cf04f8d7d816'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('pdf','cloud','roof-report','plan-review','aerial-query','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();roof=json.loads(Path(a.roof_report).read_text());plan=json.loads(Path(a.plan_review).read_text());aerial=json.loads(Path(a.aerial_query).read_text())
    if file_hash(a.pdf)!=PDF or plan['input_sha256']['pdf']!=PDF or file_hash(a.cloud)!=roof['input_sha256']['cloud'] or plan['input_sha256']['cloud']!=roof['input_sha256']['cloud'] or plan['input_sha256']['roof_report']!=file_hash(a.roof_report):raise ValueError('Exact source/cloud/roof/plan bindings required')
    with pymupdf.open(a.pdf) as d:
        page=d[0];raw,_=extract_page(page,PDF,1);labels=[]
        for w in page.get_text('words'):
            if re.fullmatch(r'\d+N',w[4]):
                point=pymupdf.Point((w[0]+w[2])/2,(w[1]+w[3])/2)*~page.transformation_matrix
                labels.append({'text':w[4],'northing':int(w[4][:-1]),'native_centre':[point.x,point.y]})
    candidates,_=recover_page(raw)
    source={c['id']:c for c in candidates};lines={r['id']:r for r in raw}
    outline,projection,interior=source[CANDIDATE],source[PROJECTION],lines[INTERIOR]
    with laspy.open(a.cloud) as reader:
        if not is_bng(reader.header.parse_crs()) or reader.header.point_count>15_000_000:raise ValueError('Bounded native BNG cloud required')
    cloud=laspy.read(a.cloud);ranked=sorted(roof['distinct_observed_envelopes'],key=lambda r:r['point_count'])
    if len(ranked)!=2:raise ValueError('Exact two-envelope context required')
    def members(e):
        row=next(c for c in roof['candidates'] if c.get('membership_sha256')==e['membership_sha256'])
        ids=row['original_crop_point_indices']
        if len(ids)>20_000 or any(type(i)!=int or not 0<=i<len(cloud) for i in ids):raise ValueError('Bounded original indices required')
        return set(ids)
    core=members(ranked[0]);expanded=members(ranked[1])
    if not core<expanded:raise ValueError('Nested observed components required')
    def observed(ids):
        pts=cloud[sorted(ids)]
        if not ((np.asarray(pts.classification)==6)&(~np.asarray(pts.withheld,dtype=bool))&(~np.asarray(pts.synthetic,dtype=bool))).all():raise ValueError('Eligible class-6 cue returns required')
        return np.column_stack((pts.x,pts.y,pts.z))
    xyz=observed(core);lower=observed(expanded-core)
    native=MultiPoint(xyz[:,:2]).convex_hull
    if not native.equals_exact(shape(ranked[0]['geometry']),0,normalize=True):raise ValueError('Core geometry mismatch')
    orientations=next(e for e in plan['envelopes'] if e['membership_sha256']==ranked[0]['membership_sha256'])['printed_scale_edge_review']['equivalent_orientations']
    report=compare_cues(shape(outline['geometry']),shape(projection['geometry']),shape(interior['geometry']),xyz,MultiPoint(lower[:,:2]).convex_hull,orientations)
    report['document_northing_direction_review']=northing_direction(labels,orientations)
    response=aerial['response']
    if 'error' in response or response.get('exceededTransferLimit') or not isinstance(response.get('features'),list):raise ValueError('Complete catalogue response required')
    report.update(document_sha256=PDF,page=1,source_cues={'outline':outline,'projection':projection,'interior_line':interior},
        lower_return_count=len(lower),aerial_catalogue_search={'query':aerial,'feature_count':len(response['features']),
            'status':'no_coverage_in_queried_catalogue' if not response['features'] else 'unreviewed_coverage',
            'accepted_checkpoints':0,'scope':'One official vertical photography catalogue and the queried tile; not all aerial imagery providers'},
        input_sha256={k:file_hash(getattr(a,k)) for k in ('pdf','cloud','roof_report','plan_review','aerial_query')})
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'source_line_midpoint_offset_pdf_points':report['source_interior_line_midpoint_offset_pdf_points'],
        'projection_comparisons':[r['projection_to_lower_envelope'] for r in report['orientation_comparisons']],
        'ridge_comparisons':[r['high_return_line_comparisons'] for r in report['orientation_comparisons']],
        'catalogue_status':report['aerial_catalogue_search']['status']}))


if __name__=='__main__':main()
