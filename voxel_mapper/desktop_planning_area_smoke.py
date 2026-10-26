"""Full source-plan to saved local layout through real managed desktop jobs."""
import hashlib
import base64
import json
import math
from pathlib import Path

import pymupdf
from shapely.geometry import shape

from .desktop_runtime import DesktopRuntime, _wait, write_json
from .planning_area_pilot import VERSION
from .glyph_visibility import screen_architectural_span


# Original 748-byte synthetic TrueType program: A triangle and B rectangle.
_TRANSFORM_FONT='AAEAAAAKAIAAAwAgT1MvMkUhRDYAAAEoAAAAYGNtYXAADACVAAABkAAAADRnbHlmLwD8igAAAcwAAAAyaGVhZFm5pJwAAACsAAAANmhoZWEFegH2AAAA5AAAACRobXR4ArwAZAAAAYgAAAAIbG9jYQAMABkAAAHEAAAACG1heHAABQAGAAABCAAAACBuYW1lEn9neQAAAgAAAADDcG9zdAApACUAAALEAAAAKAABAAAAAQAA0+n7tF8PPPUAAwPoAAAAAHwlsIAAAAAAfCWwgABkAAAB9AK8AAAAAwACAAAAAAAAAAEAAAMg/zgAAAJYAGQAZAH0AAEAAAAAAAAAAAAAAAAAAAABAAEAAAADAAQAAQAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAwJYAZAABQAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAPz8/PwAAAEEAQgMg/zgAAAMgAMgAAAAAAAAAAAAAAAAAAAAgAAACWAAAAGQAZAAAAAIAAAADAAAAFAADAAEAAAAUAAQAIAAAAAQABAABAAAAQv//AAAAQf///8AAAQAAAAAAAAAAAAwAGQABAGQAAAH0ArwAAgAAMyEDZAGQyAK8AAABAGQAAAH0ArwAAwAAMyERIWQBkP5wArwAAAAAAAAKAH4AAQAAAAAAAQAQAAAAAQAAAAAAAgAHABAAAQAAAAAAAwAQAAAAAQAAAAAABAAQAAAAAQAAAAAABgAQAAAAAwABBAkAAQAgABcAAwABBAkAAgAOADcAAwABBAkAAwAgABcAAwABBAkABAAgABcAAwABBAkABgAgABdUcmFuc2Zvcm1GaXh0dXJlUmVndWxhcgBUAHIAYQBuAHMAZgBvAHIAbQBGAGkAeAB0AHUAcgBlAFIAZQBnAHUAbABhAHIAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAACQAJQ=='


def _check_text_transform(root):
    source=root/'native-transform-original.pdf'
    with pymupdf.open() as document:
        page=document.new_page(width=300,height=180)
        font=page.insert_font(fontname='fixture',fontbuffer=base64.b64decode(_TRANSFORM_FONT))
        document.xref_set_key(font,'BaseFont','/TransformFixture')
        anchor=pymupdf.Point(80,90)
        page.insert_text(anchor,'AB',fontname='fixture',fontsize=12,color=(1,0,0),
            morph=(anchor,pymupdf.Matrix(1.4,0,0,1,0,0)))
        document.save(source)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    with pymupdf.open(source) as document:
        page=document[0];screen=screen_architectural_span(page,page.get_texttrace()[0])
    proof=screen.get('source_text_transform',{});basis=proof.get('effective_font_basis_pdf_native',[])
    if (screen['status']!='raster_consistent_candidate' or len(basis)!=4
            or not math.isclose(basis[0]/basis[3],1.4,rel_tol=1e-6)
            or proof.get('encoded_glyph_count')!=2
            or hashlib.sha256(source.read_bytes()).hexdigest()!=before):
        raise ValueError('Original anisotropic glyph transform check failed')
    write_json(root/'original-text-transform.json',{'original_pdf_sha256':before,'screen':screen})


