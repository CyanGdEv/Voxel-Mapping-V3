"""Source-checked attachment review queue, without invented physical checkpoints."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rasterio,pymupdf
from shapely.geometry import Polygon,shape
from shapely.ops import transform
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from voxel_mapper.boundary_registration import file_hash,fit_boundary
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.raster_landmarks import attachment_stability

PDF='1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pdf','dtm','dsm','survey-receipt','osm','grid','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();receipt=json.loads(Path(a.survey_receipt).read_text())
    if file_hash(a.pdf)!=PDF:raise ValueError('Exact retained planning PDF required')
    for kind in ('dtm','dsm'):
        if file_hash(getattr(a,kind))!=receipt['crop_sha256'][kind]:raise ValueError('Dated raster crop checksum mismatch')
    if file_hash(a.grid)!=receipt['datum_grid_sha256'] or file_hash(a.osm)!=receipt['osm_sha256']:raise ValueError('Retained grid/OSM checksum mismatch')
    if receipt['survey']['survey_id']!='P_10682' or receipt['survey']['survey_start']!='20220105' or receipt['survey']['survey_end']!='20220105':raise ValueError('Exact dated survey identity required')
    datadir.append_data_dir(str(Path(a.grid).resolve().parent));group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Best metre-scale comparison transform required')
    project=group.transformers[0];refs=[]
    for e in json.loads(Path(a.osm).read_text())['elements']:
        if e['type']=='way' and e['id'] in (834919978,70689589,107259863):refs.append({'id':'osm/way/'+str(e['id']),'name':e['tags']['name'],'geometry':transform(project.transform,Polygon([(v['lon'],v['lat']) for v in e['geometry']]))})
    if len(refs)!=3:raise ValueError('Three comparison outlines required')
    with rasterio.open(a.dtm) as g,rasterio.open(a.dsm) as s:
        if g.crs.to_epsg()!=27700 or s.crs!=g.crs or s.transform!=g.transform or s.shape!=g.shape or g.res!=(1,1):raise ValueError('Matched native metre BNG grids required')
        review=attachment_stability(g.read(1,masked=True),s.read(1,masked=True),g.transform,refs)
    with pymupdf.open(a.pdf) as d:raw,extraction=extract_page(d[0],PDF,1)
    candidates,recovery=recover_page(raw);by_id={c['id']:c for c in candidates}
    source_ids={'osm/way/834919978':'c631c9fa7adff4f77172e3d30eac1cf566847a40d391ddad7b18a596a7d7be52','osm/way/70689589':'c9dd868808f29e5ebe0064254d4fcbc52517137914abebd134bc9db71cb82670','osm/way/107259863':'de6cbe692f9b518cee0168516d655c803ac425302b307a62db1f46918ace17f7'}
    for row in review['landmarks']:
        cid=source_ids[row['reference_id']];c=by_id.get(cid)
        row['source_candidate_id']=cid;row['source_candidate_reproduced']=c is not None
        if c is None:row['reasons'].append('Retained source outline not reproduced');continue
        row['source_candidate']=c;row['outline_fit_diagnostics']=[]
        for comparison in row['comparisons']:
            if 'region_geometry' not in comparison or comparison['intersection_over_union']<.7:continue
            fit=fit_boundary(shape(c['geometry']),shape(comparison['region_geometry']))
            row['outline_fit_diagnostics'].append({'threshold_m':comparison['threshold_m'],'boundary_hypothesis':fit,'physical_attachment_verified':False})
    review.update(document_sha256=PDF,page=1,survey=receipt['survey'],input_sha256={k:file_hash(getattr(a,k)) for k in ('pdf','dtm','dsm','survey_receipt','osm','grid')},drawing_extraction_status=extraction['status'],linework_recovery_status=recovery['status'],point_pairs_submitted_to_registration=0,registration_status='withheld; exact independent physical attachment points not established',limitations=['Minimum rectangle corners are inspection estimates, not surveyed building corners','Threshold selection can merge roof/trees/supports or shrink outlines','Roof-to-wall offsets and native edge uncertainty remain unmeasured','No check is relabelled independent based only on a different point name'])
    Path(a.output).write_text(json.dumps(review,indent=2)+'\n')
    print(json.dumps([{'name':r['name'],'source_reproduced':r['source_candidate_reproduced'],'boundary_spread_m':r['maximum_threshold_boundary_spread_m'],'accepted_checkpoints':0} for r in review['landmarks']]))

if __name__=='__main__':main()
