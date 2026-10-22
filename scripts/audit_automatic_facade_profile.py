"""Independently audit source profile cells, masks and lossless planar mesh areas."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from scipy import ndimage

from voxel_mapper.automatic_facade_profile import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(profile,preview,components,views,corpus,output):
    profile,preview,components,views,corpus,output=map(Path,(profile,preview,components,views,corpus,output))
    evidence=json.loads((profile/'facade-profile.json').read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(preview,components,views,corpus,temp,max_checks=evidence['contract']['max_checks']);fresh.pop('directory')
        assert digest(fresh)==digest(evidence)
    assert evidence['world_geometry_additions']==evidence['accepted_physical_components']==evidence['training_labels_generated']==0
    assert not evidence['world_placement_eligible'] and not evidence['physical_wall_base_verified'] and not evidence['physical_scale_verified']
    assert evidence['wall_thickness_m'] is evidence['roof_pitch_degrees'] is None
    source=json.loads((views/'view-candidates.json').read_text());source_views={v['id']:v for p in source['pages'] for v in p['views']}
    previous=json.loads((preview/'facade-preview.json').read_text());old={p['id']:p for p in previous['previews']}
    for group in evidence['profiles']:
        view=source_views[group['view_id']];png=views/view['render']['png'];assert file_hash(png)==view['render']['png_sha256']
        with Image.open(png) as image:gray=np.asarray(image.convert('L'))
        receipt=next(r for r in evidence['source_raster_receipts'] if r['view_id']==group['view_id'])
        assert hashlib.sha256(gray.tobytes()).hexdigest()==receipt['source_gray_sha256'];checked['original_source_rasters']+=1
        for row in group['source_opening_alternatives']:
            original=old[row['id']]
            assert all(row[k]==original[k] for k in row);checked['source_opening_witness_links']+=1
        x0,y0,x1,y1=group['source_parent_bounds_pixels'];mpp=group['nominal_metres_per_source_pixel'];level=group['printed_level_pixel']
        for variant in group['variants']:
            if variant['status']!='source_profile_masks_only':continue
            # Independent outside flood fill; kernel instead labels every original white region.
            dark=gray<variant['threshold'];white=~dark;seeds=np.zeros_like(white)
            seeds[0,:]=white[0,:];seeds[-1,:]=white[-1,:];seeds[:,0]=white[:,0];seeds[:,-1]=white[:,-1]
            outside=ndimage.binary_propagation(seeds,mask=white);closed=white&~outside;solid=~outside
            labels,_=ndimage.label(white);selected=np.zeros_like(white);ids=[]
            left,right=variant['source_upper_span_pixels'];first=variant['first_full_width_row'];borders=set(np.unique(labels[seeds]).tolist())
            for identity,box in enumerate(ndimage.find_objects(labels),1):
                if box is None or identity in borders or box[0].stop>y0 or box[0].stop<first:continue
                if box[1].start>=left and box[1].stop<=right:
                    ids.append(identity);selected[box]|=labels[box]==identity
            assert ids==[r['label'] for r in variant['roof_source_regions']]
            for record in variant['roof_source_regions']:
                a,b,c,d=record['bounds_pixels'];membership=labels[b:d,a:c]==record['label']
                assert int(membership.sum())==record['source_cell_count']
                assert hashlib.sha256(np.packbits(membership).tobytes()).hexdigest()==record['source_membership_sha256']
                assert closed[b:d,a:c][membership].all();checked['closed_roof_source_regions']+=1
            # Explicit four-neighbour adjacency, without the kernel's binary_dilation call.
            adjacent=np.zeros_like(selected);adjacent[1:]|=selected[:-1];adjacent[:-1]|=selected[1:]
            adjacent[:,1:]|=selected[:,:-1];adjacent[:,:-1]|=selected[:,1:]
            roof=selected|(adjacent&dark);wall=np.zeros_like(white)
            for record in variant['ground_columns']:
                x=record['column'];mid=(gray[y0:y1,x]>=128)&(gray[y0:y1,x]<=224)
                breaks=np.flatnonzero(~mid);top=y0+int(breaks[-1])+1 if len(breaks) else y0
                supported=y1-top>=16;assert record['shade_row_interval']==[top,y1] and record['supported']==supported
                assert not record['contact_role_verified']
                if supported:wall[y0:top,x]=solid[y0:top,x]
                checked['original_ground_column_runs']+=1
            for name,expected in [('roof',roof),('wall',wall)]:
                surface=variant[name+'_surface'];mask_receipt=variant[name+'_mask_receipt'];path=profile/mask_receipt['file']
                assert file_hash(path)==mask_receipt['png_sha256']
                with Image.open(path) as image:mask=np.asarray(image)>0
                np.testing.assert_array_equal(mask,expected)
                assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==surface['source_grid_mask_sha256']
                rebuilt=np.zeros_like(mask);pixel_area=0
                for index,(a,b,c,d) in enumerate(surface['source_rectangles_pixels']):
                    assert 0<=a<c<=mask.shape[1] and 0<=b<d<=mask.shape[0]
                    assert not rebuilt[b:d,a:c].any() and mask[b:d,a:c].all()
                    rebuilt[b:d,a:c]=True;pixel_area+=(c-a)*(d-b)
                    points=surface['vertices_nominal_local_m'][4*index:4*index+4]
                    expected_points=[[(x-x0)*mpp,0.,(level-y)*mpp] for x,y in [(a,d),(c,d),(c,b),(a,b)]]
                    assert np.allclose(points,expected_points,rtol=0,atol=1e-12)
                    assert surface['triangles'][2*index:2*index+2]==[[4*index,4*index+1,4*index+2],[4*index,4*index+2,4*index+3]]
                    checked['lossless_source_rectangles']+=1;checked['source_mesh_triangles']+=2
                np.testing.assert_array_equal(rebuilt,mask)
                assert pixel_area==surface['source_cell_count']==int(mask.sum())
                assert abs(surface['projected_area_nominal_m2']-pixel_area*mpp*mpp)<1e-10
                polygon_mask=rasterize([(p,1) for p in surface['source_polygons_pixels']],out_shape=mask.shape)>0 if mask.any() else np.zeros_like(mask)
                np.testing.assert_array_equal(polygon_mask,mask)
                assert not surface['holes_are_verified_apertures'] and not surface['source_gap_repair_applied'] and not surface['physical_surface_verified']
                assert surface['wall_thickness_m'] is surface['roof_pitch_degrees'] is None
                checked['independent_source_masks']+=1
            assert int(np.count_nonzero(roof&wall))==variant['source_roof_wall_overlap_cells']
            assert not variant['source_roof_wall_overlap_repaired'];checked['separate_threshold_variants']+=1
        if group['threshold_comparison']:
            for name in ('roof','wall'):
                masks=[]
                for variant in group['variants']:
                    with Image.open(profile/variant[name+'_mask_receipt']['file']) as image:masks.append(np.asarray(image)>0)
                a,b=masks;comparison=group['threshold_comparison'][name]
                assert comparison['different_cells']==int(np.count_nonzero(a^b))
                assert comparison['shared_cells']==int(np.count_nonzero(a&b));assert not comparison['variants_merged']
                checked['independent_threshold_comparisons']+=1
    result={'version':'automatic-facade-profile-audit-v1','status':'passed','fresh_profile_replay_identical':True,
        'source_profile_sha256':file_hash(profile/'facade-profile.json'),'source_preview_sha256':file_hash(preview/'facade-preview.json'),
        'counts':evidence['counts'],'checked':dict(checked),'world_geometry_additions':0,
        'scope':'Exact original raster-cell projections; no physical wall/roof/aperture/floor identity, depth, pitch, thickness or placement acceptance.'}
    atomic_json(output,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('profile','preview','components','views','corpus','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit(a.profile,a.preview,a.components,a.views,a.corpus,a.output)))
