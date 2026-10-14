"""Original named plan enclosures and held-out sheet-layout scale diagnostics."""
import hashlib
import json
import math
from pathlib import Path
import re

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape, Point, box, Polygon, mapping

from .building_spec import digest
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span
from .plan_elevation_edges import straight_edges, plan_scale
from .plan_network import recover, VERSION as NETWORK_VERSION
from .clipped_plan_fills import recover as recover_fills
from .fill_endcaps import recover as recover_endcaps
from .sheet_layout_audit import anchors,fit,diagnostic_lengths,VERSION as LAYOUT_VERSION
from .generation_cycles import atomic_json

VERSION='building-plan-audit-v1'


def _bounds(value):
    if (not isinstance(value,list) or len(value)!=4
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in value)
            or value[0]>=value[2] or value[1]>=value[3]):
        raise ValueError('Finite ordered source bounds required')
    return value


def named_enclosures(page,sha,number,label,bounds,network,unit):
    """Retain every exact face containing a visible named label; never close gaps."""
    traces=page.get_texttrace();inverse=native_inverse(page);scope=box(*bounds)
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:
        raise ValueError('Named plan text budget exceeded')
    if not isinstance(label,str) or not label.strip() or len(label)>128:
        raise ValueError('Literal bounded component label required')
    rows=[];area_claims=[]
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        area=re.fullmatch(r'GIA\s*:?\s*(\d{1,5}(?:\.\d{1,3})?)\s*m(?:2|²)',text,re.I)
        if text!=label and not area:continue
        rect=pymupdf.Rect(run['bbox']);points=[pymupdf.Point(p)*inverse for p in (rect.tl,rect.tr,rect.br,rect.bl)]
        polygon=Polygon([(p.x,p.y) for p in points])
        if not scope.covers(polygon):continue
        center=(rect.tl+rect.br)*.5;native=center*inverse
        row={'text':text,'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'label_geometry':mapping(polygon),'center_pdf_native':[native.x,native.y],
            'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
        if area:
            area_claims.append({**row,'printed_gia_m2':float(area[1]),'component_assignment_verified':False});continue
        matches=[];crossing=[]
        if row['glyph_screen']['status']=='raster_consistent_candidate':
            for face in network['faces']:
                g=shape(face['geometry'])
                if not g.contains(Point(center.x,center.y)):continue
                native_shape=affine_transform(g,[inverse.a,inverse.c,inverse.b,inverse.d,inverse.e,inverse.f])
                item={'source_face_id':face['id'],'source_edge_ids':face['source_edge_ids'],
                    'geometry':mapping(native_shape),'coordinate_frame':'pdf_native_points_y_up',
                    'interior_rings':len(g.interiors),'nominal_area_m2':g.area*unit*unit if unit else None,
                    'physical_footprint_verified':False,'scale_application_verified':False}
                (matches if scope.covers(native_shape) else crossing).append(item)
        row.update(enclosure_candidates=matches,crossing_scope_candidates=crossing,
            status='withheld_label_visibility' if row['glyph_screen']['status']!='raster_consistent_candidate' else
                'exact_named_enclosure_candidate' if len(matches)==1 and not crossing else
                'ambiguous_named_enclosures' if matches or crossing else 'no_exact_named_enclosure')
        rows.append(row)
    return {'document_sha256':sha,'page':number,'component_label':label,
        'declared_scope_pdf_native':bounds,'component_scope_verified':False,'label_occurrences':rows,
        'printed_area_claims':area_claims,'unique_component_identity_verified':False,
        'closed_source_footprint_candidates':sum(len(r['enclosure_candidates']) for r in rows),
        'geometry_snapping_or_gap_bridging':False,'complete_building_specs_generated':0,'world_geometry_additions':0}


def _source(source,resolve):
    if not isinstance(source,dict) or set(source)!={'path','sha256','page','furniture_bounds_pdf_native'}:
        raise ValueError('Original sheet path/hash/page and furniture scope required')
    sha=source['sha256'];number=source['page']
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Pinned original sheet required')
    if type(number) is not int or not 1<=number<=10000:raise ValueError('Bounded sheet page required')
    if not isinstance(source['path'],str) or not source['path']:raise ValueError('Original sheet path required')
    _bounds(source['furniture_bounds_pdf_native']);path=Path(resolve(source['path']))
    if path.stat().st_size>32000000:raise ValueError('Original sheet byte budget exceeded')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Original sheet checksum mismatch')
    return path,data


def prepare(config,resolve,output):
    if (not isinstance(config,dict) or config.get('version')!=VERSION
            or set(config)-{'version','building_id','plan','reference_sheet','furniture_anchors',
                'component_label','component_bounds_pdf_native','elevation_width_candidates_m'}):
        raise ValueError('Versioned source plan audit request required')
    identifier=config.get('building_id');bounds=_bounds(config.get('component_bounds_pdf_native'))
    if not isinstance(identifier,str) or not 1<=len(identifier)<=256:raise ValueError('Bounded building identity required')
    if not isinstance(config.get('plan'),dict) or not isinstance(config.get('reference_sheet'),dict):
        raise ValueError('Original plan and reference sheet descriptors required')
    if box(*bounds).intersects(box(*_bounds(config['plan']['furniture_bounds_pdf_native']))):
        raise ValueError('Component region and furniture fit region must be disjoint')
    widths=config.get('elevation_width_candidates_m',[])
    if (not isinstance(widths,list) or len(widths)>32 or any(type(w) not in (int,float)
            or not math.isfinite(w) or not .5<=w<=100 for w in widths)):
        raise ValueError('Bounded diagnostic width candidates required')
    plan_path,plan_data=_source(config['plan'],resolve);ref_path,ref_data=_source(config['reference_sheet'],resolve)
    if config['plan']['sha256']==config['reference_sheet']['sha256']:
        raise ValueError('Independent original sheets required for layout comparison')
    root=Path(output)
    if root.exists():raise ValueError('Fresh plan audit output required')
    with pymupdf.open(stream=plan_data,filetype='pdf') as plan_doc,pymupdf.open(stream=ref_data,filetype='pdf') as ref_doc:
        psource=config['plan'];rsource=config['reference_sheet']
        if psource['page']>len(plan_doc) or rsource['page']>len(ref_doc):raise ValueError('Requested source sheet page absent')
        page=plan_doc[psource['page']-1];reference=ref_doc[rsource['page']-1]
        for doc,pg in ((plan_doc,page),(ref_doc,reference)):
            kind,value=doc.xref_get_key(pg.xref,'UserUnit')
            if (kind!='null' and float(value)!=1) or pg.cropbox!=pg.mediabox:
                raise ValueError('Standard original sheet frame required for printed scale audit')
        terms=config.get('furniture_anchors');names=[t.get('text') for t in terms] if isinstance(terms,list) and all(isinstance(t,dict) for t in terms) else []
        subject=anchors(page,psource['sha256'],psource['page'],names,psource['furniture_bounds_pdf_native'])
        ref=anchors(reference,rsource['sha256'],rsource['page'],names,rsource['furniture_bounds_pdf_native'])
        layout=fit(subject,ref,terms)
        edges=straight_edges(page,psource['sha256'],psource['page']);network=recover(edges);scale=plan_scale(page)
        unit=scale['nominal_metres_per_pdf_point_candidate']
        enclosure=named_enclosures(page,psource['sha256'],psource['page'],config.get('component_label'),bounds,network,unit)
        fills=recover_fills(page,psource['sha256'],psource['page'])
        gaps=recover_endcaps(fills['candidates'],unit) if unit else {'status':'withheld_nominal_scale','gaps':[]}
        gaps.update(document_sha256=psource['sha256'],page=psource['page'])
        inverse=native_inverse(page);scoped_gaps=[]
        for gap in gaps['gaps']:
            polygon=affine_transform(shape(gap['gap_corridor_geometry']),
                [inverse.a,inverse.c,inverse.b,inverse.d,inverse.e,inverse.f])
            if box(*bounds).covers(polygon):
                scoped_gaps.append({'source_gap_id':gap['id'],'parent_fill_candidate_ids':gap['parent_fill_candidate_ids'],
                    'geometry':mapping(polygon),'coordinate_frame':'pdf_native_points_y_up',
                    'nominal_gap_width_m':gap['nominal_gap_width_m'],'physical_opening_verified':False,
                    'inferred_closure_applied':False})
        reference_scale=plan_scale(reference);reference_unit=reference_scale['nominal_metres_per_pdf_point_candidate']
        same_scale=unit is not None and reference_unit is not None and abs(unit-reference_unit)<1e-12
        dimensions=[{'target_width_m':w,'target_width_basis':'declared_diagnostic_input_not_verified_measurement',
            'inverse_layout_length_candidates':diagnostic_lengths(edges,layout,unit,w)
            if same_scale else [],'comparison_status':'nominal_equal_scale_layout_hypotheses_only' if same_scale else
                'withheld_different_or_unresolved_printed_scales','geometry_correction_applied':False} for w in widths]
        report={'version':VERSION,'building_id':identifier,'config_sha256':digest(config),
            'source_sha256':[psource['sha256'],rsource['sha256']],'layout_version':LAYOUT_VERSION,'network_version':NETWORK_VERSION,
            'sheet_layout_audit':layout,'plan_scale_review':scale,'reference_scale_review':reference_scale,
            'named_enclosure_audit':enclosure,'source_network_counts':network['counts'],
            'fill_recovery_counts':fills['counts'],'endcap_gap_candidates':len(gaps['gaps']),
            'component_scope_gap_candidates':scoped_gaps,
            'diagnostic_dimensions':dimensions,'source_geometry_changed':False,'physical_scale_verified':False,
            'complete_building_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0}
        # Expose the same JSON-only contract in memory and on disk.
        report=json.loads(json.dumps(report,allow_nan=False))
    for source,path in ((config['plan'],plan_path),(config['reference_sheet'],ref_path)):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('Original sheet changed during plan audit')
    root.mkdir(parents=True)
    atomic_json(root/'report.json',report);atomic_json(root/'source-network.json',network)
    atomic_json(root/'source-fills.json',fills)
    atomic_json(root/'source-fill-endcaps.json',gaps)
    atomic_json(root/'review-queue.json',{'version':VERSION,'source_sha256':report['source_sha256'],
        'status':'awaiting_footprint_scale_and_view_review','outcome':None,
        'requirements':['source_supported_closed_component_footprint','viewport_specific_scale_review',
            'physical_reference_and_revision_identity','per_view_state','cross_view_depth_and_vertical_datum'],
        'training_labels_generated':0})
    return report
