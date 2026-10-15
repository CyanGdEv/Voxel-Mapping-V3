"""Source contrast-edge fragments for partial jamb review; no gap-filled geometry."""
import base64
import binascii
import hashlib
import math

import numpy as np
from shapely.geometry import shape

from .building_spec import digest

VERSION='partial-jamb-profiles-v1'
RECIPES=((24,220),(48,235))


def _pack(mask):
    raw=np.packbits(mask,bitorder='little').tobytes()
    return {'packed_sha256':hashlib.sha256(raw).hexdigest(),
        'packed_bits_base64':base64.b64encode(raw).decode('ascii')}


def build(gray):
    gray=np.asarray(gray)
    if gray.dtype!=np.uint8 or gray.ndim!=2 or not gray.size or gray.size>6000000 or max(gray.shape)>3000:
        raise ValueError('Bounded source grayscale raster required')
    gradient=np.zeros(gray.shape,dtype='int16');gradient[:,1:]=abs(np.diff(gray.astype('int16'),axis=1))
    return {'version':VERSION,'size_pixels':[gray.shape[1],gray.shape[0]],
        'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),
        'variants':[{'edge_difference_threshold':edge,'head_dark_threshold':head,
            'edge_mask':_pack(gradient>=edge),'head_mask':_pack(gray<head)} for edge,head in RECIPES],
        'physical_opening_verified':False,'world_geometry_additions':0}


