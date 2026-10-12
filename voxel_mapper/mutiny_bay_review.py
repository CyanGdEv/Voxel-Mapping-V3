"""Hash-pinned courtyard topology and bounded one-object alignment diagnostics."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, box, mapping
from .forbidden_valley import reviewed_outline
from .wicker_registration import similarity_candidates

ROOF = '581e0fb0b88ceabd526f5d56decafd21e37945bf49ae433117be2c94bbabcaf4'


def compare_envelopes(source, mapped, printed_scale):
    """Diagnose shape/scale disagreement; a one-object fit never approves placement."""
    if not math.isfinite(printed_scale) or printed_scale <= 0:
        raise ValueError('Positive finite printed scale required')
    candidates = similarity_candidates(list(source.minimum_rotated_rectangle.exterior.coords)[:4],
                                       list(mapped.minimum_rotated_rectangle.exterior.coords)[:4])
    best = min(candidates, key=lambda c:c['shop_corner_rms_m'])
    difference = abs(best['scale_m_per_pdf_point']/printed_scale-1)
    return {'status':'withheld_one_object_alignment', 'candidate_for_diagnosis_only':best,
            'printed_scale_m_per_point':printed_scale, 'fit_scale_difference_fraction':difference,
            'printed_scale_gate_passed':difference<=.02, 'independent_control_objects':1,
            'registration_verified':False, 'world_geometry_additions':0,
            'reason':'One mapped building does not establish placement; differing envelopes may represent different physical extents'}


def extract_roof(cache):
    import pymupdf
    path=Path(cache)/'files'/(ROOF+'.pdf')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ROOF:
        raise ValueError('Existing courtyard roof source hash mismatch')
    with pymupdf.open(path) as pdf:
        page=pdf[0]
        if 'Existing Roof Plan' not in page.get_text() or '1 : 200' not in page.get_text():
            raise ValueError('Existing roof revision/scale labels no longer match')
        # Reviewed inner roof/eaves corners; never infer them from a room label.
        courtyard=reviewed_outline(page,[(565,783),(1019,783),(1019,1208),(565,1208)],tolerance=3)
        # The corner towers and entry project beyond the main four wings.
        # This envelope is deliberately a diagnostic proxy, not a full footprint.
        roof_envelope=box(477.84,692.4,1107.12,1317.84)
        if not roof_envelope.covers(courtyard):
            raise ValueError('Courtyard outside reviewed roof envelope')
        scale=200/(1000*72/25.4)
        return {'document_id':ROOF,'page':1,'state':'existing','drawing':'3023-10',
                'frame':'displayed_pdf_points_rotation_applied',
                'scale_m_per_point':scale,'scale_status':'printed_1_200_not_independently_verified',
                'courtyard_geometry':mapping(courtyard),
                'courtyard_nominal_area_m2':courtyard.area*scale**2,
                'roof_envelope_geometry':mapping(roof_envelope),
                'roof_envelope_nominal_dimensions_m':[(roof_envelope.bounds[2]-roof_envelope.bounds[0])*scale,
                                                       (roof_envelope.bounds[3]-roof_envelope.bounds[1])*scale],
                'roof_envelope_status':'simplified_proxy_not_complete_roof_or_building_boundary',
                'courtyard_status':'Inner roof perimeter retained; existing canopy and access details not removed',
                'registration_verified':False,'world_geometry_additions':0}


def review(cache,osm):
    from shapely.geometry import shape
    profile=extract_roof(cache)
    raw=json.loads(Path(osm).read_text())
    way=next(e for e in raw['elements'] if e.get('type')=='way' and e['id']==113576011)
    t=Transformer.from_crs(4326,27700,always_xy=True)
    mapped=Polygon([t.transform(p['lon'],p['lat']) for p in way['geometry']])
    alignment=compare_envelopes(shape(profile['roof_envelope_geometry']),mapped,profile['scale_m_per_point'])
    return {'status':'courtyard_topology_retained_alignment_withheld','profile':profile,'alignment':alignment,
            'mapped_building':{'id':way['id'],'name':way['tags'].get('name'),
                               'area_m2':mapped.area,'interior_rings':len(mapped.interiors)},
            'osm_sha256':hashlib.sha256(Path(osm).read_bytes()).hexdigest(),
            'limitations':['Roof envelope and mapped BBQ polygon are not proven to cover the same complete structure',
                           'Historical inner roof perimeter does not authorize clearing the current canopy',
                           'No whole-area translation or world replacement is approved by this diagnostic']}


def audit_channel(source, osm):
    """Read existing native cells without approving or clearing any structure."""
    import collections
    import amulet
    from shapely.geometry import shape
    from shapely.ops import transform
    from .cli import parse_osm
    from .reconstruction.geometry import roof_cells
    source=Path(source)
    q=json.loads((source/'quality-report.json').read_text())
    raw=json.loads(Path(osm).read_text())
    relation=next(e for e in raw['elements'] if e.get('type')=='relation' and e['id']==17436870)
    member=next(m for m in relation['members'] if m['ref']==453985982)
    project=Transformer.from_crs(4326,q['crs'],always_xy=True)
    g=Polygon([project.transform(p['lon'],p['lat']) for p in member['geometry']])
    if not g.is_valid or not 1<g.area<5000:raise ValueError('Bounded mapped channel required')
    features,_=parse_osm(raw)
    waters=[transform(project.transform,shape(f['geometry'])) for f in features['features']
            if f['properties']['kind']=='water' and shape(f['geometry']).geom_type in ('Polygon','MultiPolygon')]
    from shapely.ops import unary_union
    overlap=g.intersection(unary_union(waters)).area
    cells=roof_cells(g);counts=collections.Counter();cache={}
    world=amulet.load_level(str(source/'bedrock-world'))
    try:
        for x,z in cells:
            key=x//16,(-z)//16
            if key not in cache:cache[key]=world.get_chunk(*key,'minecraft:overworld')
            chunk=cache[key]
            for y in range(168,195):
                block=chunk.block_palette[int(chunk.blocks[x%16,y+q['world']['vertical_offset_blocks'],(-z)%16])]
                counts[block.base_name]+=1
    finally:world.close()
    return {'source_package_sha256':hashlib.sha256((source/'park.mcworld').read_bytes()).hexdigest(),
            'osm_relation':17436870,'osm_member':453985982,'footprint_area_m2':g.area,
            'mapped_water_overlap_area_m2':overlap,'columns_checked':len(cells),
            'geographic_y_scan_m':[168,194],'native_material_counts':dict(counts),
            'stone_brick_cells':counts['stone_bricks'],'world_mutations':0,
            'status':'Read-only bounded native scan; no structure removal authorized'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',required=True);p.add_argument('--osm',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source-output',help='Optional retained native world for the bounded channel audit')
    a=p.parse_args();out=Path(a.output)
    if out.exists():raise ValueError('Refusing to overwrite review output')
    out.mkdir(parents=True);r=review(a.cache,a.osm)
    if a.source_output:r['native_channel_audit']=audit_channel(a.source_output,a.osm)
    (out/'mutiny-bay-alignment-review.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r['alignment'],indent=2))

if __name__=='__main__':main()