def make_source(path, *, wide=False):
    """Two buildings, joined paving and an intentionally disconnected path."""
    with pymupdf.open() as document:
        page=document.new_page(width=2384,height=1684)
        # Keep the previous native y-up coordinates and voxel-grid phase while
        # adding real ISO paper around the unchanged synthetic area.
        offset=page.rect.height-420
        for index,(rectangle,label,origin) in enumerate((
                ((60,80,160,180),'Shop',(80,110)),
                ((160,120,400,160),'Footpath',(210,145)),
                ((400,80,500,200),'Plaza',(420,110)),
                ((500,100,600,180),'Toilets',(520,130)),
                ((250,260,450,300),'Footpath',(300,285)))):
            x0,y0,x1,y1=rectangle
            if wide and label=='Toilets':
                x0+=1500;x1+=1500;y0-=1300;y1-=1300
                origin=(origin[0]+1500,origin[1]-1300)
            page.draw_rect((x0,y0+offset,x1,y1+offset))
            colour=((.65,.65,.65),(.55,.35,.2),(.7,0,0))[index%3]
            if label=='Shop':
                for text,position in (('COURTYARD',(80,110)),('TAVERN',(87,122)),('Building',(80,151))):
                    page.insert_text((position[0],position[1]+offset),text,fontsize=10,color=colour)
            else:
                page.insert_text((origin[0],origin[1]+offset),label,fontsize=10,color=colour)
        # A closed enclosure containing a split instruction and a separate
        # material word must not turn into an extra path or paving feature.
        page.draw_rect((850,80+offset,1200,180+offset))
        x=880
        for text in ('Path',' lowered',' and',' ground',' graded'):
            page.insert_text((x,110+offset),text,fontsize=10,color=(.7,0,0))
            x+=pymupdf.get_text_length(text,fontsize=10)
        page.insert_text((880,160+offset),'stone',fontsize=10,color=(.7,0,0))
        # Unclassified closed curves remain isolated from physical proposals.
        page.draw_circle((1400,110+offset),30)
        # A source ring assembled from separately painted curve/line operators
        # must be recovered for review without adding another paving feature.
        page.draw_bezier((1500,80+offset),(1550,50+offset),(1650,50+offset),(1700,80+offset))
        for a,b in (((1700,80),(1700,180)),((1700,180),(1500,180)),((1500,180),(1500,80))):
            page.draw_line((a[0],a[1]+offset),(b[0],b[1]+offset))
        page.insert_text((1550,130+offset),'stone',fontsize=10)
        # A longer original curve crosses every label window. Its separate
        # style-scoped review must retain the whole ring without exporting it.
        red=(1,0,0)
        page.draw_bezier((700,240+offset),(900,180+offset),(1100,180+offset),(1300,240+offset),color=red)
        for a,b in (((1300,240),(1300,320)),((1300,320),(700,320)),((700,320),(700,240))):
            page.draw_line((a[0],a[1]+offset),(b[0],b[1]+offset),color=red)
        page.insert_text((980,280+offset),'stone',fontsize=10)
        page.insert_text((60,360+offset),'Site Plan Proposed showing Buildings and Paths',fontsize=12)
        page.insert_text((80,390+offset),'1/200 @ A1',fontsize=12)
        page.insert_text((80,405+offset),'1/400 @ A3',fontsize=12)
        document.save(path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()



def _check_hatch_regions(root):
    from .planning_hatch_regions import page_review
    with pymupdf.open() as doc:
        page=doc.new_page(width=800,height=400)
        page.insert_text((650,85),'New Paving with levels',fontsize=8)
        page.insert_text((650,145),'Existing Paving with levels',fontsize=8)
        tile=doc.get_new_xref()
        doc.update_object(tile,'<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 8 8] /XStep 8 /YStep 8 /Resources << >> >>')
        doc.update_stream(tile,b'0.5 g 0 0 8 8 re f')
        resource=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
        doc.xref_set_key(resource,'Pattern',f'<< /P1 {tile} 0 R >>')
        paint=doc.get_new_xref();doc.update_object(paint,'<< >>')
        doc.update_stream(paint,b'q /Pattern cs /P1 scn 580 300 60 30 re f 20 100 m 20 200 300 200 300 100 c 300 50 l 20 50 l h f Q q 0.9 0.8 0.7 rg 580 240 60 30 re f 340 50 m 540 50 l 540 200 l 340 200 l 340 50 l 400 100 l 400 130 l 430 130 l 430 100 l 400 100 l 340 50 l h f* Q')
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [paint]+page.get_contents())+']')
        path=root/'synthetic-hatch-original.pdf';doc.save(path)
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as doc:review=page_review(doc[0],sha,1)
    if (not review['analysis_complete'] or review['summary']['legend_associated_paving_regions']!=2
            or review['summary']['existing_paving_regions']!=1 or review['summary']['proposed_paving_regions']!=1
            or review['work']['source_passes']!=2
            or shape(next(r['geometry'] for r in review['records'] if r['legend_claim'] and r['legend_claim']['printed_state']=='existing')).area!=29100
            or review['summary']['curved_paving_regions']!=1 or review['world_geometry_additions']
            or review['world_placement_eligible'] or review['training_labels_generated']
            or hashlib.sha256(path.read_bytes()).hexdigest()!=sha):
        raise ValueError('Original source hatch and paving legend checks failed')
    from .planning_gap_boundaries import review as gap_review
    gaps=gap_review(review)
    if (not gaps['analysis_complete'] or gaps['summary']['assumed_rock_boundaries']!=1
            or gaps['records'][0]['material']!='rock' or gaps['records'][0]['height_m'] is not None
            or gaps['records'][0]['interior_filled_with_rock'] or gaps['world_geometry_additions']):
        raise ValueError('User-default rock gap policy check failed')
    write_json(root/'gap-boundary-review.json',gaps)
    write_json(root/'source-hatch-review.json',review)


