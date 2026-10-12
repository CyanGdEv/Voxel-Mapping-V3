"""Rank local orientation hypotheses against mapped context without accepting registration."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import Polygon
from shapely.ops import unary_union

OSM='49f601bb30fc11935457f26f6653b53be1b0172820a25c8c465ee84d91497d93'
GRID='5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa'

def review(osm_path,grid_path,lidar_path):
    def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    if digest(osm_path)!=OSM or digest(grid_path)!=GRID:raise ValueError('Pinned mapped context/grid required')
    datadir.append_data_dir(str(Path(grid_path).resolve().parent));group=TransformerGroup(4326,27700,always_xy=True)
    if not group.best_available:raise ValueError('Best datum transform unavailable')
    transform=next(t for t in group.transformers if 0<=t.accuracy<=1)
    osm=json.loads(Path(osm_path).read_text())['elements'];shop=next(e for e in osm if e['type']=='way' and e['id']==834919978)
    station=next(e for e in osm if e['type']=='relation' and e['id']==17436869)
    def polygon(points):return Polygon([transform.transform(p['lon'],p['lat']) for p in points])
    shop_poly=polygon(shop['geometry']);station_poly=unary_union([polygon(m['geometry']) for m in station['members'] if m['role']=='outer'])
    centre=np.array(shop_poly.centroid.coords[0]);target=np.array(station_poly.centroid.coords[0]);vector=target-centre;vector/=np.linalg.norm(vector)
    report=json.loads(Path(lidar_path).read_text());rows=[]
    for envelope in report['envelopes']:
        hypotheses=[]
        for h in envelope['hypotheses']:
            matrix=np.array(h['local_metres_to_bng_matrix']);rear=matrix@np.array([-1.,0]);rear/=np.linalg.norm(rear)
            angle=math.degrees(math.acos(float(np.clip(np.dot(rear,vector),-1,1))))
            hypotheses.append({'rotation_degrees':h['rotation_degrees'],'rear_direction_bng_unit_vector':rear.tolist(),'rear_to_mapped_station_centroid_angle_degrees':angle,
                               'station_context_facing':angle<90,'registration_verified':False})
        hypotheses.sort(key=lambda h:h['rear_to_mapped_station_centroid_angle_degrees'])
        rows.append({'point_count':envelope['point_count'],'hypotheses_ranked_by_context':hypotheses})
    return {'status':'mapped_context_orientation_preference_only','shop_way_id':834919978,'station_complex_relation_id':17436869,
            'station_relation_name':station.get('tags',{}).get('name'),'station_complex_bng_centroid':target.tolist(),
            'shop_mapped_centroid_bng':centre.tolist(),'station_complex_distance_from_shop_metres':float(np.linalg.norm(target-centre)),
            'station_complex_bng_geometry':station_poly.__geo_interface__,'envelopes':rows,
            'independent_access_guide_context':{'url':'https://www.accessable.co.uk/alton-towers-resort/access-guides/wicker-man-shop',
                'retrieved_date':'2026-10-10','access_route':'indexed page text; direct page and image access returned 403',
                'survey_date_verified':False,'front_opening_width_metres':3,'front_protective_canopy_reported':False,
                'rear_ride_to_shop_access':'steps and platform lift','physical_canopy_identity_verified':False},
            'input_sha256':{str(p):digest(p) for p in [osm_path,grid_path,lidar_path]},
            'limitations':['Unnamed mapped station complex is contextual, not a positively surveyed attachment landmark.',
                           'OSM was already used to seed roof candidates; this comparison is not an independent geographic checkpoint.',
                           'Front canopy absence does not establish rear canopy absence.',
                           'Access-guide survey date and geographic control coordinates were not obtained.',
                           'Source layouts and current observations can differ; proposed opening widths are not automatically replaced.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['osm','grid','lidar-review','output']:p.add_argument('--'+k,required=True)
    a=p.parse_args();r=review(a.osm,a.grid,a.lidar_review);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps([{'points':e['point_count'],'angles':[round(h['rear_to_mapped_station_centroid_angle_degrees'],2) for h in e['hypotheses_ranked_by_context']]} for e in r['envelopes']]))

if __name__=='__main__':main()
