"""Independent native PDF items, whole ridge endpoint arithmetic and face gates."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile

import numpy as np
import pymupdf

from voxel_mapper.section_adjoining_evidence import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output):
    evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output=map(Path,
        (evidence,projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,output))
    path=evidence/'section-adjoining-evidence.json';report=json.loads(path.read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(projection_evidence,section_evidence,pyramid_evidence,reference_evidence,section_catalogue,source_directory,fascia_evidence,roof_plan_pdf,temp,max_checks=report['contract']['max_checks'])
        fresh.pop('directory');assert fresh==report
    projection=json.loads(projection_evidence.read_text());pyramid=json.loads(pyramid_evidence.read_text())
    assert report['status']=='section_adjoining_ridge_diagnostics_only' and report['parent_projection_fresh_replay_identical']
    with pymupdf.open(roof_plan_pdf) as doc:
        for witness in report['original_plan_witnesses']:
            page=doc[0];assert page.cropbox.x0==page.cropbox.y0==0
            record=page.get_cdrawings(extended=True)[witness['original_pdf_path_index']]
            assert digest(record)==witness['original_path_record_sha256']
            item=record['items'][witness['original_pdf_item_index']];assert item[0]=='l'
            assert [[float(p[0]),float(page.mediabox.height-p[1])] for p in item[1:3]]==witness['original_endpoints_pdf_native']
            checked['independent_original_plan_items']+=1
    for sha in sorted({l['document_sha256'] for l in report['source_horizontal_lines']}):
        with pymupdf.open(source_directory/(sha+'.pdf')) as doc:
            page=doc[0];paths=page.get_cdrawings(extended=True)
            for line in report['source_horizontal_lines']:
                if line['document_sha256']!=sha:continue
                record=paths[line['path_index']];item=record['items'][line['item_index']]
                assert digest(record)==line['path_record_sha256'];assert item[0]=='l'
                assert [list(p) for p in item[1:3]]==line['source_endpoints_pdf_unrotated']
                assert record['type']=='s' and record['stroke_opacity']==1 and not record.get('layer') and record['dashes']=='[] 0'
                a,b=line['source_endpoints_pdf_unrotated'];assert a[1]==b[1] and 12<=abs(a[0]-b[0])<=250
                assert not line['source_line_clipped_or_extended'];checked['independent_original_section_items']+=1
                pixel=next((p for p in report['source_line_pixel_checks'] if p['line_id']==line['id']),None)
                if pixel:
                    # Re-render the whole original stroke and check every sampled
                    # RGB window at original coordinates, independently of line_pixels.
                    box=pymupdf.Rect(min(a[0],b[0])-1,a[1]-1,max(a[0],b[0])+1,a[1]+1)
                    pix=page.get_pixmap(matrix=pymupdf.Matrix(6,6),clip=box,alpha=False,colorspace=pymupdf.csRGB)
                    rgb=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3)
                    for sample in pixel['source_samples']:
                        t=sample['fraction'];x=int(np.floor(6*(a[0]+t*(b[0]-a[0]))))-pix.x;y=int(np.floor(6*a[1]))-pix.y
                        window=rgb[max(0,y-1):y+2,max(0,x-1):x+2]
                        assert window.tolist()==sample['source_neighbourhood_rgb']
                        assert bool(np.any(np.max(np.abs(window.astype(float)-np.array(record['color'])*255),axis=2)<=24))==sample['matching_source_color_present']
                        checked['independent_original_rgb_neighbourhoods']+=1
    lines={l['id']:l for l in report['source_horizontal_lines']};posemap={p['id']:p for p in projection['projection_candidates']}
    for row in report['projection_ridge_checks']:
        pose=posemap[row['parent_projection_id']];group=next(g for g in projection['source_groups'] if g['id']==row['source_group_id'])
        plan=next(p for p in report['plan_ridges'] if p['pyramid_candidate_id']==row['original_plan_candidate_id'] and p['original_ridge']['source_component_id']==row['original_ridge_source_id'])
        c=next(c for g in pyramid['plan_graphs'] for c in g['candidates'] if c['id']==row['original_plan_candidate_id']);u=pose['unit_projection_horizontal_vector']
        xs=[group['source_apex_pdf_unrotated'][0]+sum((point[i]-c['source_apex_pdf_native'][i])*u[i] for i in (0,1))*plan['nominal_metres_per_pdf_point']/group['nominal_metres_per_pdf_point'] for point in plan['original_ridge']['source_endpoints_pdf_native']]
        assert np.allclose(xs,row['projected_original_ridge_endpoint_x_pdf_points'],rtol=0,atol=1e-10);checked['independent_whole_ridge_projections']+=1
        for comparison in row['comparisons']:
            line=lines[comparison['source_line_id']];source=sorted(p[0] for p in line['source_endpoints_pdf_unrotated']);residual=[x-y for x,y in zip(sorted(xs),source)]
            assert np.allclose(residual,comparison['source_endpoint_residuals_pdf_points'],rtol=0,atol=1e-10)
            assert (pose['status']=='conditional_source_projection_supported' and abs(xs[1]-xs[0])>1e-10 and max(map(abs,residual))<=.5)==comparison['endpoints_compatible']
            checked['independent_endpoint_comparisons']+=1
    supported_lines={p['line_id'] for p in report['source_line_pixel_checks'] if p['all_samples_supported']}
    for summary in report['conditional_face_constraints']:
        supported=[r for r in report['projection_ridge_checks'] if r['source_group_id']==summary['source_group_id'] and any(c['endpoints_compatible'] and c['source_line_id'] in supported_lines for c in r['comparisons'])]
        ids=sorted({r['parent_projection_id'] for r in supported});assert ids==summary['conditionally_supported_projection_ids']
        visible=sum(posemap[i]['shared_cap_candidate_visible'] for i in ids)
        assert len(ids)==summary['conditionally_supported_projection_count'];assert visible==summary['shared_cap_visible_candidates']
        assert not summary['physical_face_assignment_verified'] and not summary['wall_closure_authorized'] and not summary['parent_orientations_deleted']
        checked['independent_conditional_face_gates']+=1
    assert not report['wall_closure_authorized'] and report['world_geometry_additions']==report['training_labels_generated']==0
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_projection_sha256':file_hash(projection_evidence),'checked':dict(checked)}
    atomic_json(output,receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','projection-evidence','section-evidence','pyramid-evidence','reference-evidence','section-catalogue','source-directory','fascia-evidence','roof-plan-pdf','output'):
        p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
