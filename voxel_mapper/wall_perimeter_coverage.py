"""Trace source-region boundaries supported by paired walls; no inferred perimeter."""
from collections import Counter
import hashlib
import json
import math
from shapely.geometry import LineString, shape, mapping
from shapely.ops import unary_union, substring
from shapely.strtree import STRtree
from .wall_region_adjacency import VERSION as ADJACENCY_VERSION
from .drawing_components import split_page

VERSION='wall-perimeter-coverage-v1'


def review(parents,faces,bands,adjacency,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded perimeter checks required')
    records=parents+faces+bands
    pin=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
    if (adjacency['version']!=ADJACENCY_VERSION or adjacency['status']!='wall_side_region_evidence_only'
            or adjacency['source_records_sha256']!=pin):raise ValueError('Matching current source adjacency required')
    if len(parents)>10000 or len(faces)>20000 or len(bands)>10000:raise ValueError('Bounded perimeter source records required')
    lookup={r['id']:r for r in faces};band_ids={r['id'] for r in bands}
    if len(lookup)!=len(faces) or len(band_ids)!=len(bands):raise ValueError('Unique perimeter source identities required')
    if any(r['document_sha256']!=adjacency['document_sha256'] or r['page']!=adjacency['page']
           or r['coordinate_frame']!='pdf_native_points_y_up' for r in records):
        raise ValueError('Same native perimeter source page required')
    components={r['id']:r for r in split_page(parents)}
    source_bands={r['id']:r for r in bands}
    rows=adjacency['wall_adjacency']
    if len(rows)!=len(bands) or {r['wall_band_id'] for r in rows}!=band_ids:
        raise ValueError('Complete unique wall adjacency required')
    support=[];seeds={}
    for row in rows:
        band=source_bands[row['wall_band_id']]
        refs=band['source_line_references']
        if len(row['sides'])!=2 or len(refs)!=2:raise ValueError('Two original perimeter sides required')
        roles=[]
        for side,ref in zip(row['sides'],refs):
            source=components.get(ref['component_id'])
            interval=ref['source_interval_fraction']
            if (source is None or side['source_component_id']!=source['id']
                    or side['component_contract']!=source['extraction_contract']
                    or ref['component_contract']!=source['extraction_contract']
                    or side['original_source_geometry']!=source['geometry']
                    or side['source_interval_fraction']!=interval
                    or len(interval)!=2 or any(type(t) not in (int,float) or not math.isfinite(t) for t in interval)
                    or not 0<=interval[0]<interval[1]<=1):
                raise ValueError('Original perimeter side provenance required')
            expected=substring(shape(source['geometry']),*interval,normalized=True)
            if not shape(side['band_side_support']).equals_exact(expected,0):
                raise ValueError('Unchanged original perimeter side required')
            support.append({'wall_band_id':row['wall_band_id'],'source_component_id':side['source_component_id'],
                'geometry':side['band_side_support']})
            side_roles=set()
            seen=set()
            for region in side['adjacent_regions']:
                face_id=region['face_id']
                if face_id not in lookup or face_id in seen:raise ValueError('Unique original adjacent face required')
                seen.add(face_id)
                face_geometry=shape(lookup[face_id]['geometry'])
                shared=face_geometry.boundary.intersection(expected)
                if (shared.length<=1e-7 or not shape(region['shared_source_geometry']).equals_exact(shared,0)
                        or face_geometry.intersection(shape(band['geometry'])).area>1e-10):
                    raise ValueError('Original adjacent boundary support required')
                for i in region['region_claim_indices']:
                    if type(i) is not int or not 0<=i<len(adjacency['labels']):raise ValueError('Original region claim required')
                    claim=adjacency['labels'][i]
                    if (claim['status']!='unique_contained_region_claim' or claim['containing_face_ids']!=[face_id]
                            or claim['glyph_screen']['status']!='raster_consistent_candidate'
                            or not face_geometry.contains(shape(claim['label_geometry']))):
                        raise ValueError('Visible uniquely contained region claim required')
                    side_roles.add(claim['claim'])
            roles.append(side_roles)
        if row['status']=='room_to_outdoor_side_evidence':
            if (any(len(side['adjacent_regions'])!=1 for side in row['sides'])
                    or any(len(role)!=1 for role in roles)
                    or {next(iter(role)) for role in roles}!={'room_claim','outdoor_or_surface_claim'}):
                raise ValueError('Supported room-to-outdoor seed required')
            for side in row['sides']:
                for region in side['adjacent_regions']:
                    seed=seeds.setdefault(region['face_id'],{'seed_wall_band_ids':set(),'claim_indices':set()})
                    seed['seed_wall_band_ids'].add(row['wall_band_id']);seed['claim_indices'].update(region['region_claim_indices'])
    geometries=[shape(r['geometry']) for r in support];index=STRtree(geometries)
    traces=[];checks=0
    for face_id,seed in sorted(seeds.items()):
        face=lookup[face_id];polygon=shape(face['geometry'])
        if polygon.geom_type!='Polygon' or not polygon.is_valid:raise ValueError('Valid original source region required')
        rings=[polygon.exterior,*polygon.interiors];segments=[];total=0.;covered_total=0.
        for ring_index,ring in enumerate(rings):
            for segment_index,(a,b) in enumerate(zip(ring.coords,list(ring.coords)[1:])):
                checks+=1
                if checks>max_checks:break
                line=LineString([a,b]);matches=[];parts=[]
                for k in index.query(line,predicate='intersects'):
                    checks+=1
                    if checks>max_checks:break
                    k=int(k);shared=line.intersection(geometries[k])
                    if shared.length<=1e-7:continue
                    parts.append(shared);matches.append({**support[k],'shared_boundary_geometry':mapping(shared)})
                if checks>max_checks:break
                covered=unary_union(parts) if parts else LineString()
                missing=line.difference(covered)
                total+=line.length;covered_total+=covered.length
                segments.append({'ring_index':ring_index,'ring_role':'exterior_ring' if ring_index==0 else 'protected_hole_ring',
                    'segment_index':segment_index,'original_boundary_geometry':mapping(line),
                    'source_wall_support':sorted(matches,key=lambda r:(r['wall_band_id'],r['source_component_id'])),
                    'unpaired_boundary_geometry':mapping(missing),'boundary_length_pdf_points':line.length,
                    'paired_length_pdf_points':covered.length,
                    'status':'whole_source_segment_paired' if missing.is_empty else 'partial_source_segment_paired' if parts else 'no_paired_wall_support'})
            if checks>max_checks:break
        if checks>max_checks:break
        traces.append({'face_id':face_id,'source_face_sha256':hashlib.sha256(json.dumps(face,sort_keys=True).encode()).hexdigest(),
            'seed_wall_band_ids':sorted(seed['seed_wall_band_ids']),'claim_indices':sorted(seed['claim_indices']),
            'source_region_geometry':face['geometry'],'segments':segments,'hole_count':len(polygon.interiors),
            'boundary_length_pdf_points':total,'paired_length_pdf_points':covered_total,
            'coverage_fraction':covered_total/total if total else 0.,
            'complete_paired_boundary_candidate':all(r['status']=='whole_source_segment_paired' for r in segments) and bool(segments),
            'physical_wall_loop_verified':False,'building_footprint_verified':False,'footprint_export_ready':False,
            'blockers':['source_region_boundary_is_not_a_verified_building_exterior','geographic_registration_unresolved']+
                (['incomplete_paired_wall_boundary'] if any(r['status']!='whole_source_segment_paired' for r in segments) else [])})
    exhausted=checks>max_checks
    if exhausted:traces=[]
    return {'version':VERSION,'document_sha256':adjacency['document_sha256'],'page':adjacency['page'],
        'coordinate_frame':adjacency['coordinate_frame'],'source_records_sha256':pin,
        'source_adjacency_sha256':hashlib.sha256(json.dumps(adjacency,sort_keys=True).encode()).hexdigest(),
        'status':'perimeter_budget_withheld' if exhausted else 'source_region_perimeter_coverage_only',
        'region_traces':traces,'checks':checks,'max_checks':max_checks,
        'counts':{'seed_regions':len(seeds),'retained_region_traces':len(traces),
                  'complete_paired_boundary_candidates':sum(r['complete_paired_boundary_candidate'] for r in traces),
                  **dict(Counter(s['status'] for r in traces for s in r['segments']))},
        'footprint_export_ready':False,'physical_identity_verified':False,'world_geometry_additions':0,
        'limitations':['Traced rings belong to source regions; room or courtyard boundaries are not building footprints.',
            'Only original wall-side intervals provide coverage; no gaps, doorways or hulls are invented.',
            'Unpaired boundary means missing paired-wall evidence, not proof of an opening or absent physical wall.',
            'Protected hole rings are retained. Complete paired coverage alone cannot certify exterior identity or placement.']}
