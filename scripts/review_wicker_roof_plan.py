"""Re-extract a pinned shop outline and compare native survey roof envelopes."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laspy,numpy as np,pymupdf
from shapely.geometry import MultiPoint,shape
from voxel_mapper.boundary_registration import file_hash,fit_boundary
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.roof_plan_review import page_scale,fixed_scale_edges
from voxel_mapper.point_cloud import is_bng

PDF='1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d'
CANDIDATE='c631c9fa7adff4f77172e3d30eac1cf566847a40d391ddad7b18a596a7d7be52'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('pdf','cloud','roof-report','crop-receipt','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();roof=json.loads(Path(a.roof_report).read_text());crop=json.loads(Path(a.crop_receipt).read_text())
    if file_hash(a.pdf)!=PDF:raise ValueError('Exact retained planning PDF required')
    if file_hash(a.cloud)!=crop['sha256'] or roof['input_sha256']['cloud']!=crop['sha256'] or roof['input_sha256']['crop_receipt']!=file_hash(a.crop_receipt):raise ValueError('Cloud/crop/roof evidence binding mismatch')
    if any(roof['survey'][k]!=crop['survey'][k] for k in ('survey_id','survey_start','survey_end')):raise ValueError('Dated survey mismatch')
    with pymupdf.open(a.pdf) as d:
        raw,extraction=extract_page(d[0],PDF,1);candidates,recovery=recover_page(raw)
        found=[c for c in candidates if c['id']==CANDIDATE]
        if len(found)!=1:raise ValueError('Exact shop source candidate not reproduced')
        source=found[0];scale=page_scale(d[0].get_text(),d[0].mediabox.width,d[0].mediabox.height)
    if scale['status']!='single_native_page_scale':raise ValueError('Unique native paper-labelled scale required')
    # Reconstruct each reported envelope from original crop indices, not a drawn rectangle.
    with laspy.open(a.cloud) as reader:
        if reader.header.point_count!=crop['retained_points'] or reader.header.point_count>15_000_000 or not is_bng(reader.header.parse_crs()):raise ValueError('Bounded native BNG crop required')
    if not 1<=len(roof['distinct_observed_envelopes'])<=16 or len(roof['candidates'])>16:raise ValueError('Bounded envelope sweep required')
    cloud=laspy.read(a.cloud);rows=[]
    for envelope in roof['distinct_observed_envelopes']:
        candidate=next(c for c in roof['candidates'] if c.get('membership_sha256')==envelope['membership_sha256'])
        raw_ids=candidate['original_crop_point_indices']
        if any(type(i)!=int for i in raw_ids):raise ValueError('Integer original crop indices required')
        ids=np.asarray(raw_ids,dtype=np.int64)
        if len(ids)>20_000 or len(ids)!=len(set(ids.tolist())) or np.any(ids<0) or np.any(ids>=len(cloud)):raise ValueError('Invalid envelope provenance indices')
        pts=cloud[ids]
        if not ((np.asarray(pts.classification)==6)&(~np.asarray(pts.withheld,dtype=bool))&(~np.asarray(pts.synthetic,dtype=bool))).all():raise ValueError('Eligible building return provenance required')
        xyz=np.column_stack((pts.x,pts.y,pts.z))
        if not np.isfinite(xyz).all():raise ValueError('Finite observed XYZ required')
        native=MultiPoint(xyz[:,:2]).convex_hull
        if not native.equals_exact(shape(envelope['geometry']),0,normalize=True):raise ValueError('Reported envelope does not reproduce native returns')
        if len(ids)!=envelope['point_count']:raise ValueError('Envelope point count mismatch')
        if hashlib.sha256(np.asarray(ids,dtype='<u8').tobytes()).hexdigest()!=envelope['membership_sha256']:raise ValueError('Membership hash mismatch')
        rows.append({'membership_sha256':envelope['membership_sha256'],'point_count':len(ids),
            'observed_envelope_reproduced':True,'parameter_combinations':envelope['parameter_combinations'],
            'free_scale_diagnostic':fit_boundary(shape(source['geometry']),native,scale_denominators=(scale['denominator'],)),
            'printed_scale_edge_review':fixed_scale_edges(shape(source['geometry']),native,scale['denominator'])})
    report={'status':'source_linked_edge_review_only','document_sha256':PDF,'page':1,
        'source_candidate':source,'source_candidate_reproduced':True,'native_page_scale':scale,
        'survey':crop['survey'],'envelopes':rows,'point_pairs_submitted_to_registration':0,
        'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
        'physical_identity_verified':False,'registration_verified':False,
        'input_sha256':{k:file_hash(getattr(a,k)) for k in ('pdf','cloud','roof_report','crop_receipt')},
        'remaining_requirements':['Resolve equivalent orientations using identified physical context',
            'Establish whether the planning line is a roof/eave/wall boundary and measure any offset',
            'Measure native edge uncertainty from appropriate survey evidence',
            'Supply separately sourced, identified independent physical checkpoints; boundary residuals are not checks']}
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([{'points':r['point_count'],'fixed_iou':r['printed_scale_edge_review']['best_fit']['intersection_over_union'],
        'fixed_hausdorff_m':r['printed_scale_edge_review']['best_fit']['boundary_hausdorff_m'],
        'equivalent_orientations':len(r['printed_scale_edge_review']['equivalent_orientations']),
        'flags':r['printed_scale_edge_review']['review_flags']} for r in rows]))


if __name__=='__main__':main()
