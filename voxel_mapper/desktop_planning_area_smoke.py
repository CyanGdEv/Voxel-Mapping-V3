"""Full source-plan to saved local layout through real managed desktop jobs."""
import hashlib
import json
import math
from pathlib import Path

import pymupdf
from shapely.geometry import shape

from .desktop_runtime import DesktopRuntime, _wait, write_json
from .planning_area_pilot import VERSION


def make_source(path):
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
            page.draw_rect((x0,y0+offset,x1,y1+offset))
            page.insert_text((origin[0],origin[1]+offset),label,fontsize=10,
                color=((.65,.65,.65),(.55,.35,.2),(.7,0,0))[index%3])
        page.insert_text((60,360+offset),'Site Plan Proposed showing Buildings and Paths',fontsize=12)
        page.insert_text((80,390+offset),'1/200 @ A1',fontsize=12)
        page.insert_text((80,405+offset),'1/400 @ A3',fontsize=12)
        document.save(path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(output):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Fresh planning area smoke output required')
    root.mkdir(parents=True)
    source=root/'synthetic-area-original.pdf';sha=make_source(source)
    config={'version':VERSION,'area_id':'synthetic-shared-plan-area',
        'application_references':['synthetic-fixture'],'source_directory':str(root),
        'development_exposure':'previously_inspected','documents':[{
            'file':source.name,'sha256':sha,'title':'Synthetic area plan',
            'role':'floor-plan','drawing_state':'proposed','application_reference':'synthetic-fixture'}]}
    write_json(root/'pilot.json',config)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
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
        surface_evidence=json.loads(evidence_path.read_text(encoding='utf-8'))['surface_footprints']
        regional=surface_evidence['extraction']
        if (regional.get('strategy')!='per_label_native_windows'
                or len(regional.get('regions',[]))<2
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
        summary=runtime.store.summary()
        if summary['feedback_records'] or summary['checkpoints']:
            raise ValueError('Area preview changed reviewed model memory')
    finally:runtime.close(wait=True)
    reopened=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if reopened.store.job(export_id)['result']!=result or reopened.store.job(pilot_id)['status']!='completed':
            raise ValueError('Area extraction and export did not survive restart')
    finally:reopened.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','original_pdf_sha256':sha,
        'source_plan_job':pilot,'area_world_job':exported,'building_footprint_markers':2,
        'path_plaza_candidates':3,'shared_frame_verified':True,'source_and_output_hashes_verified':True,
        'coloured_original_labels_verified':True,
        'regional_surface_windows_verified':True,
        'original_paper_scale_verified':True,
        'independent_building_centroid_spacing_m':expected_offset,
        'saved_paving_components':2,'saved_paving_cells':149,
        'persistent_restart_verified':True,'real_park_accuracy_assessed':False,
        'world_placement_eligible':False,'training_labels_generated':0,'model_weights_updated':False}
    write_json(root/'planning-area-smoke.json',receipt)
    return receipt
