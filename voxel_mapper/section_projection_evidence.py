"""Pinned section-to-plan projection diagnostics with explicit face ambiguity."""
import json
from pathlib import Path
import tempfile

import pymupdf

from . import section_roof_projection, section_roof_evidence, pyramidal_roof_topology
from .drawing_page_tools import native_inverse
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'section-projection-evidence-v1'


def plan_witnesses(graph, candidate, path, charge):
    """Every perimeter/spoke must be a whole straight item in the original PDF."""
    ids={sid for group in candidate['source_spoke_ids_per_corner']+candidate['source_perimeter_ids_per_edge'] for sid in group}
    lines={l['source_component_id']:l for l in graph['original_lines']}; required={}
    for sid in sorted(ids):
        charge();key=tuple(sorted(tuple(p) for p in lines[sid]['source_endpoints_pdf_native']));required.setdefault(key,[]).append(sid)
    found={sid:[] for sid in ids}
    with pymupdf.open(path) as doc:
        if not 1<=graph['page']<=len(doc)<=16:raise ValueError('Original plan page required')
        page=doc[graph['page']-1];matrix=native_inverse(page);paths=page.get_cdrawings(extended=True)
        if len(paths)>100000:raise OverflowError('projection_original_plan_path_budget')
        for pi,record in enumerate(paths):
            charge()
            if record['type']!='s' or record.get('layer') or record.get('stroke_opacity')!=1:continue
            for ii,item in enumerate(record['items']):
                charge()
                if item[0]!='l':continue
                points=[list(pymupdf.Point(p)*matrix) for p in item[1:3]];key=tuple(sorted(tuple(p) for p in points))
                for sid in required.get(key,[]):
                    found[sid].append({'source_component_id':sid,'original_pdf_path_index':pi,'original_pdf_item_index':ii,
                        'original_path_record_sha256':digest(record),'original_endpoints_pdf_native':points,
                        'original_paint_seqno':record['seqno']})
    if any(not witnesses for witnesses in found.values()):raise ValueError('Whole original plan perimeter/spoke witness missing')
    return [w for sid in sorted(found) for w in found[sid]]


def build(section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded projection work required')
    section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    paths=[section_evidence,pyramid_evidence,section_catalogue,fascia_evidence,roof_plan_pdf]
    if any(p.stat().st_size>32000000 for p in paths):raise ValueError('Bounded projection input files required')
    pins={p:file_hash(p) for p in paths}
    section=json.loads(section_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text());fascia=json.loads(fascia_evidence.read_text())
    if section['status']!='section_roof_source_diagnostics_only' or len(section['pages'])>4:raise ValueError('Complete section source evidence required')
    if pyramid['status']!='conditional_pyramidal_roof_evidence_only':raise ValueError('Complete original pyramid evidence required')
    if section['contract']['source_fascia_sha256']!=pins[fascia_evidence] or fascia['contract']['source_pyramid_sha256']!=pins[pyramid_evidence]:
        raise ValueError('Original section/fascia/plan lineage changed')
    if not 1<=len(pyramid['plan_graphs'])<=4 or len(pyramid['source_junctions'])>256:raise ValueError('Bounded complete original plan graphs required')
    for page in section['pages']:
        path=source_directory/(page['document_sha256']+'.pdf')
        if path.stat().st_size>20000000 or file_hash(path)!=page['document_sha256']:raise ValueError('Original section PDF changed')
        pins[path]=page['document_sha256']
    modules=[section_roof_projection,section_roof_evidence,pyramidal_roof_topology]
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in modules},
        'source_section_sha256':pins[section_evidence],'source_pyramid_sha256':pins[pyramid_evidence],
        'source_fascia_sha256':pins[fascia_evidence],'source_catalogue_sha256':pins[section_catalogue],
        'original_roof_pdf_sha256':pins[roof_plan_pdf],'max_projection_checks':max_checks,
        'parent_section_max_checks':section['contract']['max_checks'],'pymupdf_version':pymupdf.VersionBind}
    root=output/digest(contract);result={'contract':contract,'status':'section_projection_diagnostics_only','checks':0,
        'parent_section_fresh_replay_identical':False,'plan_source_witnesses':[],'source_groups':[],'projection_candidates':[],'face_ambiguity':[],
        'world_geometry_additions':0,'accepted_physical_components':0,'training_labels_generated':0,
        'previous_source_holds_overridden':False,'wall_closure_authorized':False,
        'unresolved':['Section cut/view direction tied to the original plan and adjoining gable',
                      'Physical component correspondence, source-state and datum','Shared-cap fascia/wall surface']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('section_projection_work_budget')
    try:
        charge();charge()
        with tempfile.TemporaryDirectory() as temp:
            replay=section_roof_evidence.build(section_catalogue,source_directory,fascia_evidence,temp,
                level_text=section['contract']['level_text'],max_checks=section['contract']['max_checks']);replay.pop('directory')
            if replay!=section:raise ValueError('Original section source replay changed')
        result['parent_section_fresh_replay_identical']=True
        result['source_groups']=[group for page in section['pages'] for group in section_roof_projection.spoke_groups(page,charge)]
        for graph in pyramid['plan_graphs']:
            if graph['document_sha256']!=pins[roof_plan_pdf]:raise ValueError('Original roof plan PDF identity changed')
            fresh=pyramidal_roof_topology.discover({**graph,'lines':graph['original_lines']},charge)
            if fresh!=graph:raise ValueError('Original four-spoke plan graph replay changed')
            for candidate in graph['candidates']:
                junctions=[j for j in pyramid['source_junctions'] if j['pyramid_candidate_id']==candidate['id']]
                if len(junctions)!=1:raise ValueError('One original shared-cap relation required per candidate')
                cap=junctions[0]['shared_original_cap_source_id']
                result['plan_source_witnesses'].extend(plan_witnesses(graph,candidate,roof_plan_pdf,charge))
                for group in result['source_groups']:
                    result['projection_candidates'].extend(section_roof_projection.projections(group,candidate,graph['nominal_metres_per_pdf_point'],cap,charge))
        result['face_ambiguity']=section_roof_projection.ambiguity(result['source_groups'],result['projection_candidates'])
    except OverflowError as error:
        result.update(status='section_projection_budget_withheld',reason=str(error),plan_source_witnesses=[],source_groups=[],projection_candidates=[],face_ambiguity=[])
    for path,pin in pins.items():
        if file_hash(path)!=pin:raise ValueError('Original projection input changed during build')
    result['counts']={'original_plan_line_witnesses':len(result['plan_source_witnesses']),
        'source_groups':len(result['source_groups']),'supported_source_groups':sum(g['status']=='original_three_spoke_whole_base_candidate' for g in result['source_groups']),
        'projection_candidates':len(result['projection_candidates']),
        'supported_projection_candidates':sum(p['status']=='conditional_source_projection_supported' for p in result['projection_candidates']),
        'shared_cap_visible_candidates':sum(p['shared_cap_candidate_visible'] and p['status']=='conditional_source_projection_supported' for p in result['projection_candidates']),
        'shared_cap_hidden_candidates':sum(not p['shared_cap_candidate_visible'] and p['status']=='conditional_source_projection_supported' for p in result['projection_candidates'])}
    result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>32000000:raise ValueError('Projection output budget exceeded')
    path=root/'section-projection-evidence.json'
    if path.exists():
        if json.loads(path.read_text())!=result:raise ValueError('Saved projection evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