def _check_reference_geometry_world(root,runtime):
    """Actual original PDF -> pilot -> rich world -> native saved-state checks."""
    source=root/'reference-boundary-original.pdf'
    with pymupdf.open() as doc:
        page=doc.new_page(width=2384,height=1684);tan=(.9,.8,.7)
        for outer,inner in (((100,100,350,350),(130,130,320,320)),((500,100,850,450),(570,170,780,380))):
            drawing=page.new_shape();drawing.draw_rect(outer);drawing.draw_rect(inner)
            drawing.finish(fill=tan,color=None,even_odd=True);drawing.commit()
        page.draw_rect((1050,100,1150,200),fill=(1,1,1));page.insert_text((1070,150),'Shop',fontsize=10)
        for _ in range(2):page.draw_rect((1000,400,1120,500),fill=(1,1,1))
        page.insert_text((1020,450),'Maintenance',fontsize=10)
        page.draw_rect((2100,90,2160,120),fill=tan,color=None)
        page.insert_text((2170,110),'Existing Paving with levels',fontsize=8)
        page.insert_text((60,1580),'Site Plan Proposed showing Buildings and Paths',fontsize=12)
        page.insert_text((80,1610),'1/200 @ A1',fontsize=12)
        page.insert_text((80,1630),'1/400 @ A3',fontsize=12)
        doc.save(source)
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    config={'version':VERSION,'area_id':'reference-boundary-style-fixture',
        'application_references':['synthetic-fixture'],'source_directory':str(root),
        'development_exposure':'previously_inspected','documents':[{'file':source.name,'sha256':sha,
            'title':'Original paving and narrow-path fixture','role':'site-plan','drawing_state':'proposed',
            'application_reference':'synthetic-fixture'}]}
    write_json(root/'reference-boundary-pilot.json',config)
    source_id=runtime.submit('planning_source_pilot',root/'reference-boundary-pilot.json')
    source_job=_wait(runtime,source_id)
    if source_job['status']!='completed':raise ValueError('Reference geometry source pilot failed: '+str(source_job.get('error')))
    export_id=runtime.submit_planning_area_world_preview(source_id);job=_wait(runtime,export_id)
    if job['status']!='completed':raise ValueError('Reference geometry world export failed: '+str(job.get('error')))
    result=job['result']
    if (result.get('version')!='planning-geometry-world-preview-v1' or result.get('fence_columns',0)<1
            or result.get('rock_columns',0)<1 or not result['saved_geometry_validation']['native_block_states_verified']
            or not result['archive_validation']['saved_world_reopened'] or result['rock_paving_cell_overlap']!=0
            or result.get('building_marker_mode')!='2d_boundary_only' or result.get('building_boundary_candidates',0)<2
            or result['world_placement_eligible'] or result['model_weights_updated']
            or hashlib.sha256(source.read_bytes()).hexdigest()!=sha):
        raise ValueError('Reference-style rocks and narrow-path oak fences failed verification')
    write_json(root/'reference-geometry-world.json',{'status':'passed','source_pdf_sha256':sha,
        'source_job_id':source_id,'export_job_id':export_id,'result':result})
    return result

