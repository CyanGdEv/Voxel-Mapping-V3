"""Independent original-PDF/crop, fixed-marker, position and mesh checks."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pymupdf
from PIL import Image

from voxel_mapper.automatic_facade_preview import build
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(components, views, corpus, preview, output):
    components,views,corpus,preview,output=map(Path,(components,views,corpus,preview,output))
    evidence=json.loads((preview/'facade-preview.json').read_text()); checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(components,views,corpus,temp,max_checks=evidence['contract']['max_checks']);fresh.pop('directory')
        assert digest(fresh)==digest(evidence)
    assert not evidence['world_placement_eligible'] and not evidence['physical_scale_verified']
    assert evidence['accepted_physical_components']==evidence['world_geometry_additions']==evidence['training_labels_generated']==0
    report=json.loads((components/'component-report.json').read_text())
    artwork=json.loads((components/report['artwork_scale_controls']['file']).read_text())
    levels=json.loads((components/report['elevation_level_context']['file']).read_text())
    pairs={p['id']:p for p in artwork['pairs']};markers={m['id']:(p,m) for p in artwork['pages'] for m in p['markers']}
    for row in evidence['target_marker_checks']:
        assert not row['fit_used'];pair=pairs[row['pair_id']]
        assert all(r['key']!=row['key'] for r in pair['controls'])
        originals=[]
        for side in ('subject','reference'):
            for mid in row[side+'_marker_ids']:
                source,marker=markers[mid]
                pdf=corpus/'files'/(source['document_sha256']+'.pdf');assert file_hash(pdf)==source['document_sha256']
                with pymupdf.open(pdf) as doc:
                    page=doc[source['page']-1];path=page.get_drawings()[marker['source_circle_path_index']]
                    center=(path['rect'].tl+path['rect'].br)*.5*native_inverse(page)
                    assert list(center)==marker['center_pdf_native'];assert path['seqno']==marker['source_circle_paint_seqno']
                originals.append(mid);checked['original_target_circle_receipts']+=1
        if 'residual_pdf_points' in row:
            # Explicit scalar equations, no target-dependent solve.
            m=pair['reference_to_subject_linear_row_matrix'];t=pair['reference_to_subject_translation'];x,y=row['reference_center']
            predicted=[x*m[0][0]+y*m[1][0]+t[0],x*m[0][1]+y*m[1][1]+t[1]]
            error=float(np.linalg.norm(np.asarray(predicted)-row['subject_center']))
            assert abs(error-row['residual_pdf_points'])<1e-10;assert predicted==row['predicted_subject_center']
            checked['independent_fixed_target_checks']+=1
        else:assert row['status']=='whole_visible_unique_target_references_required'
    crops={r['id']:r for r in evidence['source_crop_receipts']};gray={}
    for rid,receipt in crops.items():
        path=preview/receipt['file'];assert file_hash(path)==receipt['png_sha256']
        with pymupdf.open(corpus/'files'/(receipt['document_sha256']+'.pdf')) as doc:
            page=doc[receipt['page']-1];pix=page.get_pixmap(matrix=pymupdf.Matrix(receipt['zoom'],receipt['zoom']),
                clip=pymupdf.Rect(receipt['display_clip_points']),alpha=False,colorspace=pymupdf.csGRAY)
            assert hashlib.sha256(pix.tobytes('png')).hexdigest()==receipt['png_sha256']
            assert list(pix.irect)==[int(receipt['pixel_edge_to_display_matrix'][4]*4),int(receipt['pixel_edge_to_display_matrix'][5]*4),
                int(receipt['pixel_edge_to_display_matrix'][4]*4)+pix.width,int(receipt['pixel_edge_to_display_matrix'][5]*4)+pix.height]
        with Image.open(path) as image:gray[rid]=np.asarray(image.convert('L'))
        checked['original_pdf_crop_replays']+=1
    for position in evidence['position_checks']:
        pair=pairs[position['fixed_pair_id']];inverse=np.linalg.inv(np.asarray(pair['reference_to_subject_linear_row_matrix']))
        assert np.allclose(inverse,pair['subject_to_reference_linear_row_matrix'],rtol=0,atol=1e-12)
        axis=np.asarray(position['source_axis_pdf_native'])@inverse;axis/=np.linalg.norm(axis)
        source=next(d for d in artwork['diagnostics'] if digest(d)==position['source_artwork_diagnostic_sha256'])
        target=sorted(float((np.asarray(p)-position['source_origin_pdf_native'])@inverse@axis*source['nominal_metres_per_pdf_point']) for p in position['source_gap_endpoints_pdf_native'])
        for witness in position['witnesses']:
            slope,offset=witness['pixel_x_to_plan_position_affine'];bounds=witness['source_child_bounds_pixels']
            interval=sorted(slope*bounds[i]+offset for i in (0,2));residual=max(abs(a-b) for a,b in zip(target,interval))
            assert abs(residual-witness['maximum_endpoint_residual_m'])<1e-10
            assert witness['within_discovery_tolerance']==(residual<=.25);checked['independent_position_witnesses']+=1
    unique_bands=set()
    for row in evidence['previews']:
        mesh=row['mesh'];level=next(v for v in levels['views'] if v['view_id']==row['view_id'])
        matrix=level['pixel_edge_to_source_display_matrix'];datum=level['relative_reference']['datum_y_display_points']
        inv=json.loads((components/next(r['file'] for r in report['results'] if r['view_id']==row['view_id'])).read_text());unit=inv['nominal_metres_per_pdf_point']
        for name,bounds in [('context_vertices',row['source_parent_bounds_pixels']),('opening_outline_vertices',row['source_child_bounds_pixels'])]:
            expected=[]
            for x,y in [(bounds[0],bounds[3]),(bounds[2],bounds[3]),(bounds[2],bounds[1]),(bounds[0],bounds[1])]:
                expected.append([(x-row['source_parent_bounds_pixels'][0])*matrix[0]*unit,0.,(datum-y*matrix[3]-matrix[5])*unit])
            assert np.allclose(expected,mesh[name],rtol=0,atol=1e-12)
        assert mesh['aperture_triangles']==[] and mesh['wall_thickness_m'] is None
        assert mesh['physical_opening_bottom_m'] is mesh['physical_opening_height_m'] is mesh['physical_wall_height_m'] is None
        assert not row['physical_opening_verified'] and not row['source_geometry_changed'];checked['source_linked_mesh_alternatives']+=1
        rid=row['source_crop_receipt_id']
        if rid in unique_bands:continue
        unique_bands.add(rid);receipt=crops[rid];review=row['bottom_review'];g=gray[rid];lo,start,hi,end=review['search_pixel_interval']
        assert review['selected_physical_bottom_m'] is None and not review['physical_threshold_verified']
        # Derive every threshold run independently from the original-render pixel vector.
        expected=[]
        for threshold in (96,128):
            fractions=(g[start:end,lo:hi]<=threshold).sum(axis=1)/(hi-lo)
            mask=np.r_[False,fractions>=.8,False];edges=np.flatnonzero(mask[1:]!=mask[:-1])
            for a,b in zip(edges[::2],edges[1::2]):
                expected.append((threshold,[start+int(a),start+int(b)],float(fractions[a:b].min())))
        assert len(expected)==len(review['bands'])
        for (threshold,interval,coverage),band in zip(expected,review['bands']):
            assert threshold==band['threshold'] and interval==band['row_interval_pixels'];assert coverage==band['minimum_dark_fraction']
            display=[y/4+receipt['pixel_edge_to_display_matrix'][5] for y in interval]
            assert display==band['display_y_interval'];checked['independent_base_band_witnesses']+=1
        checked['independent_bottom_crops']+=1
    # Record exact printed level identities, without extending their physical roles.
    level_labels=[]
    for page in levels['pages'] if 'pages' in levels else []:
        for record in page['level_review']['records']:
            label=record.get('label')
            if label:level_labels.append({'id':record['id'],'text':label['text'],'datum_y_display_points':record['datum_y_display_points']})
    result={'version':'automatic-unplaced-facade-audit-v1','status':'passed','preview_sha256':file_hash(preview/'facade-preview.json'),
            'component_report_sha256':file_hash(components/'component-report.json'),'fresh_preview_replay_identical':True,
            'counts':evidence['counts'],'checked':dict(checked),'source_level_labels':level_labels,'world_geometry_additions':0,
            'scope':'Source drawing preview only. Raw bounds and separate base bands retained; no accepted wall, aperture or threshold.'}
    atomic_json(output,result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('components','views','corpus','preview','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.components,args.views,args.corpus,args.preview,args.output)))
