"""Actual managed collection workers, multiple batches and restart without reanalysis."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import pymupdf
import requests

from . import web_evidence as web
from .desktop_runtime import DesktopRuntime,_wait,write_json
from .desktop_planning_smoke import draw_component_fixture


def seed(cache):
    sources=[]
    for number in range(7):
        with pymupdf.open() as document:
            page=document.new_page(width=600,height=500)
            page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
            draw_component_fixture(page)
            page.insert_text((30,190),'Proposed Ground Floor Plan | 1:100',fontsize=10)
            page.insert_text((30,450),'Synthetic document '+str(number),fontsize=10)
            page.insert_text((30,400),'DEMO-AA-BB-CC-DR-A-0201',fontsize=8)
            page.draw_circle((500,380),17)
            page.insert_text((489,383),'0301',fontsize=8)
            page.insert_text((527,383),'1',fontsize=8)
            page=document.new_page(width=600,height=500)
            page.insert_text((30,190),'Proposed Section A-A | 1:100',fontsize=10)
            page.draw_rect((60,40,120,110))
            page.insert_text((70,80),'Container',fontsize=6)
            page.insert_text((30,240),'2 No. 2.1m x 3.5m Shipping containers.',fontsize=8)
            page.insert_textbox((30,270,570,350),
                'The proposed layout will result in a building footprint of 472 sq.m.\n'
                'The two lines of portacabins are located 8.05m apart, 35.85m long and 2.5m wide\n'
                'with an eaves height of 2.5m and linked by a domed ridge approximately 5.70m above ground level.',fontsize=7)
            page.insert_text((30,400),'DEMO-AA-BB-CC-DR-A-0301',fontsize=8)
            sources.append(('https://example.org/plan-'+str(number)+'.pdf',document.tobytes()))
    index=('<html><main>APP/1 '+''.join('<a href="'+value+'">Drawing</a>' for value,_ in sources)+'</main></html>').encode()
    class Response:
        status_code=200
        headers={'Content-Type':'text/html'}
        def __init__(self,data):self.data=data
        def iter_content(self,*args):yield self.data
        def close(self):pass
    session=requests.Session()
    try:
        for value,data in [('https://example.org/',index)]+sources:
            with patch.object(session,'get',return_value=Response(data)):
                web.fetch(value,cache,['example.org'],session=session,
                    resolver=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
    finally:session.close()


def run(output):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Fresh planning collection smoke output required')
    root.mkdir(parents=True);seed(root/'memory'/'web-cache')
    def submit(runtime):
        jid=runtime.submit_web_planning('APP/1',urls=['https://example.org/'],
            allowed_hosts=['example.org'],offline=True,collect=True)
        job=_wait(runtime,jid,timeout=120);runtime._futures[jid].result(timeout=10)
        if job['status']!='completed':raise ValueError('Managed planning collection failed: '+str(job.get('error')))
        return job
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        first=submit(runtime);result=first['result'];pack=Path(first['output_directory'])
        if result['summary']['completed_batches']!=2 or result['summary']['completed_pages']!=14:
            raise ValueError('Automatic collection did not complete its follow-up batch')
        if result['summary']['completed_sources']!=8 or result['unresolved_sources']:
            raise ValueError('Known synthetic sources were left unread')
        if result['summary'].get('closed_source_outlines')!=7 or result['summary'].get('nominal_view_outlines',0)<7:
            raise ValueError('Automatic batches lost source outlines or nominal view measurements')
        if result['summary'].get('source_outline_role_hints')!=7 or result['summary'].get('path_plaza_outline_hints')!=7:
            raise ValueError('Automatic batches lost source-label enclosure hints')
        if result['summary'].get('component_boundary_candidates')!=14:
            raise ValueError('Automatic batches lost distinct fine component boundaries')
        if result['summary'].get('size_consistent_component_hypotheses')!=14:
            raise ValueError('Automatic batches lost printed-size diagnostics')
        if result['summary'].get('nominal_section_profile_hypotheses')!=7:
            raise ValueError('Automatic batches lost unassigned section profiles')
        profiles=json.loads((pack/'section-profiles.json').read_text())
        if profiles['local_3d_components'] or profiles['physical_height_verified'] or len(profiles['profiles'])!=7:
            raise ValueError('Section profiles asserted physical height or lost evidence')
        correspondence=json.loads((pack/'section-correspondence.json').read_text())
        if (correspondence['summary']['section_plan_context_pairs']!=98
                or correspondence['summary']['profiles_with_multiple_plan_candidates']!=7
                or correspondence['summary']['source_sheet_reference_markers']!=7
                or correspondence['local_3d_components'] or correspondence['physical_height_verified']
                or any(p['selected_component_id'] is not None for p in correspondence['profiles'])):
            raise ValueError('Collection lost competing plan candidates or selected an unsupported physical link')
        massing=json.loads((pack/'design-massing.json').read_text())
        if (massing['summary']['conditional_design_massing_alternatives']!=14
                or massing['summary']['conditional_design_row_groups']!=28
                or massing['physical_height_verified'] or massing['world_placement_eligible']):
            raise ValueError('Source design dimensions lost conditional 3D row-group alternatives')
        for model_path in pack.glob('design-massing-*/model.glb'):
            if model_path.read_bytes()[:4]!=b'glTF':
                raise ValueError('Conditional massing did not export an actual GLB')
        for name,pin in result['output_sha256'].items():
            if hashlib.sha256((pack/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Planning collection snapshot output changed')
        first_alternative=massing['alternatives'][0]
        pair=[row for row in massing['alternatives'] if all(row[key]==first_alternative[key]
            for key in ('document_sha256','page','source_claim_id'))]
        if len(pair)!=2:raise ValueError('Expected both spacing interpretations for the first source claim')
        world_jid=runtime.submit_planning_world_preview(first['id'],alternative_ids=[row['id'] for row in pair])
        preview_job=_wait(runtime,world_jid,timeout=120);runtime._futures[world_jid].result(timeout=10)
        if preview_job['status']!='completed':
            raise ValueError('Managed planning world export failed: '+str(preview_job.get('error')))
        preview_result=preview_job['result'];preview_root=Path(preview_job['output_directory'])
        if (preview_result.get('status')!='conditional_world_previews_exported'
                or preview_result.get('world_placement_eligible')
                or preview_result.get('training_labels_generated')!=0
                or len(preview_result.get('worlds',[]))!=2
                or not (preview_root/'index.html').is_file()):
            raise ValueError('Planning preview worlds lost a rival or asserted physical placement')
        if {row['spacing_interpretation'] for row in preview_result['worlds']}!={'clear_gap','row_centre_separation'}:
            raise ValueError('Planning world export selected a single spacing interpretation')
        spec_pins={row['spacing_interpretation']:row['spec_sha256'] for row in pair}
        for world in preview_result['worlds']:
            if (world['source_spec_sha256']!=spec_pins[world['spacing_interpretation']]
                    or world.get('world_placement_eligible')
                    or not world['spawn_validation']['verified']
                    or not world['archive_validation']['crc_verified']
                    or not world['archive_validation']['saved_world_reopened']
                    or world['world']['round_trip_validation']!='all written blocks and all unwritten air cells verified'):
                raise ValueError('Planning world lost its source specification, safe spawn or saved-world checks')
            with zipfile.ZipFile(preview_root/world['file']) as archive:
                names=archive.namelist()
                if archive.testzip() is not None or 'level.dat' not in names or not any(name.startswith('db/') for name in names):
                    raise ValueError('Planning world is not a valid root-level Bedrock archive')
        for name,pin in preview_result['output_sha256'].items():
            if hashlib.sha256((preview_root/name).read_bytes()).hexdigest()!=pin:
                raise ValueError('Planning world output changed after validation')
    finally:runtime.close(wait=True)
    runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
    try:
        if runtime.store.job(first['id'])['result']['summary']!=result['summary']:
            raise ValueError('Collection history did not survive restart')
        if runtime.store.job(preview_job['id'])['result']!=preview_result:
            raise ValueError('Planning world export history did not survive restart')
        second=submit(runtime)
        if second['result']['summary']['new_batches']!=0 or second['result']['summary']['completed_pages']!=14:
            raise ValueError('Restart repeated completed drawing analysis')
        if second['result']['summary'].get('component_boundary_candidates')!=14:
            raise ValueError('Restart lost fine component boundary candidates')
        if second['result']['summary'].get('size_consistent_component_hypotheses')!=14:
            raise ValueError('Restart lost printed-size diagnostics')
        if second['result']['summary'].get('nominal_section_profile_hypotheses')!=7:
            raise ValueError('Restart lost unassigned section profiles')
        for key in ('section_plan_context_pairs','profiles_with_multiple_plan_candidates','source_sheet_reference_markers'):
            if second['result']['summary'].get(key)!=result['summary'][key]:
                raise ValueError('Restart changed correspondence diagnostics')
        if second['result']['summary'].get('conditional_design_massing_alternatives')!=14:
            raise ValueError('Restart lost conditional 3D design massing')
        if runtime.store.summary()['feedback_records'] or runtime.store.summary()['checkpoints']:
            raise ValueError('Collection created reviewed labels or model checkpoints')
    finally:runtime.close(wait=True)
    receipt={'status':'passed','dataset_kind':'synthetic','first_job':first,'resumed_job':second,
        'preview_world_job':preview_job,
        'multiple_automatic_batches_verified':True,'restart_without_reanalysis_verified':True,
        'original_and_output_hashes_verified':True,'network_bytes':result['network_bytes'],
        'source_label_hints_verified':True,
        'component_boundaries_verified':True,
        'component_measurements_verified':True,
        'unassigned_section_profiles_verified':True,
        'section_correspondence_rivals_retained_verified':True,
        'conditional_design_massing_verified':True,
        'planning_world_pair_export_verified':True,
        'planning_world_archive_readback_and_spawn_verified':True,
        'planning_world_history_survives_restart_verified':True,
        'public_network_assessed':False,'installed_model_quality_assessed':False,
        'training_labels_generated':0,'world_placement_eligible':False}
    write_json(root/'planning-collection-smoke.json',receipt)
    return receipt
