"""Replay checksum-bound Wicker classification evidence, without world placement."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import Polygon
from shapely.ops import transform
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.point_cloud_audit import audit_returns
from voxel_mapper.point_cloud import is_bng
import laspy


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('cloud','crop-receipt','survey-receipt','osm','grid','output'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args();crop=json.loads(Path(a.crop_receipt).read_text())
    survey=json.loads(Path(a.survey_receipt).read_text())
    for k in ('survey_id','survey_start','survey_end'):
        if crop['survey'][k]!=survey['survey'][k]:raise ValueError('Cloud/raster survey identity mismatch')
    if file_hash(a.cloud)!=crop['sha256']:raise ValueError('Cloud crop checksum mismatch')
    if crop['bounds']!=survey['grid']['bounds']:raise ValueError('Cloud/raster crop bounds mismatch')
    with laspy.open(a.cloud) as reader:
        h=reader.header;b=crop['bounds']
        if not is_bng(h.parse_crs()) or not (b[0]<=h.mins[0]<=h.maxs[0]<=b[2] and b[1]<=h.mins[1]<=h.maxs[1]<=b[3]):
            raise ValueError('Native cloud crop exceeds retained survey bounds')
    if file_hash(a.osm)!=survey['osm_sha256'] or file_hash(a.grid)!=survey['datum_grid_sha256']:
        raise ValueError('Comparison/grid checksum mismatch')
    datadir.append_data_dir(str(Path(a.grid).resolve().parent))
    group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
        raise ValueError('Best metre-scale comparison transformation required')
    refs=[]
    for e in json.loads(Path(a.osm).read_text())['elements']:
        if e['type']=='way' and e['id'] in (834919978,70689589,107259863):
            refs.append({'id':'osm/way/'+str(e['id']),'name':e['tags']['name'],
                'geometry':transform(group.transformers[0].transform,Polygon([(v['lon'],v['lat']) for v in e['geometry']]))})
    if len(refs)!=3:raise ValueError('Three retained comparison outlines required')
    report=audit_returns(a.cloud,refs)
    if report['scanned_points']!=crop['retained_points']:raise ValueError('Crop receipt point count mismatch')
    report.update(source=crop,input_sha256={k:file_hash(getattr(a,k)) for k in ('cloud','crop_receipt','survey_receipt','osm','grid')},
        horizontal_comparison_transform_accuracy_m=group.transformers[0].accuracy)
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['landmarks']))


if __name__=='__main__':main()
