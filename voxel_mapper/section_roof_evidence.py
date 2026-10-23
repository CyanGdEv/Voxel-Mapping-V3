"""Source-linked section apex/base diagnostics without physical roof assignment."""
import json
from pathlib import Path
import re

import pymupdf

from . import colored_source_glyphs, section_roof_leaders, glyph_visibility
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'section-roof-evidence-v1'


def comparisons(pages, models, charge):
    result = []
    for page in pages:
        words = {w['id']: w for w in page['numeric_words']}
        proofs = {p['line_id']: p for p in page['line_pixel_checks']}
        for leader in page['leaders']:
            for pair in leader['roof_pairs']:
                if pair['status'] != 'closed_original_section_triangle_candidate': continue
                points = pair['source_slope_far_endpoints']; y = pair['source_apex_pdf_unrotated'][1]
                source_ids = [leader['leader_source_id'], *pair['slope_source_ids'], *pair['cap_source_ids']]
                ink_supported = all(proofs[i]['all_samples_supported'] for i in source_ids)
                horizontal_cap = points[0][1] == points[1][1]
                rise = (points[0][1]-y)*page['nominal_metres_per_pdf_point_candidate'] if horizontal_cap else None
                level = float(words[leader['word_id']]['text'])
                for model in models:
                    charge(); apex = model['mesh']['vertices'][4][2] + model['source_level_value_m_candidate']
                    eaves = [v[2]+model['source_level_value_m_candidate'] for v in model['mesh']['vertices'][:4]]
                    residuals = [abs(level-apex)] + ([abs(level-rise-e) for e in eaves] if rise is not None else [])
                    row = {'section_roof_pair_id': pair['id'], 'roof_model_id': model['id'],
                           'section_label_value_m_candidate': level, 'section_roof_rise_nominal_m_candidate': rise,
                           'section_eave_value_m_candidate': level-rise if rise is not None else None,
                           'model_absolute_apex_m_candidate': apex, 'model_absolute_eaves_m_candidate': eaves,
                           'absolute_residuals_nominal_m': residuals, 'tolerance_nominal_m': .1,
                           'status': 'conditional_section_height_values_agree' if ink_supported and horizontal_cap and max(residuals) <= .1 else 'section_height_comparison_held',
                           'common_datum_assumed': True, 'same_physical_roof_assumed': True,
                           'section_projection_or_bearing_verified': False, 'shared_cap_face_identified': False,
                           'wall_closure_authorized': False, 'geometry_export_authorized': False}
                    row['id'] = digest([VERSION, row]); result.append(row)
    return result


