"""Source-linked, unplaced facade hypotheses; never accepted building geometry."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pymupdf

from .automatic_facade_alignment import compare_position
from . import automatic_facade_alignment, automatic_opening_links, generation_cycles, reconstruction_evidence_queue
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-unplaced-facade-preview-v1'


def target_checks(artwork, charge):
    """Check excluded target references against the fixed fit. Never fit them."""
    pages = {(p['document_sha256'], p['page']): p for p in artwork['pages']}
    targets = {tuple(k) for k in artwork['excluded_target_sheet_keys']}
    result = []
    for pair in artwork['pairs']:
        if pair['status'] != 'supported_non_target_artwork_layout_only': continue
        if any(tuple(r['key'][:2]) in targets for r in pair['controls']):
            raise ValueError('Target reference entered the non-target fit')
        groups = []
        for side in ('subject', 'reference'):
            page = pages[tuple(pair[side+'_page_key'])]
            grouped = defaultdict(list)
            for m in page['markers']:
                if m['key'] and tuple(m['key'][:2]) in targets: grouped[tuple(m['key'])].append(m)
            groups.append(grouped)
        for key in sorted(groups[0].keys() | groups[1].keys()):
            charge(); left, right = (g.get(key, []) for g in groups)
            row = {'pair_id': pair['id'], 'key': list(key), 'fit_used': False,
                   'subject_marker_ids': [m['id'] for m in left], 'reference_marker_ids': [m['id'] for m in right],
                   'status': 'whole_visible_unique_target_references_required', 'physical_scale_verified': False}
            def occurrences(markers):
                return {(tuple(m['center_pdf_native']), m['sheet_trace_index'], tuple(m['outside_trace_indices'])) for m in markers}
            if (len(occurrences(left)) == len(occurrences(right)) == 1 and
                    all(m['status'] == 'original_numbered_artwork_reference_candidate' for m in left+right)):
                a, b = left[0], right[0]
                values = [*a['center_pdf_native'], *b['center_pdf_native'], *a['font_sizes_points'], *b['font_sizes_points'],
                          *[m['radius_page_points'] for m in left+right]]
                if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                    raise ValueError('Finite target reference measurements required')
                if min(values[4:]) <= 0: raise ValueError('Positive target font and radius required')
                predicted = np.asarray(b['center_pdf_native']) @ pair['reference_to_subject_linear_row_matrix'] + pair['reference_to_subject_translation']
                residual = float(np.linalg.norm(predicted-a['center_pdf_native']))
                ratios = [x/y for x, y in zip(a['font_sizes_points'], b['font_sizes_points'])]
                ratios += [x['radius_page_points']/y['radius_page_points'] for x in left for y in right]
                row.update(subject_center=a['center_pdf_native'], reference_center=b['center_pdf_native'],
                           predicted_subject_center=predicted.tolist(), residual_pdf_points=residual, font_and_radius_ratios=ratios)
                row['status'] = ('fixed_non_target_layout_agrees_at_target_annotation' if residual <= .25 and
                    all(abs(v/pair['apparent_subject_artwork_scale']-1) <= .015 for v in ratios) else 'fixed_layout_target_annotation_mismatch')
            row['id'] = digest([VERSION, row]); result.append(row)
    return result


def bottom_bands(gray, bounds, source_to_pixel, unit, charge):
    """Retain every dark horizontal band near the observed jamb ends, not a threshold."""
    if gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 2000000:
        raise ValueError('Bounded uint8 bottom crop required')
    x0, y0, x1, y1 = bounds
    if not all(math.isfinite(v) for v in bounds) or not x0 < x1 or not y0 < y1:
        raise ValueError('Finite positive source opening bounds required')
    zoom, tx, ty = source_to_pixel
    if not all(math.isfinite(v) for v in (zoom, tx, ty, unit)) or zoom <= 0 or unit <= 0:
        raise ValueError('Positive finite crop scale required')
    # Central 60% avoids jambs. Lower half of original jamb height, plus 0.25 nominal m.
    lo = math.ceil((x0+.2*(x1-x0))*zoom+tx); hi = math.floor((x1-.2*(x1-x0))*zoom+tx)
    start = math.floor((y0+.5*(y1-y0))*zoom+ty)
    end = math.ceil((y1+.25/unit)*zoom+ty)
    result = {'status': 'bottom_band_search_crosses_source_crop', 'bands': [], 'source_opening_bounds_display': bounds,
              'physical_threshold_verified': False, 'selected_physical_bottom_m': None,
              'search_pixel_interval': [lo, start, hi, end], 'candidate_bottom_display_interval': None}
    if not (0 <= lo < hi <= gray.shape[1] and 0 <= start < end <= gray.shape[0]): return result
    all_bands = []
    for threshold in (96, 128):
        bands = []; run = None
        for y in range(start, end):
            charge(); coverage = float(np.count_nonzero(gray[y, lo:hi] <= threshold)/(hi-lo))
            if coverage >= .8:
                if run is None: run = {'row_interval_pixels': [y, y+1], 'minimum_dark_fraction': coverage}
                else:
                    run['row_interval_pixels'][1] = y+1
                    run['minimum_dark_fraction'] = min(coverage, run['minimum_dark_fraction'])
            elif run is not None: bands.append(run); run = None
        if run is not None: bands.append(run)
        for b in bands:
            b.update(threshold=threshold, display_y_interval=[(v-ty)/zoom for v in b['row_interval_pixels']])
            b['touches_search_boundary'] = b['row_interval_pixels'][0] == start or b['row_interval_pixels'][1] == end
        result['bands'].extend(bands); all_bands.append(bands)
    if all(len(b) == 1 and not b[0]['touches_search_boundary'] for b in all_bands):
        intervals = [b[0]['display_y_interval'] for b in all_bands]
        if max(i[0] for i in intervals) < min(i[1] for i in intervals):
            result.update(status='cross_threshold_source_base_band_candidate',
                          candidate_bottom_display_interval=[min(i[0] for i in intervals), max(i[1] for i in intervals)])
            return result
    result['status'] = 'source_base_band_missing_or_ambiguous'
    return result


def context_mesh(parent, child, matrix, unit, datum):
    """A zero-thickness context plane and measured opening outline; no carved aperture."""
    if (len(matrix) != 6 or not all(math.isfinite(v) for v in [*matrix, unit, datum]) or
            matrix[0] <= 0 or matrix[3] <= 0 or matrix[1:3] != [0., 0.] or abs(matrix[0]-matrix[3]) > 1e-6 or unit <= 0):
        raise ValueError('Finite uniform source display transform required')
    if not (parent[0] < child[0] < child[2] < parent[2] and parent[1] < child[1] < child[3] <= parent[3]):
        raise ValueError('Original surrounding parent and positive child required')
    def rectangle(bounds):
        x0,y0,x1,y1 = bounds
        return [[(x-parent[0])*matrix[0]*unit, 0., (datum-(y*matrix[3]+matrix[5]))*unit]
                for x,y in [(x0,y1),(x1,y1),(x1,y0),(x0,y0)]]
    return {'coordinate_frame': 'nominal metres; x from original parent left, y=0 display plane, z relative to printed level',
            'context_vertices': rectangle(parent), 'context_triangles': [[0,1,2],[0,2,3]],
            'opening_outline_vertices': rectangle(child), 'aperture_triangles': [], 'wall_thickness_m': None,
            'physical_wall_height_m': None, 'physical_opening_bottom_m': None, 'physical_opening_height_m': None,
            'context_surface_role': 'original_raster_parent_rectangle_only_not_exterior_wall_boundary'}


def _json(path):
    path = Path(path)
    if path.stat().st_size > 64000000: raise ValueError('Bounded preview input required')
    return json.loads(path.read_text())


def _verified_inputs(components, views, corpus):
    report = _json(components/'component-report.json'); vr = _json(views/'view-report.json')
    pins = report['output_sha256']; vpins = vr['output_sha256']
    if len(pins) > 64 or len(vpins) > 256: raise ValueError('Bounded original artifact lists required')
    for root, values in ((components,pins),(views,vpins)):
        for name, sha in values.items():
            path = (root/name).resolve()
            if not path.is_relative_to(root.resolve()) or file_hash(path) != sha: raise ValueError('Preview source artifact changed')
    if (report['contract']['version'] != 'automatic-view-component-inventory-v11' or
            file_hash(views/'view-report.json') != report['contract']['view_report_sha256']):
        raise ValueError('Matching original preview view pack required')
    source = _json(views/'view-candidates.json')
    if file_hash(views/'view-candidates.json') != report['contract']['view_candidates_sha256']:
        raise ValueError('Original view candidates changed')
    for sha in vr['contract']['source_sha256']:
        if not re.fullmatch(r'[a-f0-9]{64}', sha): raise ValueError('Original PDF digest required')
        if file_hash(corpus/'files'/(sha+'.pdf')) != sha: raise ValueError('Original preview PDF checksum mismatch')
    required = [r['file'] for r in report['results']] + [report[k]['file'] for k in ('building_facade_links','elevation_level_context',
        'facade_alignment','sheet_scale_evidence','wall_return_corners','door_symbol_evidence','artwork_scale_controls')]
    if any(name not in pins for name in required): raise ValueError('Every preview input must be hash pinned')
    inventories = {r['view_id']: _json(components/r['file']) for r in report['results']}
    if len(inventories) != len(report['results']) or len(inventories) > 32: raise ValueError('Unique bounded preview inventories required')
    all_views = [(p,v) for p in source['pages'] for v in p['views']]
    source_views = {v['id']: (p,v) for p,v in all_views}
    if len(all_views) != len(source_views) or len(all_views) > 3200: raise ValueError('Unique bounded source views required')
    for key, inv in inventories.items():
        if inv['source_view_sha256'] != digest(source_views[key][1]): raise ValueError('Original preview view changed')
    reviews = {key: _json(components/report[key]['file']) for key in ('building_facade_links','elevation_level_context',
        'facade_alignment','sheet_scale_evidence','wall_return_corners','door_symbol_evidence','artwork_scale_controls')}
    ipins = {key:digest(v) for key,v in inventories.items()}
    for value in reviews.values():
        if value['source_inventory_sha256'] != ipins: raise ValueError('Original preview inventory chain changed')
    binding = {'source_building_links_sha256':'building_facade_links','source_level_context_sha256':'elevation_level_context',
               'source_facade_alignment_sha256':'facade_alignment','source_sheet_scale_sha256':'sheet_scale_evidence',
               'source_wall_return_corners_sha256':'wall_return_corners'}
    for value in reviews.values():
        for field,key in binding.items():
            if field in value and value[field] != digest(reviews[key]): raise ValueError('Original preview review chain changed')
    # Bind complete page sets, including deferred competitors, before using annotation controls.
    pages = {(p['document_sha256'],p['page']):p for p in source['pages']}
    for p in reviews['artwork_scale_controls']['pages']:
        if p['source_page_views_sha256'] != digest(pages[(p['document_sha256'],p['page'])]):
            raise ValueError('Complete preview page views required')
    return report, vr, inventories, source_views, reviews


def build(components, views, corpus, output, *, max_checks=100000):
    """Separate downstream review command; existing extraction/acceptance stays intact."""
    bounded_work(max_checks)
    components,views,corpus,output = map(Path,(components,views,corpus,output))
    report,vr,inventories,source_views,reviews = _verified_inputs(components,views,corpus)
    artwork=reviews['artwork_scale_controls']; returns=reviews['wall_return_corners']; levels=reviews['elevation_level_context']
    buildings=reviews['building_facade_links']; symbols=reviews['door_symbol_evidence']
    result={'version':VERSION,'status':'unplaced_source_facade_hypotheses_only', 'target_marker_checks':[], 'position_checks':[],
            'previews':[], 'source_crop_receipts':[], 'checks':0,
            'contract':{'component_report_sha256':file_hash(components/'component-report.json'),
                'view_report_sha256':file_hash(views/'view-report.json'), 'implementation_sha256':file_hash(Path(__file__)),
                'source_pdf_sha256':vr['contract']['source_sha256'], 'max_checks':max_checks,
                'pymupdf_version':pymupdf.VersionBind,'numpy_version':np.__version__,
                'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (automatic_facade_alignment,
                    automatic_opening_links,generation_cycles,reconstruction_evidence_queue)}},
            'physical_scale_verified':False,'world_placement_eligible':False,'accepted_physical_components':0,
            'world_geometry_additions':0,'training_labels_generated':0,
            'recipe':{'target_markers':'excluded target annotations check fixed non-target fit only; no refit',
                'positions':'both parities at independent original return-corner origin; no fit to opening',
                'bottom':'lower half of original jamb height through 0.25 nominal m below jamb ends; all bands at dark thresholds 96/128 with >=80% central-width support near original jamb ends',
                'surface':'zero-thickness original raster parent context, opening outline only; no aperture carve'},
            'unresolved':['Physical wall, aperture, base-band and floor roles', 'Independent physical scale and source construction state',
                'Complete exterior/roof boundary and wall thickness', 'Geographic registration and vertical datum']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks: raise OverflowError('facade_preview_work_budget')
    images={}; crop_cache={}
    try:
        result['target_marker_checks']=target_checks(artwork,charge)
        target_map={(c['pair_id'],tuple(c['key'])):c for c in result['target_marker_checks']}
        pairs={p['id']:p for p in artwork['pairs']}; records={r['id']:r for r in buildings['frames']}
        lv={v['view_id']:v for v in levels['views']}; families={f['id']:f for v in levels['views'] for f in v['families']}
        previous={p['id']:p for d in returns['diagnostics'] for p in d['position_comparisons']}
        by_return={digest(d):d for d in returns['diagnostics']}
        links=defaultdict(list)
        for link in symbols['conditional_position_links']:
            if link['source_position_comparison_sha256']!=digest(previous[link['source_position_comparison_id']]):
                raise ValueError('Original symbol position link changed')
            links[link['source_position_comparison_id']].append(link)
        for diagnostic in artwork['diagnostics']:
            charge(); pair=pairs[diagnostic['pair_id']]; old=by_return[diagnostic['source_return_diagnostic_sha256']]
            record=records[old['facade_record_id']]; target=record['target_elevation_view_ids'][0]
            check=target_map.get((pair['id'],tuple(record['target_view_key_candidate'])))
            if check is None or check['status']!='fixed_non_target_layout_agrees_at_target_annotation':continue
            inverse=np.asarray(pair['subject_to_reference_linear_row_matrix']); axis=np.asarray(diagnostic['source_axis_pdf_native'])@inverse
            axis/=np.linalg.norm(axis); origin=diagnostic['source_points_pdf_native'][0]; unit=diagnostic['nominal_metres_per_pdf_point']
            def project(p):return float((np.asarray(p)-origin)@inverse@axis*unit)
            inv=inventories[record['plan_view_id']]; gaps={digest(g):g for g in inv['plan_gap_review']['gaps']}
            for width in diagnostic['width_comparisons']:
                if width['status']!='all_witness_extent_widths_compatible':continue
                parent=families[width['parent_family_review_id']]; level=lv[target]
                matrix=level['pixel_edge_to_source_display_matrix']; scale=inventories[target]['nominal_metres_per_pdf_point']
                for prior in old['position_comparisons']:
                    charge()
                    if prior['parent_family_review_id']!=parent['id'] or not links[prior['id']]:continue
                    gap=gaps[prior['source_gap_projection']['source_gap_sha256']]; points=gap['gap_endpoints_pdf_native']
                    projection={'id':gap['id'],'nominal_plan_position_interval_m':sorted(project(p) for p in points)}
                    extent={'id':diagnostic['source_corner_pair_id'],'nominal_plan_position_interval_m':[0.,diagnostic['nominal_span_m']]}
                    child=families[prior['child_family_review_id']]
                    for reverse in (False,True):
                        position=compare_position(extent,parent,child,projection,matrix,scale,reverse,charge)
                        position.update(source_artwork_diagnostic_sha256=digest(diagnostic),source_gap_sha256=digest(gap),
                            source_gap_endpoints_pdf_native=points,source_origin_pdf_native=origin,source_axis_pdf_native=diagnostic['source_axis_pdf_native'],
                            fixed_pair_id=pair['id'], source_previous_position_id=prior['id'])
                        result['position_checks'].append(position)
                        if position['status']!='all_witness_positions_compatible':continue
                        datum=level['relative_reference']['datum_y_display_points']
                        for outer in parent['witnesses']:
                            for inner in child['witnesses']:
                                charge(); bounds=inner['source_bounds_pixels']; key=(target,tuple(bounds))
                                if key not in crop_cache:
                                    source,view=source_views[target]; pdf=corpus/'files'/(source['document_sha256']+'.pdf')
                                    display=[bounds[0]*matrix[0]+matrix[4],bounds[1]*matrix[3]+matrix[5],
                                             bounds[2]*matrix[0]+matrix[4],bounds[3]*matrix[3]+matrix[5]]
                                    w=display[2]-display[0];h=display[3]-display[1]
                                    clip=pymupdf.Rect(display[0]-.5*w,display[1]-.25*h,display[2]+.5*w,display[3]+.5*h)
                                    with pymupdf.open(pdf) as doc:
                                        page=doc[source['page']-1]
                                        if not page.rect.contains(clip):raise ValueError('Whole original bottom context required')
                                        if math.ceil(clip.width*4+2)*math.ceil(clip.height*4+2)>2000000:raise OverflowError('facade_preview_crop_budget')
                                        pix=page.get_pixmap(matrix=pymupdf.Matrix(4,4),clip=clip,alpha=False,colorspace=pymupdf.csGRAY)
                                        png=pix.tobytes('png'); gray=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)
                                        bottom=bottom_bands(gray,display,[4.,-pix.x,-pix.y],scale,charge)
                                        rid=digest([VERSION,target,bounds]);name='crops/'+rid+'.png';images[name]=png
                                        receipt={'id':rid,'file':name,'png_sha256':hashlib.sha256(png).hexdigest(),
                                            'document_sha256':source['document_sha256'],'page':source['page'], 'view_id':target,
                                            'source_child_bounds_pixels':bounds, 'display_clip_points':list(clip),
                                            'size_pixels':[pix.width,pix.height],'zoom':4.,'colorspace':'DeviceGray','alpha':False,
                                            'pixel_edge_to_display_matrix':[.25,0.,0.,.25,pix.x/4,pix.y/4]}
                                    if file_hash(pdf)!=source['document_sha256']:raise ValueError('Original preview PDF changed')
                                    result['source_crop_receipts'].append(receipt);crop_cache[key]=(rid,bottom)
                                rid,bottom=crop_cache[key]
                                mesh=context_mesh(outer['source_bounds_pixels'],bounds,matrix,scale,datum)
                                row={'caption':inventories[target]['caption'],'view_id':target,'fixed_pair_id':pair['id'],
                                     'source_artwork_diagnostic_sha256':digest(diagnostic),'source_position_check_id':position['id'],
                                     'source_parent_witness_sha256':digest(outer),'source_child_witness_sha256':digest(inner),
                                     'source_parent_bounds_pixels':outer['source_bounds_pixels'],'source_child_bounds_pixels':bounds,
                                     'source_symbol_link_sha256':[digest(link) for link in links[prior['id']]],
                                     'source_crop_receipt_id':rid,'source_marker_check_id':check['id'],'bottom_review':bottom,
                                     'mesh':mesh,'source_state_claim':inventories[target]['printed_claim'].get('printed_state','unspecified'),
                                     'outside_non_target_control_hull':diagnostic['outside_all_control_hull'],
                                     'source_geometry_changed':False,'physical_opening_verified':False}
                                interval=bottom['candidate_bottom_display_interval']
                                row['base_band_relative_to_printed_level_nominal_m']=None if interval is None else sorted((datum-v)*scale for v in interval)
                                row['id']=digest([VERSION,row]);result['previews'].append(row)
                                if len(result['previews'])>256:raise OverflowError('facade_preview_alternative_budget')
    except OverflowError as error:
        result.update(status='facade_preview_budget_withheld',reason=str(error),target_marker_checks=[],position_checks=[],previews=[],source_crop_receipts=[])
        images={}
    # Recheck the complete source pack and PDFs before publishing any result/crops.
    _verified_inputs(components,views,corpus)
    if file_hash(components/'component-report.json')!=result['contract']['component_report_sha256'] or file_hash(views/'view-report.json')!=result['contract']['view_report_sha256']:
        raise ValueError('Preview source contract changed during build')
    result['counts']={'target_checks':len(result['target_marker_checks']),
        'target_annotations_agree':sum(c['status']=='fixed_non_target_layout_agrees_at_target_annotation' for c in result['target_marker_checks']),
        'position_checks':len(result['position_checks']),'positions_compatible':sum(p['status']=='all_witness_positions_compatible' for p in result['position_checks']),
        'source_linked_alternatives':len(result['previews']),'unique_source_crops':len(images),
        'unique_meshes':len({digest(p['mesh']) for p in result['previews']}),
        'base_band_candidate_crops':sum(bottom['status']=='cross_threshold_source_base_band_candidate' for _,bottom in crop_cache.values()) if images else 0}
    if sum(len(v) for v in images.values())+len(json.dumps(result).encode())>64000000:raise ValueError('Preview output budget exceeded')
    root=output/digest(result['contract'])
    if root.exists():
        saved=_json(root/'facade-preview.json')
        if digest(saved)!=digest(result):raise ValueError('Existing facade preview changed')
        for name,png in images.items():
            if (root/name).read_bytes()!=png:raise ValueError('Existing original preview crop changed')
    else:
        root.mkdir(parents=True)
        for name,png in images.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(png)
        atomic_json(root/'facade-preview.json',result)
    return {**result,'directory':str(root)}