def _check_plan_marking_palette(root):
    from . import bedrock,planning_plan_markings
    from .planning_world_preview import _verify_archive
    from .building_spec import digest
    preset=planning_plan_markings.profile()
    from .planning_theming_notes import parse as theming_note
    first=theming_note('Theming Envelope 1 to 195.8 with queuing below')
    second=theming_note('Theming Envelope 2 to 196.8')
    if (not first['queueing_below_stated'] or second['queueing_below_stated']
            or first['queue_route_geometry'] is not None or first['upper_level_is_building_height']
            or len([r for r in preset['features'] if r['role']=='theming_envelope'])!=2
            or len([r for r in preset['features'] if r['role']=='queue_area' and r['queue_area_context']['below_feature_key']=='theming-envelope-1'])!=1):
        raise ValueError('Packaged layered theming semantics failed verification')
    from . import courtyard_plan_expansion
    courtyard_features,courtyard_pose=courtyard_plan_expansion.geometry()
    if len(courtyard_features)!=11 or not courtyard_pose['printed_scale_retained'] or courtyard_pose['independent_registration_verified']:
        raise ValueError('Packaged existing courtyard profile failed verification')
    colours=('orange_wool','blue_wool','brown_wool','purple_wool','yellow_wool')
    directory=root/'plan-marking-palette';directory.mkdir()
    source=directory/'voxels.jsonl'
    source.write_text(''.join(json.dumps({'x':i,'y':0,'z':0,'kind':'terrain','material':colour})+'\n' for i,colour in enumerate((*colours,'grass_block'))))
    report={'voxel_size_m':1,'vertical_datum':'STUDY_ZERO','crs':None,'spawn_local_xyz_m':[len(colours),1,0]}
    exported=bedrock.export_world(source,directory,report,max_blocks=128,ground_depth=3)
    archive=_verify_archive(directory/exported['file'],directory/'bedrock-world',exported,lambda:False)
    if not archive['saved_world_reopened'] or exported['round_trip_validation']!='all written blocks and all unwritten air cells verified':
        raise ValueError('Packaged user wool palette failed saved-world verification')
    write_json(directory/'validation.json',{'profile_sha256':digest(preset),'materials':colours,'archive_validation':archive,'world':exported})
    return digest(preset)

