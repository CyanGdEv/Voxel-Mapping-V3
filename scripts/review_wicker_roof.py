"""Extract shop roof-envelope hypotheses from the checksum-bound dated cloud."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laspy,numpy as np
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import Polygon
from shapely.ops import transform
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.point_cloud import is_bng
from voxel_mapper.roof_candidates import roof_candidates


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('cloud','crop-receipt','survey-receipt','osm','grid','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();crop=json.loads(Path(a.crop_receipt).read_text());survey=json.loads(Path(a.survey_receipt).read_text())
    if file_hash(a.cloud)!=crop['sha256'] or file_hash(a.osm)!=survey['osm_sha256'] or file_hash(a.grid)!=survey['datum_grid_sha256']:
        raise ValueError('Retained cloud/OSM/datum-grid bytes required')
    if crop['bounds']!=survey['grid']['bounds'] or any(crop['survey'][k]!=survey['survey'][k] for k in ('survey_id','survey_start','survey_end')):
        raise ValueError('Dated cloud/raster identity and native bounds must match')
    datadir.append_data_dir(str(Path(a.grid).resolve().parent));group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Best metre-scale comparison transform required')
    found=[e for e in json.loads(Path(a.osm).read_text())['elements'] if e['type']=='way' and e['id']==834919978]
    if len(found)!=1:raise ValueError('Unique retained shop comparison required')
    ref=transform(group.transformers[0].transform,Polygon([(v['lon'],v['lat']) for v in found[0]['geometry']]))
    with laspy.open(a.cloud) as reader:
        h=reader.header;b=crop['bounds']
        if not is_bng(h.parse_crs()) or h.point_count!=crop['retained_points'] or h.point_count>15_000_000 or not (b[0]<=h.mins[0]<=h.maxs[0]<=b[2] and b[1]<=h.mins[1]<=h.maxs[1]<=b[3]):raise ValueError('Bounded native BNG crop required')
        arrays=[];ids=[];scanned=0;selected=0
        for pts in reader.chunk_iterator(500_000):
            xyz=np.column_stack((pts.x,pts.y,pts.z))
            mask=(np.asarray(pts.classification)==6)&(~np.asarray(pts.withheld,dtype=bool))&(~np.asarray(pts.synthetic,dtype=bool))&np.isfinite(xyz).all(axis=1)
            selected+=int(np.count_nonzero(mask))
            if selected>20_000:raise ValueError('Roof connectivity point budget exceeded')
            arrays.append(xyz[mask]);ids.append(np.flatnonzero(mask)+scanned);scanned+=len(pts)
        if scanned!=h.point_count:raise ValueError('Truncated crop')
    report=roof_candidates(np.concatenate(arrays),np.concatenate(ids),ref,crop['bounds'])
    report.update(reference_id='osm/way/834919978',name=found[0]['tags']['name'],survey=crop['survey'],
        input_sha256={k:file_hash(getattr(a,k)) for k in ('cloud','crop_receipt','survey_receipt','osm','grid')},
        comparison_transform_accuracy_m=group.transformers[0].accuracy,
        selection_method='Connected components over all eligible class-6 returns in the crop; outline seeds ranking only')
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'spread_m':report['maximum_connectivity_boundary_spread_m'],'candidates':[{k:r.get(k) for k in ('radius_m','height_step_m','point_count','seed_point_count','area_m2','comparison_outline_iou','crop_edge_within_connectivity_radius')} for r in report['candidates']]}))


if __name__=='__main__':main()
