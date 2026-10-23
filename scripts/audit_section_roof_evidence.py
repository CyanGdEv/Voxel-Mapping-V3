"""Fresh replay and independent source path, RGB sample and height checks."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper.section_roof_evidence import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence,source_catalogue,source_directory,fascia_evidence,output):
    evidence,source_catalogue,source_directory,fascia_evidence,output=map(Path,(evidence,source_catalogue,source_directory,fascia_evidence,output))
    path=evidence/'section-roof-evidence.json';report=json.loads(path.read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        replay=build(source_catalogue,source_directory,fascia_evidence,temp,level_text=report['contract']['level_text'],max_checks=report['contract']['max_checks'])
        replay.pop('directory');assert replay==report
    assert report['status']=='section_roof_source_diagnostics_only'
    pair_map={}
    for record in report['pages']:
        original=source_directory/(record['document_sha256']+'.pdf');assert file_hash(original)==record['document_sha256']
        with pymupdf.open(original) as doc:
            page=doc[0];traces=page.get_texttrace();paths=page.get_cdrawings(extended=True);display=page.get_displaylist()
            original_words=page.get_text('words');lines={l['id']:l for l in record['source_lines']}
            for word in record['numeric_words']:
                source=original_words[word['word_index']];assert source[4]==word['text'];assert list(source[:4])==word['source_bbox_pdf_unrotated']
                assert ''.join(chr(traces[ti]['chars'][ci][0]) for ti,ci in word['trace_character_indices'])==word['text']
                checked['original_numeric_words']+=1
            for ti,screen in record['glyph_screens'].items():
                span=traces[int(ti)];clip=pymupdf.Rect(span['bbox'])+(-.5,-.5,.5,.5)
                pix=display.get_pixmap(matrix=pymupdf.Matrix(6,6),clip=clip,colorspace=pymupdf.csRGB,alpha=False)
                assert hashlib.sha256(pix.samples).hexdigest()==screen['source_rgb_sha256']
                for candidate in screen['original_font_candidates']:
                    assert hashlib.sha256(doc.extract_font(candidate['original_font_xref'])[3]).hexdigest()==candidate['original_font_sha256']
                    assert candidate['original_cids']==[c[1] for c in span['chars']]
                assert not screen['font_substitution_used'];checked['original_color_glyph_traces']+=1
            for line in lines.values():
                source=paths[line['path_index']];item=source['items'][line['item_index']]
                assert digest(source)==line['path_record_sha256'];assert item[0]=='l'
                assert [list(p) for p in item[1:3]]==line['source_endpoints_pdf_unrotated']
                assert list(source['color'])==line['color_rgb'];assert not line['source_line_clipped_or_extended']
                checked['original_whole_path_items']+=1
            for proof in record['line_pixel_checks']:
                line=lines[proof['line_id']];a,b=line['source_endpoints_pdf_unrotated']
                clip=pymupdf.Rect(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1]))+(-1,-1,1,1)
                pix=display.get_pixmap(matrix=pymupdf.Matrix(6,6),clip=clip,colorspace=pymupdf.csRGB,alpha=False)
                assert hashlib.sha256(pix.samples).hexdigest()==proof['source_rgb_sha256']
                rgb=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3);passed=[]
                for i,witness in enumerate(proof['source_samples'],1):
                    assert witness['fraction']==i/32
                    point=[a[j]+i/32*(b[j]-a[j]) for j in (0,1)];x=math.floor(point[0]*6)-pix.x;y=math.floor(point[1]*6)-pix.y
                    window=rgb[max(0,y-1):y+2,max(0,x-1):x+2];assert window.tolist()==witness['source_neighbourhood_rgb']
                    supported=bool(np.any(np.max(np.abs(window.astype(float)-np.array(line['color_rgb'])*255),axis=2)<=24))
                    assert supported==witness['matching_source_color_present'];passed.append(supported);checked['independent_original_rgb_neighbourhoods']+=1
                assert all(passed)==proof['all_samples_supported']
            for leader in record['leaders']:
                leader_points=lines[leader['leader_source_id']]['source_endpoints_pdf_unrotated'];apex=max(leader_points,key=lambda p:p[1])
                for pair in leader['roof_pairs']:
                    if pair['status']=='closed_original_section_triangle_candidate':
                        assert pair['source_apex_pdf_unrotated']==apex
                        for sid in pair['slope_source_ids']:assert apex in lines[sid]['source_endpoints_pdf_unrotated']
                        ends=sorted(pair['source_slope_far_endpoints'])
                        for sid in pair['cap_source_ids']:assert sorted(lines[sid]['source_endpoints_pdf_unrotated'])==ends
                        checked['independent_closed_triangles']+=1
                    pair_map[pair['id']]=(pair,record)
    models={m['id']:m for m in json.loads(fascia_evidence.read_text())['models']}
    for row in report['height_comparisons']:
        pair,page=pair_map[row['section_roof_pair_id']];model=models[row['roof_model_id']]
        rise=(pair['source_slope_far_endpoints'][0][1]-pair['source_apex_pdf_unrotated'][1])*200*.0254/72
        assert abs(rise-row['section_roof_rise_nominal_m_candidate'])<1e-12
        assert row['model_absolute_apex_m_candidate']==model['mesh']['vertices'][4][2]+model['source_level_value_m_candidate']
        assert not row['shared_cap_face_identified'] and not row['wall_closure_authorized'];checked['independent_height_comparisons']+=1
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),
             'source_fascia_sha256':file_hash(fascia_evidence),'checked':dict(checked)}
    atomic_json(output,receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','source-catalogue','source-directory','fascia-evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