def build(source_catalogue, source_directory, fascia_evidence, output, *, level_text='191.5', max_checks=2000000):
    if type(max_checks) is not int or not 1 <= max_checks <= 2000000:
        raise ValueError('Bounded section work required')
    if not isinstance(level_text,str) or not re.fullmatch(r'[12]\d{2}\.\d{1,3}',level_text):
        raise ValueError('Exact source numeric label required')
    source_catalogue, source_directory, fascia_evidence, output = map(Path,(source_catalogue,source_directory,fascia_evidence,output))
    if source_catalogue.stat().st_size > 1000000 or fascia_evidence.stat().st_size > 32000000:
        raise ValueError('Bounded section input files required')
    pins = {source_catalogue:file_hash(source_catalogue),fascia_evidence:file_hash(fascia_evidence)}
    entries=json.loads(source_catalogue.read_text())['entries']; parent=json.loads(fascia_evidence.read_text())
    if parent['status']!='conditional_source_gradient_fascia_only' or len(parent['models'])>100:
        raise ValueError('Complete conditional fascia source report required')
    if not 1 <= len(entries) <= 4 or len({e['sha256'] for e in entries})!=len(entries):
        raise ValueError('One to four distinct original section PDFs required')
    for entry in entries:
        sha=entry['sha256']
        if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Original section digest required')
        if entry['nominal_scale_denominator']!=200:raise ValueError('Supported printed section scale required')
        path=source_directory/(sha+'.pdf')
        if path.stat().st_size>20000000 or file_hash(path)!=sha:raise ValueError('Original section PDF changed')
        pins[path]=sha
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),
              'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (section_roof_leaders,colored_source_glyphs,glyph_visibility)},
              'source_catalogue_sha256':pins[source_catalogue],'source_fascia_sha256':pins[fascia_evidence],
              'source_pdf_sha256':sorted(e['sha256'] for e in entries),'level_text':level_text,'max_checks':max_checks,
              'pymupdf_version':pymupdf.VersionBind}
    root=output/digest(contract); result={'contract':contract,'status':'section_roof_source_diagnostics_only','checks':0,
            'pages':[],'height_comparisons':[],'accepted_physical_components':0,'world_geometry_additions':0,
            'training_labels_generated':0,'previous_source_holds_overridden':False,'wall_closure_authorized':False,
            'unresolved':['Same physical roof and section cut/bearing','Common vertical datum and source scale application',
                          'Shared-cap face, wall/fascia boundary and complete physical building']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('section_work_budget')
    try:
        for entry in entries:
            path=source_directory/(entry['sha256']+'.pdf')
            with pymupdf.open(path) as doc:
                if len(doc)!=1 or doc[0].rotation!=0:raise OverflowError('single_unrotated_section_page_required')
                page=doc[0]; original_words=page.get_text('words')
                scale_words=[{'text':w[4],'bbox_pdf_unrotated':list(w[:4])} for w in original_words if w[4]=='1/200']
                if not scale_words:raise ValueError('Printed section scale claim missing')
                words,screens=section_roof_leaders.numeric_words(page,level_text,charge)
                lines=section_roof_leaders.strokes(page,entry['sha256'],words,charge)
                leaders=section_roof_leaders.discover(words,lines,charge)
                ids={l['leader_source_id'] for l in leaders}
                for l in leaders:
                    for pair in l['source_arrow_head_pairs']:ids.update(pair)
                    for pair in l['roof_pairs']:ids.update(pair['slope_source_ids']);ids.update(pair['cap_source_ids'])
                retained=[l for l in lines if l['id'] in ids]; proofs=[]; display=page.get_displaylist()
                for line in retained:
                    charge();proofs.append(section_roof_leaders.line_pixels(page,line,display))
                result['pages'].append({'document_sha256':entry['sha256'],'page':1,'source_title':entry['title'],
                        'coordinate_frame':'pymupdf_unrotated_points_y_down','numeric_words':words,'glyph_screens':screens,
                        'source_lines':retained,'leaders':leaders,'line_pixel_checks':proofs,
                        'printed_scale_word_witnesses':scale_words,'nominal_metres_per_pdf_point_candidate':200*.0254/72,
                        'scale_application_verified':False,'source_state_and_text_visibility_verified':False})
        result['height_comparisons']=comparisons(result['pages'],parent['models'],charge)
    except OverflowError as error:
        result.update(status='section_roof_evidence_budget_withheld',reason=str(error),pages=[],height_comparisons=[])
    for path,pin in pins.items():
        if file_hash(path)!=pin:raise ValueError('Original section evidence input changed during build')
    result['counts']={'source_pages':len(result['pages']),
        'numeric_words':sum(len(p['numeric_words']) for p in result['pages']),
        'leaders':sum(len(p['leaders']) for p in result['pages']),
        'closed_section_roof_pairs':sum(r['status']=='closed_original_section_triangle_candidate' for p in result['pages'] for l in p['leaders'] for r in l['roof_pairs']),
        'held_section_roof_pairs':sum(r['status']!='closed_original_section_triangle_candidate' for p in result['pages'] for l in p['leaders'] for r in l['roof_pairs']),
        'height_comparisons':len(result['height_comparisons']),
        'agreeing_height_comparisons':sum(r['status']=='conditional_section_height_values_agree' for r in result['height_comparisons'])}
    result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>32000000:raise ValueError('Section evidence output budget exceeded')
    path=root/'section-roof-evidence.json'
    if path.exists():
        if digest(json.loads(path.read_text()))!=digest(result):raise ValueError('Saved section evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
