"""Checksum-pinned mapped building/water comparison outlines within a park domain."""
import argparse
from collections import Counter
import json
from pathlib import Path

from pyproj import CRS,Transformer
from shapely.geometry import shape
from shapely.ops import transform

from .boundary_registration import file_hash

VERSION='physical-references-v1'


def select(feed,domain,domain_crs):
    crs=CRS.from_user_input(domain_crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info):raise ValueError('Projected metre park domain CRS required')
    if domain.geom_type not in ('Polygon','MultiPolygon') or domain.is_empty or not domain.is_valid or domain.has_z:raise ValueError('Valid 2D park polygon required')
    if feed.get('type')!='FeatureCollection' or len(feed.get('features',[]))>100000:raise ValueError('Bounded mapped FeatureCollection required')
    converter=Transformer.from_crs(4326,crs,always_xy=True);rows=[];counts=Counter();ids=set()
    for feature in feed['features']:
        kind=feature.get('properties',{}).get('kind')
        if kind not in ('building','water') or feature.get('geometry',{}).get('type') not in ('Polygon','MultiPolygon'):continue
        identifier=feature.get('id')
        if not isinstance(identifier,str) or not identifier or identifier in ids:raise ValueError('Unique physical reference identity required')
        ids.add(identifier);geometry=shape(feature['geometry'])
        if geometry.is_empty or not geometry.is_valid or geometry.has_z:raise ValueError('Valid 2D mapped outline required')
        counts['physical_outlines']+=1
        if not domain.covers(transform(converter.transform,geometry)):
            counts['outside_or_crossing_park_domain']+=1;continue
        rows.append(feature);counts[kind]+=1;counts['named' if feature.get('properties',{}).get('name') else 'unnamed']+=1
        if len(rows)>5000:raise ValueError('At most 5000 physical comparison references')
    rows.sort(key=lambda f:f['id'])
    return {'type':'FeatureCollection','features':rows},dict(counts)


def run(osm,boundary,boundary_crs,output,*,expected_osm_sha256,expected_boundary_sha256):
    from .cli import parse_osm
    if file_hash(osm)!=expected_osm_sha256 or file_hash(boundary)!=expected_boundary_sha256:raise ValueError('Mapped source or park boundary checksum mismatch')
    feed,_=parse_osm(json.loads(Path(osm).read_text()));domain=shape(json.loads(Path(boundary).read_text()));selected,counts=select(feed,domain,boundary_crs)
    output=Path(output);output.mkdir(parents=True,exist_ok=True);path=output/'physical-references.geojson';temporary=path.with_suffix('.partial');temporary.write_text(json.dumps(selected,sort_keys=True)+'\n');temporary.replace(path)
    report={'version':VERSION,'osm_sha256':expected_osm_sha256,'boundary_sha256':expected_boundary_sha256,'boundary_crs':CRS.from_user_input(boundary_crs).to_wkt(),'reference_crs':'EPSG:4326','references':len(selected['features']),'counts':counts,'reference_sha256':file_hash(path),'status':'mapped_comparison_evidence_only','survey_verification':False,'current_as_built_verified':False,'world_geometry_additions':0}
    (output/'reference-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('osm','boundary','boundary-crs','osm-sha256','boundary-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(run(a.osm,a.boundary,a.boundary_crs,a.output,expected_osm_sha256=a.osm_sha256,expected_boundary_sha256=a.boundary_sha256),indent=2))

if __name__=='__main__':main()
