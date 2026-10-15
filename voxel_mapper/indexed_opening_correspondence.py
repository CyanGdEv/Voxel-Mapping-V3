"""Width and position queries over retained original jamb/head consensus families."""
import math
import re

import pymupdf
from shapely.geometry import shape

from .raster_opening_scan import width_candidates


def compare(view,projection,frame,region,tolerance,charge):
    result={'frame_id':frame['id'],'source_gap_id':projection['source_gap_id'],'region_id':region['id'],
        'status':'withheld_missing_or_budgeted_opening_index','width_family_candidates':0,'matches':[],
        'physical_correspondence_verified':False}
    scan=view.get('indexed_opening_scan',{})
    if scan.get('status')!='indexed_jamb_head_correspondence_candidates_only':return result
    if (not isinstance(view.get('document_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',view['document_sha256'])
            or type(view.get('page')) is not int or view['page']<1
            or view.get('document_sha256')!=region.get('document_sha256') or view.get('page')!=region.get('page')
            or view.get('view_key_candidate')!=region.get('view_key_candidate')):
        result['status']='withheld_index_region_source_scope';return result
    if any(not isinstance(view.get(k),str) or not re.fullmatch('[0-9a-f]{64}',view[k])
            for k in ('source_png_sha256','indexed_scan_sha256')):
        result['status']='withheld_index_source_hash_binding';return result
    matrix=view.get('pixel_edge_to_pdf_native_matrix')
    if not isinstance(matrix,list) or len(matrix)!=6 or not all(type(v) in (int,float) and math.isfinite(v) for v in matrix):
        result['status']='withheld_index_pixel_transform';return result
    pixel_to_native=pymupdf.Matrix(matrix)
    display=pixel_to_native*(~pymupdf.Matrix(region['unrotated_mupdf_to_pdf_native_matrix']))*pymupdf.Matrix(region['unrotated_mupdf_to_display_matrix'])
    if abs(display.b)>1e-7 or abs(display.c)>1e-7 or display.a<=0 or display.d<=0:
        result['status']='withheld_nonpositive_or_skew_display_pixel_transform';return result
    factor=region['nominal_metres_per_pdf_point_candidate'];unit=display.a*factor
    bounds=shape(region['display_geometry']).bounds;region_width=(bounds[2]-bounds[0])*factor
    families=width_candidates(scan,projection['width_m']/unit,tolerance/unit,charge)
    result['width_family_candidates']=len(families)
    for identity,family in families:
        charge();pixels=family['bounds_pixels']
        observed=[(pixels[i]*display.a+display.e-bounds[0])*factor for i in (0,2)]
        if observed[0]<-tolerance or observed[1]>region_width+tolerance:continue
        for reverse in (False,True):
            interval=[region_width-observed[1],region_width-observed[0]] if reverse else observed
            width_residual=interval[1]-interval[0]-projection['width_m']
            residual=max(abs(interval[i]-projection['position_interval_m'][i]) for i in (0,1))
            if abs(width_residual)>tolerance or residual>tolerance:continue
            result['matches'].append({'frame_id':frame['id'],'source_gap_id':projection['source_gap_id'],
                'region_id':region['id'],'indexed_family_index':identity,
                'first_threshold_pair_index':family['first_pair_index'],
                'second_threshold_pair_indices':family['second_pair_indices'],
                'threshold_correspondence_count':len(family['second_pair_indices']),
                'source_png_sha256':view.get('source_png_sha256'),
                'source_indexed_scan_sha256':view.get('indexed_scan_sha256'),
                'source_bounds_pixels':pixels,'elevation_x_reversed':reverse,
                'width_residual_m':width_residual,'maximum_position_residual_m':residual,
                'region_component_class_candidate':region['component_class_candidate'],
                'facade_width_within_discovery_tolerance':abs(frame['projected_extent_width_m']-region_width)<=tolerance,
                'floor_or_vertical_datum_verified':False,'physical_correspondence_verified':False})
    result['status']='indexed_width_and_position_query_hypotheses_only';return result
