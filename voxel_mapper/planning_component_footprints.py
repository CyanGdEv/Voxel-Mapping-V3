"""Fine source-linework boundaries around visible printed component labels.

Search bounds select complete paint primitives, never clip or close geometry.
Candidates remain unregistered source hypotheses, not accepted park buildings.
"""
from concurrent.futures import CancelledError
import json
import math

from shapely.geometry import shape

from . import ordinary_surfaces, planning_outline_semantics, planning_view_geometry
from .building_spec import digest

VERSION='planning-component-boundaries-v1'
SEARCH_MARGIN_POINTS=144
LIMITS={'max_component_labels':32,'max_native_candidates':10000,
        'max_native_points':200000,'max_outlines':500,'max_output_bytes':8000000}


def page_candidates(page, sha, number, inventory, associations, *, options=None,
                    cancelled=lambda:False):
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):
        raise ValueError('Known component boundary limits required')
    limits={**LIMITS,**options}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):
        raise ValueError('Lower-only component boundary limits required')
    if limits['max_output_bytes']<16384:raise ValueError('Component boundary metadata needs 16384 bytes')
    if (not isinstance(associations,dict) or associations.get('version')!=planning_outline_semantics.VERSION
            or associations.get('document_sha256')!=sha or associations.get('page')!=number
            or associations.get('source_inventory_sha256')!=digest(inventory)
            or associations.get('inventory_complete') is not True
            or inventory.get('inventory_complete') is not True
            or page.number+1!=number):
        raise ValueError('Complete same-source outline associations required')
    def check():
        if cancelled():raise CancelledError('Component boundary recovery cancelled')
    check()
    labels=[r for r in associations['labels']
            if r['claim']['role']=='building' and r['claim']['scope']=='component']
    visible=[r for r in labels if r['glyph_screen']['status']=='raster_consistent_candidate']
    result={'version':VERSION,'document_sha256':sha,'page':number,
        'coordinate_frame':'pdf_native_points_y_up','limits':limits,
        'source_inventory_sha256':digest(inventory),'source_associations_sha256':digest(associations),
        'status':'no_visible_component_labels','analysis_complete':True,'candidates':[],
        'boundary_decisions':[],
        'component_labels':len(labels),'visible_component_labels':len(visible),
        'physical_identity_verified':False,'view_scope_verified':False,
        'registration_verified':False,'scale_verified':False,'world_placement_eligible':False,
        'training_labels_generated':0,'model_weights_updated':False,
        'world_geometry_additions':0,'geometric_accuracy':None,
        'limitations':['Search margin is a PDF scan region, not a physical component or view extent.',
            'A unique visible component label inside closed source linework is a boundary hypothesis only.',
            'Source state, exterior-wall interpretation, scale, heights and park alignment remain unresolved.',
            'No endpoint snapping, gap repair, nearest/smallest enclosure selection or guessed geometry.']}
    def finish(reason=None):
        if reason:result.update(status='component_boundaries_withheld',analysis_complete=False,
                                reason=reason,candidates=[])
        result['summary']={'component_boundary_candidates':len(result['candidates']),
            'component_labels':len(labels),'visible_component_labels':len(visible),
            'unresolved_component_labels':len(labels)-len(result['candidates'])}
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            # Keep bounded diagnostics; no successful partial candidate set.
            for key in ('fine_associations','fine_inventory_records','extraction','recovery'):
                result.pop(key,None)
            result.update(status='component_boundaries_withheld',analysis_complete=False,
                reason='component_output_budget_exceeded',candidates=[],boundary_decisions=[])
            result['summary']['component_boundary_candidates']=0
            result['summary']['unresolved_component_labels']=len(labels)
        check();return result
    if len(labels)>limits['max_component_labels']:return finish('component_label_budget_exceeded')
    if not visible:return finish()
    # Bound the scan using visible native component labels, without assigning
    # any physical role to that rectangle or intersecting source primitives.
    bounds=[shape(r['geometry_pdf_native']).bounds for r in visible]
    if any(not all(math.isfinite(v) for v in b) for b in bounds):
        raise ValueError('Finite native component label bounds required')
    frame=planning_view_geometry._native_frame(page).bounds
    region=[max(frame[0],min(b[0] for b in bounds)-SEARCH_MARGIN_POINTS),
            max(frame[1],min(b[1] for b in bounds)-SEARCH_MARGIN_POINTS),
            min(frame[2],max(b[2] for b in bounds)+SEARCH_MARGIN_POINTS),
            min(frame[3],max(b[3] for b in bounds)+SEARCH_MARGIN_POINTS)]
    extraction_options={'region_native_points':region,'min_line_length_points':.25,
        'max_candidates':limits['max_native_candidates'],'max_total_points':limits['max_native_points'],
        'max_paths':100000,'max_scan_paths':100000,'regional_fallback':False}
    result.update(search_region_pdf_native=region,search_margin_pdf_points=SEARCH_MARGIN_POINTS,
                  extraction_options=extraction_options)
    check()
    try:
        faces,extraction,recovery,covered=ordinary_surfaces.closed_source_faces(page,sha,number,
            extraction_options=extraction_options,recovery_options={'max_face_provenance':2048})
    except (ValueError,RuntimeError,OverflowError) as error:
        result['error']=str(error)[:512]
        return finish('fine_source_geometry_failed')
    check()
    fine_inventory=ordinary_surfaces._outline_inventory(faces,extraction,recovery,limits['max_outlines'])
    result.update(extraction=extraction,recovery=recovery,covered_boundaries_withheld=covered,
        fine_inventory_sha256=digest(fine_inventory),
        fine_inventory_records=[{'candidate_id':r['candidate_id'],'source_record_sha256':r['source_record_sha256']}
                                for r in fine_inventory['records']])
    if not fine_inventory['inventory_complete']:return finish(fine_inventory['reason'])
    fine=planning_outline_semantics.page_candidates(page,sha,number,fine_inventory,cancelled=cancelled)
    result['fine_associations']=fine
    if not fine['inventory_complete']:return finish('fine_label_associations_incomplete')
    by_id={r['candidate_id']:r for r in fine_inventory['records']}
    label_by_id={r['id']:r for r in fine['labels']}
    for outline in fine['outlines']:
        check()
        decision={'candidate_id':outline['candidate_id'],'label_ids':outline['label_ids'],
                  'status':'withheld','reason':outline['status']}
        result['boundary_decisions'].append(decision)
        if (outline['status']!='visible_label_enclosure_hint'
                or outline['source_role_hint']!='building' or outline['component_label_count']!=1):continue
        component=[label_by_id[k] for k in outline['label_ids']
                   if label_by_id[k]['claim']['scope']=='component']
        if len(component)!=1:continue
        record=by_id[outline['candidate_id']]
        if shape(record['candidate']['geometry']).interiors:
            decision['reason']='interior_rings_require_component_boundary_interpretation'
            continue
        label=component[0]
        result['candidates'].append({'id':digest([VERSION,sha,number,record['candidate_id'],label['id']]),
            'status':'source_component_boundary_hypothesis','document_sha256':sha,'page':number,
            'coordinate_frame':'pdf_native_points_y_up','geometry_pdf_native':record['candidate']['geometry'],
            'source_outline':record,'label':label,'association':outline,
            'physical_identity_verified':False,'world_placement_eligible':False,'geometric_accuracy':None})
        decision.update(status='source_component_boundary_hypothesis',reason=None)
    result['status']='source_component_boundary_candidates'
    return finish()
