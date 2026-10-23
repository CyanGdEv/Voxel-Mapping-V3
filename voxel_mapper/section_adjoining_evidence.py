"""Pinned original adjoining ridge evidence, preserving all parent hypotheses."""
import json
from pathlib import Path
import tempfile

import pymupdf

from . import section_adjoining_ridges as kernel
from . import section_projection_evidence as parent
from . import pyramidal_roof_topology, section_roof_leaders
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'section-adjoining-evidence-v1'


def build(projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,
          source_directory,fascia_evidence,roof_plan_pdf,output,*,max_checks=2000000):
    if type(max_checks) is not int or not 1 <= max_checks <= 2000000:
        raise ValueError('Bounded adjoining-source work required')
    projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    paths=[projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,fascia_evidence,roof_plan_pdf]
    if any(p.stat().st_size>32000000 for p in paths):
        raise ValueError('Bounded adjoining evidence inputs required')
    pins={p:file_hash(p) for p in paths}
    projection=json.loads(projection_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text());reference=json.loads(reference_evidence.read_text())
    if projection['status']!='section_projection_diagnostics_only':
        raise ValueError('Complete parent projection evidence required')
    if pyramid['contract']['source_reference_sha256']!=pins[reference_evidence]:
        raise ValueError('Original adjoining-plan reference lineage changed')
    for page in json.loads(section_evidence.read_text())['pages']:
        p=source_directory/(page['document_sha256']+'.pdf')
        if p.stat().st_size>20000000 or file_hash(p)!=page['document_sha256']:
            raise ValueError('Original adjoining section source changed')
        pins[p]=page['document_sha256']
    contract={'version':VERSION, 'implementation_sha256':file_hash(Path(__file__)),
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (kernel,parent,pyramidal_roof_topology,section_roof_leaders)},
        'source_projection_sha256':pins[projection_evidence], 'source_section_sha256':pins[section_evidence],
        'source_pyramid_sha256':pins[pyramid_evidence], 'source_reference_sha256':pins[reference_evidence],
        'source_catalogue_sha256':pins[section_catalogue], 'source_fascia_sha256':pins[fascia_evidence],
        'original_roof_pdf_sha256':pins[roof_plan_pdf], 'max_checks':max_checks,
        'parent_projection_max_checks':projection['contract']['max_projection_checks'],
        'source_neighbourhood_pdf_points':{'horizontal_margin':250,'below_original_base':80,'whole_horizontal_length_range':[12,250]},
        'pymupdf_version':pymupdf.VersionBind}
    fields=('plan_ridges','original_plan_witnesses','source_horizontal_lines','source_line_pixel_checks','projection_ridge_checks','conditional_face_constraints')
    result={'contract':contract,'status':'section_adjoining_ridge_diagnostics_only','checks':0,
            'parent_projection_fresh_replay_identical':False, **{f:[] for f in fields},
            'accepted_physical_components':0,'world_geometry_additions':0,'training_labels_generated':0,
            'previous_source_holds_overridden':False,'wall_closure_authorized':False,
            'unresolved':['Physical adjoining-building correspondence and source-state','Section cut/view direction and reflection','Shared-cap fascia/wall surface and vertical datum']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:
            raise OverflowError('section_adjoining_work_budget')
    try:
        charge();charge()
        with tempfile.TemporaryDirectory() as temp:
            fresh=parent.build(section_evidence,pyramid_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,temp,
                               max_checks=projection['contract']['max_projection_checks']);fresh.pop('directory')
            if fresh!=projection:
                raise ValueError('Original parent projection source replay changed')
        result['parent_projection_fresh_replay_identical']=True
        for graph in pyramid['plan_graphs']:
            topologies=[t for t in reference['source_topologies'] if t['view_id']==graph['view_id']]
            if len(topologies)!=1 or topologies[0]['lines']!=graph['original_lines']:
                raise ValueError('Identical original adjoining-plan source graph required')
            topology=topologies[0];by_id={l['source_component_id']:l for l in graph['original_lines']}
            for junction in pyramid['source_junctions']:
                candidates=[c for c in graph['candidates'] if c['id']==junction['pyramid_candidate_id']]
                if not candidates:continue
                lows=[c for c in topology['candidates'] if c['id']==junction['gable_candidate_id']]
                if len(lows)!=1:raise ValueError('Original adjoining ridge candidate required')
                low=lows[0];candidate=candidates[0]
                replay=pyramidal_roof_topology.junctions(topology,[candidate],{low['id']},charge)
                if junction not in replay:raise ValueError('Original adjoining shared-cap relation changed')
                ridge=by_id[low['ridge_source_id']]
                result['plan_ridges'].append({'junction_id':junction['id'],'pyramid_candidate_id':candidate['id'],
                    'gable_candidate_id':low['id'],'original_ridge':ridge,'original_rail_source_ids':low['rail_source_ids'],
                    'original_shared_cap_source_id':junction['shared_original_cap_source_id'],
                    'nominal_metres_per_pdf_point':graph['nominal_metres_per_pdf_point'],
                    'original_rail_tails_unchanged':True,'physical_roof_roles_verified':False})
                witness_candidate={'source_spoke_ids_per_corner':[[low['ridge_source_id']]],
                    'source_perimeter_ids_per_edge':[[s] for s in low['rail_source_ids']+[junction['shared_original_cap_source_id']]]}
                result['original_plan_witnesses'].extend(parent.plan_witnesses(graph,witness_candidate,roof_plan_pdf,charge))
        groups=projection['source_groups']
        for sha in sorted({g['source_document_sha256'] for g in groups}):
            with pymupdf.open(source_directory/(sha+'.pdf')) as doc:
                selected=[g for g in groups if g['source_document_sha256']==sha]
                if any(g['source_page']!=1 for g in selected):raise ValueError('Single original section page required')
                if not any(g['status']=='original_three_spoke_whole_base_candidate' for g in selected):continue
                result['source_horizontal_lines'].extend(kernel.horizontal_strokes(doc[0],sha,selected,charge))
        for plan in result['plan_ridges']:
            candidate=next(c for g in pyramid['plan_graphs'] for c in g['candidates'] if c['id']==plan['pyramid_candidate_id'])
            for pose in projection['projection_candidates']:
                if pose['original_plan_candidate_id']!=candidate['id']:continue
                group=next(g for g in groups if g['id']==pose['source_group_id'])
                result['projection_ridge_checks'].append(kernel.compare(group,pose,candidate,plan['original_ridge'],plan['nominal_metres_per_pdf_point'],result['source_horizontal_lines'],charge))
        compatible={c['source_line_id'] for r in result['projection_ridge_checks'] for c in r['comparisons'] if c['endpoints_compatible']}
        for sha in sorted({l['document_sha256'] for l in result['source_horizontal_lines'] if l['id'] in compatible}):
            with pymupdf.open(source_directory/(sha+'.pdf')) as doc:
                page=doc[0];display=page.get_displaylist()
                for line in result['source_horizontal_lines']:
                    if line['document_sha256']==sha and line['id'] in compatible:
                        charge();result['source_line_pixel_checks'].append(section_roof_leaders.line_pixels(page,line,display))
        result['conditional_face_constraints']=kernel.summarize(groups,result['projection_ridge_checks'],result['source_line_pixel_checks'])
    except OverflowError as error:
        result.update(status='section_adjoining_budget_withheld',reason=str(error),**{f:[] for f in fields})
    for path,pin in pins.items():
        if file_hash(path)!=pin:raise ValueError('Original adjoining input changed during build')
    result['counts']={f:len(result[f]) for f in fields}
    result['counts'].update(conditionally_supported_projections=sum(r['conditionally_supported_projection_count'] for r in result['conditional_face_constraints']),
        conditional_shared_cap_visible=sum(r['shared_cap_visible_candidates'] for r in result['conditional_face_constraints']),
        conditional_shared_cap_hidden=sum(r['shared_cap_hidden_candidates'] for r in result['conditional_face_constraints']))
    result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>32000000:raise ValueError('Adjoining evidence output budget exceeded')
    root=output/digest(contract);path=root/'section-adjoining-evidence.json'
    if path.exists():
        if json.loads(path.read_text())!=result:raise ValueError('Saved adjoining evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
