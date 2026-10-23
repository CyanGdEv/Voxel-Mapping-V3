"""Independent original site primitives, rigid transforms, pixels and face bridges."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper.site_roof_evidence import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence,adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output):
    evidence,adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (evidence,adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    path=evidence/'site-roof-evidence.json';r=json.loads(path.read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(adjoining_evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,site_catalogue,source_directory,fascia_evidence,roof_plan_pdf,temp,max_checks=r['contract']['max_checks']);fresh.pop('directory');assert fresh==r
    assert r['status']=='site_roof_correspondence_diagnostics_only' and r['parent_adjoining_fresh_replay_identical']
    for source in r['source_pages']:
        with pymupdf.open(source_directory/(source['document_sha256']+'.pdf')) as doc:
            page=doc[0];assert page.rotation==0 and page.cropbox.x0==page.cropbox.y0==0
            paths=page.get_cdrawings(extended=True);words=page.get_text('words');pixelmap={p['line_id']:p for p in source['line_pixel_checks']}
            for word in source['context_words']:
                original=words[word['word_index']];assert original[4]==word['text'] and list(original[:4])==word['source_bbox_pdf_unrotated'];checked['independent_context_word_items']+=1
            for line in source['graph']['original_lines']:
                record=paths[line['path_index']];assert digest(record)==line['path_record_sha256'];item=record['items'][line['item_index']];ei=line['original_primitive_edge_index']
                if item[0]=='l':points=list(item[1:3]);assert ei==0
                elif item[0]=='qu':
                    q=item[1];cycle=[q[0],q[1],q[3],q[2]];points=[cycle[ei],cycle[(ei+1)%4]]
                elif item[0]=='re':
                    x0,y0,x1,y1=item[1];cycle=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)];points=[cycle[ei],cycle[(ei+1)%4]]
                else:raise AssertionError('Unsupported original primitive')
                assert [list(p) for p in points]==line['source_endpoints_pdf_unrotated']
                # MuPDF exposes float32 point/matrix results. Reproduce that
                # representation with independent native y-up arithmetic.
                assert [[float(p[0]),float(np.float32(page.mediabox.height)-np.float32(p[1]))] for p in points]==line['source_endpoints_pdf_native']
                assert not line['source_line_clipped_or_extended'] and not line['implicit_closing_edge_invented'];checked['independent_original_site_edges']+=1
                proof=pixelmap.get(line['id'])
                if proof:
                    a,b=points;box=pymupdf.Rect(min(a[0],b[0])-1,min(a[1],b[1])-1,max(a[0],b[0])+1,max(a[1],b[1])+1)
                    pix=page.get_pixmap(matrix=pymupdf.Matrix(6,6),clip=box,colorspace=pymupdf.csRGB,alpha=False);rgb=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3)
                    for sample in proof['source_samples']:
                        t=sample['fraction'];x=math.floor((a[0]+t*(b[0]-a[0]))*6)-pix.x;y=math.floor((a[1]+t*(b[1]-a[1]))*6)-pix.y;window=rgb[max(0,y-1):y+2,max(0,x-1):x+2]
                        assert window.tolist()==sample['source_neighbourhood_rgb'];matches=bool(np.any(np.max(np.abs(window.astype(float)-np.array(record['color'])*255),axis=2)<=24))
                        assert matches==sample['matching_source_color_present'];checked['independent_original_rgb_neighbourhoods']+=1
                    assert all(s['matching_source_color_present'] for s in proof['source_samples'])==proof['all_samples_supported']
    adjoining=json.loads(adjoining_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text());projection=json.loads(projection_evidence.read_text())
    for registration in r['registrations']:
        archgraph=next(g for g in pyramid['plan_graphs'] if any(c['id']==registration['architectural_plan_candidate_id'] for c in g['candidates']));a=next(c for c in archgraph['candidates'] if c['id']==registration['architectural_plan_candidate_id'])
        site=next(p for p in r['source_pages'] if any(c['id']==registration['site_plan_candidate_id'] for c in p['graph']['candidates']));b=next(c for c in site['graph']['candidates'] if c['id']==registration['site_plan_candidate_id']);mapping=registration['architectural_to_site_corner_indices']
        ae=np.array(a['source_corners_pdf_native'][1])-a['source_corners_pdf_native'][0];be=np.array(b['source_corners_pdf_native'][mapping[1]])-b['source_corners_pdf_native'][mapping[0]]
        alpha=math.atan2(ae[1],ae[0]);beta=math.atan2(be[1],be[0]);reflected=registration['reflection_candidate'];theta=beta+alpha if reflected else beta-alpha
        c,s=math.cos(theta),math.sin(theta);matrix=np.array([[c,s],[s,-c]]) if reflected else np.array([[c,-s],[s,c]])
        assert np.allclose(matrix,registration['orthogonal_matrix'],rtol=0,atol=1e-12);assert abs(abs(np.linalg.det(matrix))-1)<1e-12
        unit=site['graph']['nominal_metres_per_pdf_point'];ratio=archgraph['nominal_metres_per_pdf_point']/unit;A=np.array(a['source_apex_pdf_native']);B=np.array(b['source_apex_pdf_native'])
        predicted=B+np.array([matrix@(np.array(p)-A)*ratio for p in a['source_corners_pdf_native']]);residual=(predicted-np.array(b['source_corners_pdf_native'])[mapping])*unit
        assert np.allclose(predicted,registration['predicted_site_corners_pdf_native'],rtol=0,atol=1e-10);assert np.allclose(residual,registration['corner_residual_vectors_nominal_m'],rtol=0,atol=1e-10)
        ridge=next(p['original_ridge'] for p in adjoining['plan_ridges'] if p['original_ridge']['source_component_id']==registration['original_architectural_ridge_source_id']);pred=B+np.array([matrix@(np.array(p)-A)*ratio for p in ridge['source_endpoints_pdf_native']])
        assert np.allclose(pred,registration['predicted_site_ridge_endpoints_pdf_native'],rtol=0,atol=1e-10);checked['independent_orthogonal_registrations']+=1
        linebyid={l['id']:l for l in site['graph']['original_lines']}
        for comparison in registration['ridge_comparisons']:
            ends=np.array(linebyid[comparison['site_source_line_id']]['source_endpoints_pdf_native'])[comparison['original_site_endpoint_order']];res=(pred-ends)*unit;error=float(max(np.linalg.norm(res,axis=1)))
            assert np.allclose(res,comparison['endpoint_residual_vectors_nominal_m'],rtol=0,atol=1e-10);assert abs(error-comparison['maximum_endpoint_residual_nominal_m'])<1e-10
            assert (error<=.1)==comparison['whole_ridge_endpoints_compatible'];checked['independent_whole_ridge_endpoint_orders']+=1
        support=next(s for s in r['registration_support'] if s['registration_id']==registration['id']);pixelids={p['line_id'] for p in site['line_pixel_checks'] if p['all_samples_supported']}
        valid=all(any(sid in pixelids for sid in group) for group in b['source_perimeter_ids_per_edge']+b['source_spoke_ids_per_corner'])
        matches=[m for m in registration['ridge_comparisons'] if m['whole_ridge_endpoints_compatible'] and m['site_source_line_id'] in pixelids]
        assert matches==support['supported_whole_ridge_matches'];good=valid and max(np.linalg.norm(residual,axis=1))<=.1 and bool(matches)
        assert good==(support['status']=='conditional_compound_roof_registration_supported');assert not support['physical_component_identity_verified'] and not support['world_export_authorized'];checked['independent_correspondence_gates']+=1
    for bridge in r['section_site_camera_candidates']:
        registration=next(rg for rg in r['registrations'] if rg['id']==bridge['registration_id']);pose=next(p for p in projection['projection_candidates'] if p['id']==bridge['parent_projection_id']);matrix=np.array(registration['orthogonal_matrix'])
        assert np.allclose(matrix@pose['candidate_viewer_direction_native_xy'],bridge['candidate_viewer_direction_site_native_xy'],rtol=0,atol=1e-12)
        assert np.allclose(matrix@pose['unit_projection_horizontal_vector'],bridge['candidate_horizontal_direction_site_native_xy'],rtol=0,atol=1e-12)
        assert not bridge['geographic_bearing_verified'] and not bridge['wall_closure_authorized'];checked['independent_section_camera_bridges']+=1
    assert r['world_geometry_additions']==r['accepted_physical_components']==r['training_labels_generated']==0 and not r['wall_closure_authorized'] and not r['geographic_registration_verified']
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_adjoining_sha256':file_hash(adjoining_evidence),'checked':dict(checked)}
    atomic_json(output,receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','adjoining-evidence','projection-evidence','section-evidence','pyramid-evidence','reference-evidence','section-catalogue','site-catalogue','source-directory','fascia-evidence','roof-plan-pdf','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
