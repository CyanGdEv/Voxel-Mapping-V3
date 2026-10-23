"""Fresh source replay and compound roof correspondence to original site plans."""
import json
from pathlib import Path
import re
import tempfile

import numpy as np
import pymupdf

from . import section_adjoining_evidence as parent
from . import site_roof_correspondence as kernel
from . import pyramidal_roof_topology as topology
from . import section_roof_leaders
from .generation_cycles import atomic_json,file_hash
from .reconstruction_evidence_queue import digest

VERSION='site-roof-evidence-v1'


def build(adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,
          section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output,*,max_checks=200000):
    if type(max_checks) is not int or not 1<=max_checks<=200000:raise ValueError('Bounded site correspondence work required')
    adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    paths=[adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,fascia_evidence,roof_plan_pdf]
    if any(p.stat().st_size>32000000 for p in paths):raise ValueError('Bounded site correspondence inputs required')
    pins={p:file_hash(p) for p in paths};adjoining=json.loads(adjoining_evidence.read_text());projection=json.loads(projection_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text());entries=json.loads(site_catalogue.read_text())['entries']
    if adjoining['status']!='section_adjoining_ridge_diagnostics_only':raise ValueError('Complete adjoining-source parent required')
    if not 1<=len(entries)<=2 or len({e['sha256'] for e in entries})!=len(entries):raise ValueError('One or two distinct original site PDFs required')
    for entry in entries:
        if not re.fullmatch('[0-9a-f]{64}',entry['sha256']) or entry['nominal_scale_denominator']!=250 or entry['context_word']!='Station':raise ValueError('Pinned original site source and supported source scale/context required')
        path=source_directory/(entry['sha256']+'.pdf')
        if path.stat().st_size>20000000 or file_hash(path)!=entry['sha256']:raise ValueError('Original site PDF changed')
        pins[path]=entry['sha256']
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (kernel,parent,topology,section_roof_leaders)},
        'input_sha256':{p.name:pins[p] for p in paths},'original_site_pdf_sha256':sorted(e['sha256'] for e in entries),
        'max_checks':max_checks,'parent_max_checks':adjoining['contract']['max_checks'],
        'context_margin_pdf_points':kernel.CONTEXT_MARGIN_PDF_POINTS,'tolerance_nominal_m':kernel.TOLERANCE_M,
        'pymupdf_version':pymupdf.VersionBind}
    fields=('source_pages','registrations','registration_support','section_site_camera_candidates')
    result={'contract':contract,'status':'site_roof_correspondence_diagnostics_only','checks':0,
        'parent_adjoining_fresh_replay_identical':False,**{f:[] for f in fields},'accepted_physical_components':0,
        'world_geometry_additions':0,'training_labels_generated':0,'wall_closure_authorized':False,
        'geographic_registration_verified':False,'previous_source_holds_overridden':False,
        'unresolved':['Original plans describe the same physical component/source-state','Reflection and section cut/view direction','Geographic registration and datum','Shared-cap surface and physical wall closure']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('site_roof_work_budget')
    try:
        charge();charge()
        with tempfile.TemporaryDirectory() as temp:
            fresh=parent.build(projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,temp,max_checks=adjoining['contract']['max_checks']);fresh.pop('directory')
            if fresh!=adjoining:raise ValueError('Original adjoining-source replay changed')
        result['parent_adjoining_fresh_replay_identical']=True
        for entry in entries:
            path=source_directory/(entry['sha256']+'.pdf');unit=250*.0254/72
            with pymupdf.open(path) as doc:
                if len(doc)!=1 or doc[0].rotation!=0:raise ValueError('One unrotated original site page required')
                page=doc[0];scale_words=[{'text':w[4],'bbox_pdf_unrotated':list(w[:4])} for w in page.get_text('words') if w[4]=='1/250']
                if not scale_words:raise ValueError('Original printed site scale missing')
                words,screens=section_roof_leaders.numeric_words(page,entry['context_word'],charge)
                lines=kernel.original_lines(page,entry['sha256'],words,unit,charge)
                graph=topology.discover({'view_id':digest([VERSION,entry['sha256'],entry['context_word']]),'document_sha256':entry['sha256'],'page':1,'nominal_metres_per_pdf_point':unit,'lines':lines},charge)
                registrations=[]
                for candidate in graph['candidates']:
                    for plan in adjoining['plan_ridges']:
                        source=next(c for g in pyramid['plan_graphs'] for c in g['candidates'] if c['id']==plan['pyramid_candidate_id'])
                        registrations.extend(kernel.registrations(source,candidate,plan['nominal_metres_per_pdf_point'],unit,plan['original_ridge'],lines,charge))
                required={sid for c in graph['candidates'] for group in c['source_perimeter_ids_per_edge']+c['source_spoke_ids_per_corner'] for sid in group}
                required.update(c['site_source_line_id'] for r in registrations for c in r['ridge_comparisons'] if c['whole_ridge_endpoints_compatible'])
                pixels=[];display=page.get_displaylist()
                for line in lines:
                    if line['id'] in required:
                        charge();pixels.append(section_roof_leaders.line_pixels(page,line,display))
                result['source_pages'].append({'document_sha256':entry['sha256'],'page':1,'source_title':entry['title'],
                    'context_words':words,'context_glyph_screens':screens,'printed_scale_word_witnesses':scale_words,
                    'graph':graph,'line_pixel_checks':pixels,'context_label_assigns_physical_roof_role':False,
                    'scale_application_verified':False,'coordinate_frame':'pdf_native_points_y_up'})
                result['registrations'].extend(registrations);result['registration_support'].extend(kernel.support(registrations,graph['candidates'],pixels))
        supported={r['registration_id'] for r in result['registration_support'] if r['status']=='conditional_compound_roof_registration_supported'}
        posemap={p['id']:p for p in projection['projection_candidates']}
        for registration in result['registrations']:
            if registration['id'] not in supported:continue
            matrix=np.array(registration['orthogonal_matrix'])
            for constraint in adjoining['conditional_face_constraints']:
                for pid in constraint['conditionally_supported_projection_ids']:
                    charge();pose=posemap[pid]
                    if pose['original_plan_candidate_id']!=registration['architectural_plan_candidate_id']:continue
                    row={'registration_id':registration['id'],'parent_projection_id':pid,'source_group_id':pose['source_group_id'],
                        'candidate_viewer_direction_site_native_xy':(matrix@pose['candidate_viewer_direction_native_xy']).tolist(),
                        'candidate_horizontal_direction_site_native_xy':(matrix@pose['unit_projection_horizontal_vector']).tolist(),
                        'original_source_horizontal_and_plan_scale_unchanged':True,'same_physical_component_assumed':True,
                        'geographic_bearing_verified':False,'physical_face_assignment_verified':False,'wall_closure_authorized':False}
                    row['id']=digest([VERSION,row]);result['section_site_camera_candidates'].append(row)
    except OverflowError as error:
        result.update(status='site_roof_correspondence_budget_withheld',reason=str(error),**{f:[] for f in fields})
    for p,pin in pins.items():
        if file_hash(p)!=pin:raise ValueError('Original site correspondence input changed during build')
    result['counts']={'source_pages':len(result['source_pages']),'source_context_words':sum(len(p['context_words']) for p in result['source_pages']),
        'original_site_line_items':sum(len(p['graph']['original_lines']) for p in result['source_pages']),
        'original_site_roof_candidates':sum(len(p['graph']['candidates']) for p in result['source_pages']),
        'original_site_pixel_checks':sum(len(p['line_pixel_checks']) for p in result['source_pages']),
        'registrations':len(result['registrations']),'supported_registrations':sum(r['status']=='conditional_compound_roof_registration_supported' for r in result['registration_support']),
        'section_site_camera_candidates':len(result['section_site_camera_candidates'])}
    result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>32000000:raise ValueError('Site correspondence output budget exceeded')
    root=output/digest(contract);path=root/'site-roof-evidence.json'
    if path.exists():
        if json.loads(path.read_text())!=result:raise ValueError('Saved site correspondence evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