def run(output):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Fresh planning area smoke output required')
    root.mkdir(parents=True)
    plan_profile_pin=_check_plan_marking_palette(root)
    _check_text_transform(root)
    _check_hatch_regions(root)
    source=root/'synthetic-area-original.pdf';sha=make_source(source)
    config={'version':VERSION,'area_id':'synthetic-shared-plan-area',
        'application_references':['synthetic-fixture'],'source_directory':str(root),
        'development_exposure':'previously_inspected','documents':[{
            'file':source.name,'sha256':sha,'title':'Synthetic area plan',
            'role':'floor-plan','drawing_state':'proposed','application_reference':'synthetic-fixture'}]}
    write_json(root/'pilot.json',config)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        reference_world=_check_reference_geometry_world(root,runtime)
        pilot_id=runtime.submit('planning_source_pilot',root/'pilot.json')
        pilot=_wait(runtime,pilot_id,timeout=120);runtime._futures[pilot_id].result(timeout=10)
        if pilot['status']!='completed':raise ValueError('Managed source-plan extraction failed: '+str(pilot.get('error')))
        layouts=runtime.planning_area_layouts(pilot_id)
        if len(layouts)!=1:raise ValueError('Expected one supported same-plan layout')
        layout=json.loads(Path(layouts[0]['layout_path']).read_text(encoding='utf-8'))
        scale=layout['source_context'].get('scale_resolution',{})
        if (scale.get('basis')!='original_page_iso_paper_match'
                or scale.get('selected_paper_size')!='A1'
                or scale.get('printed_scale_denominator')!=200):
            raise ValueError('Original paper-qualified site plan scale was not exercised')
        evidence_path=Path(pilot['output_directory'])/pilot['result']['pages'][0]['evidence_file']
        page_evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
        curves=page_evidence.get('curved_boundary_review',{})
        if (not curves.get('analysis_complete') or len(curves.get('records',[]))!=1
                or curves['world_placement_eligible'] is not False
                or len(curves['records'][0]['source_paint_witnesses'][0]['operators_pdf_native'])!=4
                or curves['records'][0]['curve_approximation']['chord_error_bound_pdf_points']>.05):
            raise ValueError('Original closed-curve review isolation was not exercised')
        network=page_evidence.get('curve_network_review',{})
        if (not network.get('analysis_complete') or len(network.get('records',[]))!=1
                or network['world_placement_eligible'] is not False
                or len(network['records'][0]['candidate']['source_edges'])!=4
                or network['curve_interior_intersection_noding_performed'] is not False):
            raise ValueError('Original open curved network recovery was not exercised')
        complete_plan=page_evidence.get('complete_curve_scope_plan',{})
        complete_review=page_evidence.get('complete_curve_scope_review',{})
        if (not complete_plan.get('analysis_complete') or complete_plan.get('anchor_count')!=1
                or not complete_review.get('analysis_complete') or len(complete_review.get('records',[]))!=1
                or not complete_review['complete_anchor_coverage'][0]['eligible_subpaths_retained']
                or complete_review['physical_role_inferred_from_style'] is not False):
            raise ValueError('Complete long curved source scope recovery was not exercised')
        names=[r for r in page_evidence['outline_semantics']['labels']
            if r['status']=='qualified_building_name_withheld']
        if (len(names)!=1 or names[0]['name_context']['name_text']!='COURTYARD TAVERN'
                or names[0]['name_context']['suffix']['glyph_screen']['status']!='raster_consistent_candidate'):
            raise ValueError('Original building-name qualifier was not exercised')
        surface_evidence=page_evidence['surface_footprints']
        notes=[r for r in page_evidence['outline_semantics']['labels']
            if r['status']=='annotation_fragment_withheld']
        if (len(notes)!=1 or notes[0]['annotation_context']['text']!='Path lowered and ground graded'
                or notes[0]['annotation_context']['all_parts_visible'] is not True
                or not any(r['reason']=='annotation_fragment_context_withheld'
                           for r in surface_evidence['boundary_decisions'])):
            raise ValueError('Whole native annotation withholding was not exercised')
        regional=surface_evidence['extraction']
        if (regional.get('strategy')!='per_label_native_windows'
                or regional.get('region_schedule')!='coalesced_shared_native_union'
                or regional.get('source_path_passes')!=1
                or len(regional.get('source_windows',[]))<2
                or not 1<=len(regional.get('regions',[]))<len(regional['source_windows'])
                or any(not region['inventory_complete'] for region in regional['regions'])):
            raise ValueError('Bounded regional surface recovery was not exercised')
        roles=[row['role'] for row in layout['candidates']]
        if roles.count('building')!=2 or sum(role in ('path','plaza','surface') for role in roles)!=3:
            raise ValueError('Automatic area outline inventory changed: '+str(roles))
        if not layout['shared_frame'] or any(row['height_m'] is not None for row in layout['candidates']):
            raise ValueError('Missing shared frame or invented building heights')
        screens=[]
        for candidate in layout['candidates']:
            for evidence in candidate['source_evidence']:
                semantic=evidence['semantic_evidence']
                labels=semantic.get('labels',[])+([semantic['label']] if 'label' in semantic else [])
                screens.extend(label.get('glyph_screen',{}) for label in labels)
        if not screens or any(screen.get('source_colour_support')!='original_rgb_over_white_projection' for screen in screens):
            raise ValueError('Original coloured area labels were not independently screened')
        buildings=sorted((shape(row['geometry_nominal_local']) for row in layout['candidates']
                          if row['role']=='building'),key=lambda geometry:geometry.centroid.x)
        expected_offset=440*200*.0254/72
        if not math.isclose(buildings[1].centroid.x-buildings[0].centroid.x,expected_offset,abs_tol=1e-9):
            raise ValueError('Independent source spacing was lost during area assembly')
        export_id=runtime.submit_planning_area_world_preview(pilot_id)
        exported=_wait(runtime,export_id,timeout=180);runtime._futures[export_id].result(timeout=10)
        if exported['status']!='completed':raise ValueError('Managed area world export failed: '+str(exported.get('error')))
        result=exported['result'];pack=Path(exported['output_directory'])
        connectivity=result.get('saved_grid_paving_connectivity',{})
        if (connectivity.get('component_count')!=2 or connectivity.get('paving_cells')!=149
                or connectivity.get('saved_display_cells_verified') is not True
                or connectivity.get('saved_display_headroom_verified') is not True
                or connectivity.get('saved_paving_membership_verified') is not True):
            raise ValueError('Saved connected plaza/path or isolated path changed')
        if result.get('world_placement_eligible') or result.get('model_weights_updated') or result.get('training_labels_generated'):
            raise ValueError('A layout preview changed physical acceptance or learning')
        for name,pin in result['output_sha256'].items():
            if hashlib.sha256((pack/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Area preview output checksum mismatch')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:
            raise ValueError('Area original changed during managed export')
        # A second original full-page PDF exceeds both the old span and area
        # limits. Relocate only a synthetic building before drawing the PDF;
        # the managed pipeline still discovers every polygon and scale itself.
        wide_source=root/'synthetic-wide-area-original.pdf'
        wide_sha=make_source(wide_source,wide=True)
        wide_config={**config,'area_id':'synthetic-complete-tiled-area',
            'documents':[{**config['documents'][0],'file':wide_source.name,'sha256':wide_sha}]}
        write_json(root/'wide-pilot.json',wide_config)
        wide_pilot_id=runtime.submit('planning_source_pilot',root/'wide-pilot.json')
        wide_pilot=_wait(runtime,wide_pilot_id,timeout=120)
        runtime._futures[wide_pilot_id].result(timeout=10)
        if wide_pilot['status']!='completed':
            raise ValueError('Managed wide source-plan extraction failed: '+str(wide_pilot.get('error')))
        wide_layouts=runtime.planning_area_layouts(wide_pilot_id)
        if len(wide_layouts)!=1:raise ValueError('Expected one complete wide plan layout')
        wide_layout=json.loads(Path(wide_layouts[0]['layout_path']).read_text(encoding='utf-8'))
        wide_buildings=sorted((shape(row['geometry_nominal_local']) for row in wide_layout['candidates']
            if row['role']=='building'),key=lambda geometry:geometry.centroid.x)
        if (len(wide_buildings)!=2
                or not math.isclose(wide_buildings[1].centroid.x-wide_buildings[0].centroid.x,
                    1940*200*.0254/72,abs_tol=1e-9)
                or not math.isclose(wide_buildings[1].centroid.y-wide_buildings[0].centroid.y,
                    1290*200*.0254/72,abs_tol=1e-9)):
            raise ValueError('Wide plan source spacing was cropped, rescaled or repositioned')
        wide_export_id=runtime.submit_planning_area_world_preview(wide_pilot_id)
        wide_exported=_wait(runtime,wide_export_id,timeout=180)
        runtime._futures[wide_export_id].result(timeout=10)
        if wide_exported['status']!='completed':
            raise ValueError('Managed complete tiled export failed: '+str(wide_exported.get('error')))
        wide_result=wide_exported['result']
        partition=wide_result['platform_partition']
        wide_saved=wide_result['saved_grid_paving_connectivity']
        if (partition['section_count']!=2 or partition['platform_cells']<=16384
                or partition['native_write_attempts']>100000
                or len(wide_result['candidate_display_counts'])!=5
                or wide_saved['paving_cells']!=149 or wide_saved['component_count']!=2
                or wide_saved.get('saved_complete_platform_verified') is not True
                or not all(t['verified'] for t in wide_saved['saved_sections'])
                or wide_result['archive_validation']['saved_world_reopened'] is not True
                or wide_result['world_placement_eligible'] or wide_result['model_weights_updated']):
            raise ValueError('Complete bounded tiled preview or retained features changed')
        for name,pin in wide_result['output_sha256'].items():
            if hashlib.sha256((Path(wide_exported['output_directory'])/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Wide preview output checksum mismatch')
        if hashlib.sha256(wide_source.read_bytes()).hexdigest()!=wide_sha:
            raise ValueError('Wide original changed during managed export')
        summary=runtime.store.summary()
        if summary['feedback_records'] or summary['checkpoints']:
            raise ValueError('Area preview changed reviewed model memory')
    finally:runtime.close(wait=True)
    reopened=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if reopened.store.job(export_id)['result']!=result or reopened.store.job(pilot_id)['status']!='completed':
            raise ValueError('Area extraction and export did not survive restart')
        if reopened.store.job(wide_export_id)['result']!=wide_result:
            raise ValueError('Tiled complete area export did not survive restart')
    finally:reopened.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','original_pdf_sha256':sha,
        'source_plan_job':pilot,'area_world_job':exported,'building_footprint_markers':2,
        'path_plaza_candidates':3,'shared_frame_verified':True,'source_and_output_hashes_verified':True,
        'coloured_original_labels_verified':True,
        'regional_surface_windows_verified':True,
        'coalesced_shared_regions_verified':True,
        'original_paper_scale_verified':True,
        'original_text_transform_verified':True,
        'original_building_name_context_verified':True,
        'whole_native_annotation_context_verified':True,
        'original_closed_curve_review_verified':True,
        'open_curve_network_recovery_verified':True,
        'complete_long_curve_scope_verified':True,
        'source_hatch_legend_regions_verified':True,
        'existing_solid_paving_verified':True,
        'source_fill_rule_holes_verified':True,
        'assumed_rock_gap_policy_verified':True,
        'reference_geometry_world_verified':True,
        'narrow_path_oak_fences_verified':True,
        'rock_reference_style_verified':True,
        'additional_2d_building_boundaries_verified':True,
        'plan_marking_wool_palette_verified':True,
        'theming_queueing_below_semantics_verified':True,
        'user_identified_queue_area_profile_verified':True,
        'existing_courtyard_expansion_profile_verified':True,
        'reviewed_plan_marking_profile_sha256':plan_profile_pin,
        'reference_world_building_boundaries':reference_world['building_boundary_candidates'],
        'reference_world_rock_columns':reference_world['rock_columns'],
        'reference_world_fence_columns':reference_world['fence_columns'],
        'complete_tiled_area_verified':True,'wide_original_pdf_sha256':wide_sha,
        'wide_area_world_job':wide_exported,'wide_area_sections':partition['section_count'],
        'wide_area_platform_cells':partition['platform_cells'],
        'wide_area_native_write_attempts':partition['native_write_attempts'],
        'independent_building_centroid_spacing_m':expected_offset,
        'saved_paving_components':2,'saved_paving_cells':149,
        'persistent_restart_verified':True,'real_park_accuracy_assessed':False,
        'world_placement_eligible':False,'training_labels_generated':0,'model_weights_updated':False}
    write_json(root/'planning-area-smoke.json',receipt)
    return receipt