def _unpack(packet,height,width):
    length=(height*width+7)//8;encoded=packet['packed_bits_base64']
    if not isinstance(encoded,str) or len(encoded)!=4*((length+2)//3):raise ValueError('Invalid packed source mask length')
    raw=base64.b64decode(encoded,validate=True)
    if len(raw)!=length or hashlib.sha256(raw).hexdigest()!=packet['packed_sha256']:
        raise ValueError('Source mask checksum mismatch')
    return np.unpackbits(np.frombuffer(raw,dtype='uint8'),count=height*width,bitorder='little').reshape(height,width).astype(bool)


def _runs(mask,offset):
    changes=np.flatnonzero(np.diff(np.r_[False,mask,False].astype('int8')))
    return [[int(a)+offset,int(b)+offset] for a,b in zip(changes[::2],changes[1::2])]


def query(view,projection,frame,region,display,factor,tolerance,charge):
    """Every qualifying column pair and head row; lower bounds remain observed evidence extents."""
    result={'status':'withheld_missing_partial_jamb_evidence_or_level','matches':[],
        'frame_id':frame['id'],'source_gap_id':projection['source_gap_id'],'region_id':region['id'],
        'physical_opening_verified':False,'complete_wall_component_scope_verified':False}
    packet=view.get('jamb_profile_evidence');reference=view.get('relative_level_reference',{})
    if not packet or reference.get('status')!='unverified_source_relative_shop_level':return result
    if (reference.get('document_sha256')!=view.get('document_sha256') or reference.get('page')!=view.get('page')
            or reference.get('view_key_candidate')!=view.get('view_key_candidate')
            or reference.get('nominal_metres_per_pdf_point_candidate')!=factor):return result
    try:
        if packet.get('version')!=VERSION:raise ValueError('Unknown source profile version')
        width,height=packet['size_pixels']
        if (any(type(v) is not int or not 1<=v<=3000 for v in (width,height)) or width*height>6000000
                or packet['source_gray_sha256']!=view['indexed_opening_scan']['source_gray_sha256']
                or len(packet['variants'])!=2):raise ValueError('Invalid source profile binding')
        edges=[];heads=[]
        for variant,(edge,head) in zip(packet['variants'],RECIPES):
            if variant['edge_difference_threshold']!=edge or variant['head_dark_threshold']!=head:
                raise ValueError('Unknown source profile recipe')
            edges.append(_unpack(variant['edge_mask'],height,width))
            heads.append(_unpack(variant['head_mask'],height,width))
    except (ValueError,KeyError,TypeError,binascii.Error):
        result['status']='withheld_invalid_source_profile_masks';return result
    unit=display.a*factor;vertical_unit=display.d*factor
    level_pixel=(reference['datum_y_display_points']-display.f)/display.d
    if not 25<level_pixel<height-1:
        result['status']='withheld_printed_level_outside_profile_raster';return result
    lower_limit=min(height-1,int(math.ceil(level_pixel+tolerance/vertical_unit)))
    first=max(1,int(math.floor(level_pixel))-700)
    head_rows=np.arange(first,int(math.floor(level_pixel))-23,dtype=int)
    bounds=shape(region['display_geometry']).bounds;region_width=(bounds[2]-bounds[0])*factor
    head_prefix=[np.pad(np.cumsum(mask,axis=1,dtype=np.uint16),((0,0),(1,0))) for mask in heads]
    def columns(expected):
        profiles=[]
        for x in range(max(1,int(math.ceil(expected-tolerance/unit))),min(width,int(math.floor(expected+tolerance/unit))+1)):
            charge();admissible=np.ones(len(head_rows),dtype=bool);ends=[];fractions=[];near=[];censored=[]
            for mask in edges:
                source=np.flatnonzero(mask[first:lower_limit,x])+first
                if not len(source):admissible[:]=False;break
                end=int(source[-1])+1;ends.append(end)
                prefix=np.r_[0,np.cumsum(mask[:,x])];lengths=end-head_rows-1
                fraction=(prefix[end]-prefix[head_rows+1])/np.maximum(1,lengths)
                admissible &= (lengths>=24)&(fraction>=.8)
                fractions.append(fraction)
                clipped=end==lower_limit and bool(mask[lower_limit,x]);censored.append(clipped)
                near.append(abs((level_pixel-end)*vertical_unit)<=tolerance and not clipped)
            if admissible.any():profiles.append({'column':x,'admissible':admissible,'ends':ends,
                'fractions':fractions,'near':near,'censored':censored})
            if len(profiles)>128:raise OverflowError
        return profiles
    for reverse in (False,True):
        desired=projection['position_interval_m']
        if reverse:desired=[region_width-desired[1],region_width-desired[0]]
        expected=[(bounds[0]+value/factor-display.e)/display.a for value in desired]
        if desired[0]<-tolerance or desired[1]>region_width+tolerance:continue
        lefts,rights=[columns(value) for value in expected]
        for left in lefts:
            for right in rights:
                charge();x0,x1=left['column'],right['column']
                if not 20<=x1-x0<=600:continue
                observed=[(x*display.a+display.e-bounds[0])*factor for x in (x0,x1)]
                residual=max(abs(observed[i]-desired[i]) for i in (0,1))
                width_residual=(x1-x0)*unit-projection['width_m']
                if residual>tolerance or abs(width_residual)>tolerance:continue
                if not (all(left['near']) or all(right['near'])):continue
                supported=[]
                for index in np.flatnonzero(left['admissible']&right['admissible']):
                    charge();y=int(head_rows[index]);support=[float((p[y,x1]-p[y,x0])/(x1-x0)) for p in head_prefix]
                    if min(support)<.9:continue
                    supported.append({'row':y,'head_dark_fractions':support,
                        'left_edge_support_fractions':[float(v[index]) for v in left['fractions']],
                        'right_edge_support_fractions':[float(v[index]) for v in right['fractions']]})
                if not supported:continue
                start=supported[0]['row']+1;profiles=[]
                for variant,mask in enumerate(edges):
                    for side,profile in [('left',left),('right',right)]:
                        x=profile['column'];end=profile['ends'][variant]
                        profiles.append({'variant_index':variant,'side':side,'adjacent_source_pixel_columns':[x-1,x],
                            'review_interval_pixels':[start,end],
                            'supported_row_intervals':_runs(mask[start:end,x],start),
                            'unsupported_row_intervals':_runs(~mask[start:end,x],start),
                            'unsupported_interval_to_printed_level_pixels':[end,int(math.floor(level_pixel))] if end<int(math.floor(level_pixel)) else None,
                            'lowest_support_extent_censored':profile['censored'][variant],
                            'nominal_lowest_support_above_printed_level_m':(level_pixel-end)*vertical_unit,
                            'lowest_support_within_level_discovery_tolerance':profile['near'][variant]})
                row_mask=np.zeros(height,dtype=bool);row_mask[[r['row'] for r in supported]]=True
                match={'frame_id':frame['id'],'source_gap_id':projection['source_gap_id'],'region_id':region['id'],
                    'jamb_column_pair_pixels':[x0,x1],'elevation_x_reversed':reverse,
                    'width_residual_m':width_residual,'maximum_position_residual_m':residual,
                    'head_row_bands_pixels':_runs(row_mask,0),'supported_head_rows':supported,
                    'source_edge_profiles':profiles,'source_png_sha256':view['source_png_sha256'],
                    'source_profile_evidence_sha256':view.get('jamb_profile_evidence_sha256'),
                    'source_level_reference_id':reference['reference_id'],'printed_level_pixel_candidate':level_pixel,
                    'nominal_head_height_intervals_above_printed_level_m':[
                        [(level_pixel-(b-1))*vertical_unit,(level_pixel-a)*vertical_unit] for a,b in _runs(row_mask,0)],
                    'comparison_reference_component_class_candidate':region['component_class_candidate'],
                    'physical_opening_verified':False,'physical_floor_role_verified':False,
                    'continuous_jambs_verified':False,'unsupported_intervals_filled':False,
                    'physical_lower_endpoints_inferred':False,'complete_wall_component_scope_verified':False}
                match['id']=digest(match);result['matches'].append(match)
                if len(result['matches'])>1024:raise OverflowError
    result.update(status='unverified_partial_level_reaching_jamb_profiles',
        recipe={'edge_difference_thresholds':[24,48],'head_dark_thresholds':[220,235],
            'minimum_edge_support_fraction':.8,'minimum_head_dark_fraction':.9,
            'minimum_review_height_pixels':24,'maximum_review_height_pixels':700,
            'lower_extent_basis':'last source edge in the printed-level review band, not a physical jamb endpoint'},
        limitations=['Head rows may be shutter lines, rails, shadows or unrelated drafting strokes.',
            'Every source support fragment and missing interval remains explicit; no complete opening or occlusion cause is verified.'])
    return result
