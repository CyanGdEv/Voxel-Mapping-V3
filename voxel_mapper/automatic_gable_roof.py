"""Source-derived pitched-roof hypotheses and independent raster gable checks."""
from collections import Counter,defaultdict
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
import pymupdf
from rasterio.features import rasterize
from scipy import ndimage
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,mapping,shape

from . import automatic_facade_profile,automatic_facade_preview,automatic_opening_links,drawing_page_tools
from .generation_cycles import atomic_json,file_hash
from .reconstruction_evidence_queue import digest

VERSION='automatic-gable-roof-review-v1'
ANGLES=np.r_[np.arange(-65,-14.9,.5),np.arange(15,65.1,.5)]


def panel_heights(group,charge):
    """Find a source slat-end cohort before looking at any gable measurements."""
    result=[];mpp=group['nominal_metres_per_source_pixel'];level=group['printed_level_pixel']
    for variant in group['variants']:
        charge();row={'threshold':variant['threshold'],'status':'dominant_tall_source_panel_cohort_required'}
        if variant['status']!='source_profile_masks_only':result.append(row);continue
        regions=[r for r in variant['roof_source_regions'] if r['bounds_pixels'][3]-r['bounds_pixels'][1]>=24
            and r['bounds_pixels'][2]-r['bounds_pixels'][0]<=16]
        counts=Counter((r['bounds_pixels'][1],r['bounds_pixels'][3]) for r in regions)
        if not counts:result.append(row);continue
        maximum=max(counts.values());modes=sorted(k for k,v in counts.items() if v==maximum)
        if len(modes)!=1 or maximum<6 or maximum<.5*len(regions):result.append(row);continue
        top,bottom=modes[0];cohort=[r for r in regions if (r['bounds_pixels'][1],r['bounds_pixels'][3])==(top,bottom)]
        span=variant['source_upper_span_pixels']
        if max(r['bounds_pixels'][2] for r in cohort)-min(r['bounds_pixels'][0] for r in cohort)<.5*(span[1]-span[0]):
            result.append(row);continue
        ridge=min(r[1] for r in variant['roof_surface']['source_rectangles_pixels'])
        row.update(status='source_long_roof_panel_height_hypothesis',source_cohort_bounds_y=[top,bottom],
            source_cohort_region_ids=[r['label'] for r in cohort],source_cohort_records_sha256=digest(cohort),
            source_ridge_grid_y=ridge,source_eave_grid_y=bottom,
            nominal_length_m=(span[1]-span[0])*mpp,nominal_ridge_height_m=(level-ridge)*mpp,
            nominal_eave_height_m=(level-bottom)*mpp,
            source_grid_step_nominal_m=mpp,physical_roof_edge_roles_verified=False)
        row['id']=digest([VERSION,group['id'],row]);result.append(row)
    return result


def plan_triples(inventory,axis,length,charge):
    """Retain all aligned original-line triples, without fitting or moving endpoints."""
    axis=np.asarray(axis,float)
    if axis.shape!=(2,) or not np.isfinite(axis).all() or abs(np.linalg.norm(axis)-1)>1e-6:
        raise ValueError('Finite unit source roof axis required')
    unit=inventory['nominal_metres_per_pdf_point']
    if not math.isfinite(unit) or unit<=0 or not math.isfinite(length) or length<=0:raise ValueError('Finite nominal roof dimensions required')
    if len(inventory['source_components'])>4096:raise OverflowError('roof_plan_component_budget')
    normal=np.array([-axis[1],axis[0]]);lines=[]
    for component in inventory['source_components']:
        charge();geometry=component['geometry']
        if (geometry['type']!='LineString' or len(geometry['coordinates'])!=2
                or component['curve_approximation']['cubic_segments']!=0
                or component.get('rendering_status')!='supported_straight_unclipped_polyline'):continue
        points=np.asarray(geometry['coordinates'],float)
        if not np.isfinite(points).all():raise ValueError('Finite original roof line required')
        delta=points[1]-points[0];size=float(np.linalg.norm(delta))
        if not size or abs(float(delta@axis/size))<math.cos(math.radians(5)) or abs(size*unit-length)>.25:continue
        along=points@axis*unit;cross=points@normal*unit;order=np.argsort(along)
        if max(cross)-min(cross)>.25:continue
        row={'source_component_id':component['id'],'source_component_sha256':digest(component),
            'source_endpoints_pdf_native':geometry['coordinates'],'nominal_length_m':size*unit,
            'along_interval_nominal_m':sorted(along.tolist()),'cross_at_source_start_nominal_m':float(cross[order[0]]),
            'source_start_point_pdf_native':points[order[0]].tolist(),'source_points_moved':False}
        row['id']=digest([VERSION,inventory['view_id'],row]);lines.append(row)
        if len(lines)>64:raise OverflowError('roof_plan_parallel_line_budget')
    triples=[]
    for entries in combinations(lines,3):
        charge();ordered=sorted(entries,key=lambda r:(r['cross_at_source_start_nominal_m'],r['id']))
        offsets=[r['cross_at_source_start_nominal_m'] for r in ordered];a=offsets[1]-offsets[0];b=offsets[2]-offsets[1]
        if min(a,b)<1 or a+b>40 or abs(a-b)>.25:continue
        if max(max(r['along_interval_nominal_m'][i] for r in ordered)-min(r['along_interval_nominal_m'][i] for r in ordered) for i in (0,1))>.25:continue
        row={'source_line_ids':[r['id'] for r in ordered],'source_offsets_nominal_m':offsets,
            'nominal_left_run_m':a,'nominal_right_run_m':b,'nominal_depth_m':a+b,
            'source_line_intervals_nominal_m':[r['along_interval_nominal_m'] for r in ordered],
            'status':'parallel_eave_ridge_eave_hypothesis','physical_line_roles_verified':False,'symmetry_forced':False}
        row['id']=digest([VERSION,row]);triples.append(row)
        if len(triples)>128:raise OverflowError('roof_plan_triple_budget')
    return {'source_view_id':inventory['view_id'],'source_axis_pdf_native':axis.tolist(),
        'source_normal_pdf_native':normal.tolist(),'lines':lines,'triples':triples}


def exclusion_mask(inventory,page,pixel_native,size,charge):
    """Exclude native vector/text ink from raster-only slope proposals, retaining receipts."""
    inverse=~pymupdf.Matrix(pixel_native);affine=[inverse.a,inverse.c,inverse.b,inverse.d,inverse.e,inverse.f]
    geometries=[];records=[]
    if len(inventory['source_components'])>4096:raise OverflowError('gable_native_component_budget')
    for component in inventory['source_components']:
        charge();geometry=affine_transform(shape(component['geometry']),affine).buffer(1.5)
        if not geometry.intersects(Polygon([(0,0),(size[0],0),(size[0],size[1]),(0,size[1])])):continue
        geometries.append(geometry);records.append({'source_component_id':component['id'],'source_component_sha256':digest(component),
            'geometry_pixels':mapping(geometry),'kind':'native_component_excluded_from_raster_proposals'})
    traces=page.get_texttrace()
    if len(traces)>10000:raise OverflowError('gable_source_text_budget')
    transform=drawing_page_tools.native_inverse(page)*inverse
    for index,trace in enumerate(traces):
        charge();box=pymupdf.Rect(trace['bbox']);geometry=Polygon([tuple(p*transform) for p in (box.tl,box.tr,box.br,box.bl)]).buffer(1.)
        if geometry.is_empty or not geometry.intersects(Polygon([(0,0),(size[0],0),(size[0],size[1]),(0,size[1])])):continue
        geometries.append(geometry);records.append({'source_texttrace_index':index,'source_bbox_unrotated_mupdf':list(box),
            'geometry_pixels':mapping(geometry),'kind':'native_text_excluded_from_raster_proposals'})
    mask=rasterize([(mapping(g),1) for g in geometries],out_shape=(size[1],size[0]),all_touched=True)>0 if geometries else np.zeros((size[1],size[0]),bool)
    return mask,{'records':records,'source_mask_sha256':hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest(),
        'source_image_changed':False,'native_physical_edges_may_be_excluded':True}


def slope_lines(gray,excluded,threshold,charge):
    """Bounded Hough proposals; fixed even-column fit and odd-column source checks."""
    if gray.dtype!=np.uint8 or gray.ndim!=2 or gray.size>6000000 or max(gray.shape)>3000 or excluded.shape!=gray.shape or excluded.dtype!=bool:
        raise ValueError('Bounded original gray raster and boolean exclusion mask required')
    if threshold not in (220,235):raise ValueError('Original source raster thresholds required')
    dark=gray<threshold;gx=ndimage.sobel(dark.astype(float),axis=1);gy=ndimage.sobel(dark.astype(float),axis=0)
    orientation=(np.rad2deg(np.arctan2(-gx,gy))+90)%180-90
    eligible=dark&~excluded&(abs(orientation)>=15)&(abs(orientation)<=65)&(np.hypot(gx,gy)>=1)
    y,x=np.nonzero(eligible);angles=orientation[y,x]
    if len(x)>65536:raise OverflowError('gable_source_edge_pixel_budget')
    radius=math.ceil(math.hypot(*gray.shape));votes=np.zeros((len(ANGLES),2*radius+1),np.int32)
    for i,angle in enumerate(ANGLES):
        charge();rad=math.radians(angle);keep=abs(angles-angle)<=12
        bins=np.rint(y[keep]*math.cos(rad)-x[keep]*math.sin(rad)).astype(int)+radius
        votes[i]=np.bincount(bins,minlength=2*radius+1)
    peaks=np.argwhere((votes>=48)&(votes==ndimage.maximum_filter(votes,size=(5,5),mode='constant')))
    if len(peaks)>256:raise OverflowError('gable_hough_peak_budget')
    lines=[];members={}
    for i,j in peaks:
        charge();angle=float(ANGLES[i]);rho=int(j-radius);rad=math.radians(angle)
        ids=np.flatnonzero((abs(angles-angle)<=12)&(abs(y*math.cos(rad)-x*math.sin(rad)-rho)<=1.5))
        if len(ids)<48:continue
        ids=ids[np.lexsort((y[ids],x[ids]))];xx=x[ids];yy=y[ids]
        if xx[-1]-xx[0]<64:continue
        fit=xx%2==0;check=~fit
        if min(int(fit.sum()),int(check.sum()))<16:continue
        if len(ids)>8192:raise OverflowError('gable_line_source_pixel_budget')
        design=np.c_[xx[fit],np.ones(int(fit.sum()))];m,b=np.linalg.lstsq(design,yy[fit],rcond=None)[0]
        residual=np.abs(m*xx+b-yy)/math.sqrt(1+m*m)
        if not math.tan(math.radians(15))<=abs(m)<=math.tan(math.radians(65)) or max(residual)>3:continue
        seed={'angle_degrees':angle,'normal_offset_pixels':rho,'votes':int(votes[i,j])}
        key=hashlib.sha256(np.asarray(sorted((y[ids]*gray.shape[1]+x[ids]).tolist()),dtype='<u8').tobytes()).hexdigest()
        if key in members:members[key]['hough_seeds'].append(seed);continue
        columns=np.unique(xx);gaps=[[int(a+1),int(b)] for a,b in zip(columns[:-1],columns[1:]) if b>a+1]
        row={'slope':float(m),'intercept':float(b),'pitch_magnitude_degrees':abs(math.degrees(math.atan(m))),
            'source_x_interval':[int(xx.min()),int(xx.max())],
            'source_pixels':[{'x':int(a),'y':int(bb),'gray':int(gray[bb,a]),'role':'fit' if a%2==0 else 'check'} for a,bb in zip(xx,yy)],
            'source_membership_sha256':key,'hough_seeds':[seed],
            'fit_max_normal_residual_pixels':float(max(residual[fit])),
            'check_max_normal_residual_pixels':float(max(residual[check])),
            'unsupported_column_intervals':gaps,'source_gaps_filled':False,
            'fit_role_recipe':'even_original_columns_fit_odd_original_columns_check_before_fit_no_outlier_removal',
            'physical_roof_edge_verified':False}
        row['id']=digest([VERSION,threshold,hashlib.sha256(gray.tobytes()).hexdigest(),hashlib.sha256(excluded.astype('uint8').tobytes()).hexdigest(),key]);members[key]=row;lines.append(row)
        if len(lines)>128:raise OverflowError('gable_source_line_budget')
    return {'threshold':threshold,'eligible_source_edge_pixels':len(x),'hough_peak_count':len(peaks),
        'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),'lines':lines}


def gable_pairs(lines,metres_per_pixel,level_pixel,charge):
    if not np.isfinite([metres_per_pixel,level_pixel]).all() or metres_per_pixel<=0:raise ValueError('Finite source gable scale required')
    result=[]
    for a in lines:
        if a['slope']>=0:continue
        for b in lines:
            if b['slope']<=0:continue
            charge();x=(b['intercept']-a['intercept'])/(a['slope']-b['slope']);y=a['slope']*x+a['intercept']
            if not (a['source_x_interval'][0]+32<x<b['source_x_interval'][1]-32 and
                a['source_x_interval'][0]-12<=x<=a['source_x_interval'][1]+12 and b['source_x_interval'][0]-12<=x<=b['source_x_interval'][1]+12):continue
            row={'left_line_id':a['id'],'right_line_id':b['id'],'inferred_ridge_pixel':[float(x),float(y)],
                'nominal_ridge_height_m':float((level_pixel-y)*metres_per_pixel),
                'left_pitch_degrees':a['pitch_magnitude_degrees'],'right_pitch_degrees':b['pitch_magnitude_degrees'],
                'ridge_is_original_source_vertex':False,'ridge_is_line_intersection_hypothesis':True,
                'physical_gable_identity_verified':False,'independent_depth_measurement_m':None}
            row['id']=digest([VERSION,row]);result.append(row)
            if len(result)>512:raise OverflowError('gable_pair_budget')
    return result


def roof_mesh(length,left_run,right_run,eave,ridge):
    values=[length,left_run,right_run,eave,ridge]
    if not all(type(v) in (int,float) and math.isfinite(v) for v in values) or min(length,left_run,right_run)<=0 or ridge<=eave:
        raise ValueError('Finite positive source roof dimensions and rise required')
    depth=left_run+right_run;y0=-depth/2;yr=y0+left_run;y1=depth/2
    vertices=[[-length/2,y0,eave],[length/2,y0,eave],[-length/2,yr,ridge],[length/2,yr,ridge],[-length/2,y1,eave],[length/2,y1,eave]]
    return {'coordinate_frame':'unplaced nominal metres; x longitudinal, y transverse, z relative to printed Shop Level',
        'vertices':vertices,'triangles':[[0,1,3],[0,3,2],[2,3,5],[2,5,4]],
        'left_pitch_degrees':math.degrees(math.atan2(ridge-eave,left_run)),
        'right_pitch_degrees':math.degrees(math.atan2(ridge-eave,right_run)),
        'assembly_hypothesis':'constant longitudinal ridge and eaves; native parallel-triple transverse positions; no forced symmetry',
        'continuous_roof_planes_are_assumed':True,'source_mask_holes_incorporated':False,
        'wall_mesh':None,'fascia_mesh':None,'openings_carved':0,'physical_surface_verified':False,'world_placement_eligible':False}


def _load(path):
    path=Path(path)
    if path.stat().st_size>64000000:raise ValueError('Bounded gable roof input required')
    return json.loads(path.read_text())


def build(profile,preview,components,views,corpus,output,*,max_checks=100000):
    automatic_opening_links.bounded_work(max_checks)
    profile,preview,components,views,corpus,output=map(Path,(profile,preview,components,views,corpus,output))
    previous=_load(profile/'facade-profile.json')
    with tempfile.TemporaryDirectory() as temp:
        replay=automatic_facade_profile.build(preview,components,views,corpus,temp,max_checks=previous['contract']['max_checks']);replay.pop('directory')
        if digest(previous)!=digest(replay):raise ValueError('Source facade profile replay changed')
    for group in previous['profiles']:
        for variant in group['variants']:
            for name in ('roof','wall'):
                receipt=variant.get(name+'_mask_receipt')
                if receipt and file_hash(profile/receipt['file'])!=receipt['png_sha256']:raise ValueError('Source facade profile mask changed')
    report,vr,inventories,source_views,reviews=automatic_facade_preview._verified_inputs(components,views,corpus)
    contract={'version':VERSION,'source_profile_sha256':file_hash(profile/'facade-profile.json'),
        'component_report_sha256':file_hash(components/'component-report.json'),'view_report_sha256':file_hash(views/'view-report.json'),
        'source_preview_sha256':file_hash(preview/'facade-preview.json'),'implementation_sha256':file_hash(Path(__file__)),
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (automatic_facade_profile,automatic_facade_preview,
            automatic_opening_links,drawing_page_tools)},'source_profile_contract':previous['contract'],'max_checks':max_checks}
    result={'version':VERSION,'contract':contract,'status':'conditional_unplaced_pitched_roof_review_only','checks':0,
        'long_profile_reviews':[],'plan_reviews':[],'gable_views':[],'models':[],'gable_checks':[],
        'recipe':{'original_raster_thresholds':[220,235],'source_slope_angle_range_degrees':[15,65],
            'hough_angle_step_degrees':.5,'hough_gradient_orientation_window_degrees':12,'hough_normal_band_pixels':1.5,
            'minimum_hough_votes':48,'minimum_line_points':48,'minimum_line_x_span_pixels':64,'minimum_fit_and_check_pixels':16,
            'maximum_fit_and_check_normal_residual_pixels':3,'fit_roles':'even_original_columns_fit_odd_columns_check_no_outlier_removal',
            'native_vector_exclusion_buffer_pixels':1.5,'native_text_exclusion_buffer_pixels':1,
            'maximum_plan_span_alignment_or_spacing_difference_nominal_m':.25,
            'maximum_independent_gable_ridge_difference_nominal_m':.25,'maximum_independent_gable_pitch_difference_degrees':1.,
            'source_points_moved':False,'source_gaps_filled':False},
        'physical_roof_identity_verified':False,'physical_scale_verified':False,'world_placement_eligible':False,
        'accepted_physical_components':0,'world_geometry_additions':0,'training_labels_generated':0,
        'unresolved':['Physical roof/line/gable identity, design state and scale','Adjacent small gable/wing association',
            'Complete wall/fascia/opening geometry and floor roles','Independent geographic registration and vertical datum']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('gable_roof_work_budget')
    records=reviews['building_facade_links']['frames'];artwork=reviews['artwork_scale_controls']
    levels={v['view_id']:v for v in reviews['elevation_level_context']['views']}
    prior_preview=_load(preview/'facade-preview.json');targets={(r['pair_id'],tuple(r['key'])):r for r in prior_preview['target_marker_checks']}
    try:
        if len(previous['profiles'])>8:raise OverflowError('gable_long_profile_budget')
        for group in previous['profiles']:
            charge();height_rows=panel_heights(group,charge);result['long_profile_reviews'].append({'source_profile_id':group['id'],'source_view_id':group['view_id'],'heights':height_rows})
            for record in records:
                if record['target_elevation_view_ids']!=[group['view_id']]:continue
                for frame in record['frame_review']['frames']:
                    for pair in artwork['pairs']:
                        check=targets.get((pair['id'],tuple(record['target_view_key_candidate'])))
                        if not check or check['status']!='fixed_non_target_layout_agrees_at_target_annotation':continue
                        axis=np.asarray(frame['diagnostic_axis'])@np.asarray(pair['subject_to_reference_linear_row_matrix']);axis/=np.linalg.norm(axis)
                        for inv in inventories.values():
                            if inv['printed_claim'].get('plan_level_or_form')!='roof' or [inv['document_sha256'],inv['page']]!=pair['reference_page_key']:continue
                            for h in height_rows:
                                if h['status']!='source_long_roof_panel_height_hypothesis':continue
                                plan=plan_triples(inv,axis,h['nominal_length_m'],charge)
                                plan.update(source_height_review_id=h['id'],source_long_frame_id=frame['id'],fixed_artwork_pair_id=pair['id'])
                                plan['id']=digest([VERSION,plan]);result['plan_reviews'].append(plan)
                                for triple in plan['triples']:
                                    mesh=roof_mesh(h['nominal_length_m'],triple['nominal_left_run_m'],triple['nominal_right_run_m'],h['nominal_eave_height_m'],h['nominal_ridge_height_m'])
                                    model={'source_profile_id':group['id'],'source_height_review_id':h['id'],'source_plan_review_id':plan['id'],
                                        'source_plan_triple_id':triple['id'],'source_long_view_id':group['view_id'],
                                        'source_long_frame_id':frame['id'],'source_long_frame_axis_pdf_native':frame['diagnostic_axis'],
                                        'fixed_artwork_pair_id':pair['id'],'source_project_sheet_key':record['target_view_key_candidate'][:2],
                                        'source_nominal_depth_m':triple['nominal_depth_m'],'mesh':mesh,
                                        'source_construction_state':group['printed_state'],'independent_gable_checks_passed':False}
                                    model['id']=digest([VERSION,model]);result['models'].append(model)
                                    if len(result['models'])>128:raise OverflowError('gable_roof_model_budget')
        selected=sorted({key for key,inv in inventories.items() if inv['printed_claim']['view_kind']=='elevation'
            and key in levels and levels[key]['relative_reference']['status']=='unverified_source_relative_shop_level'})
        if len(selected)>16:raise OverflowError('gable_source_view_budget')
        for key in selected:
            charge();inv=inventories[key];source,view=source_views[key]
            receipt=_load(views/view['render']['receipt'])
            if inv['raster_coordinate_receipt']['quarter_turns_counterclockwise']!=0:raise ValueError('Aligned original gable crop required')
            with Image.open(views/view['render']['png']) as image:
                if image.width*image.height>6000000 or max(image.size)>3000:raise OverflowError('gable_source_raster_budget')
                if list(image.size)!=receipt['size_pixels'] or file_hash(views/view['render']['png'])!=inv['source_png_sha256']:raise ValueError('Matching original gable raster required')
                gray=np.asarray(image.convert('L')).copy()
            with pymupdf.open(corpus/'files'/(source['document_sha256']+'.pdf')) as doc:
                excluded,exclusions=exclusion_mask(inv,doc[source['page']-1],inv['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix'],receipt['size_pixels'],charge)
            matrix=levels[key]['pixel_edge_to_source_display_matrix'];unit=inv['nominal_metres_per_pdf_point']
            if len(matrix)!=6 or not np.isfinite([*matrix,unit]).all() or unit<=0 or matrix[0]<=0 or matrix[3]<=0 or matrix[1:3]!=[0.,0.] or abs(matrix[0]-matrix[3])>1e-6:raise ValueError('Uniform aligned original gable display transform required')
            mpp=matrix[0]*unit
            level=(levels[key]['relative_reference']['datum_y_display_points']-matrix[5])/matrix[3]
            row={'view_id':key,'caption':inv['caption'],'document_sha256':source['document_sha256'],'page':source['page'],
                'source_png_sha256':view['render']['png_sha256'],'source_exclusions':exclusions,'nominal_metres_per_pixel':mpp,
                'printed_level_pixel':level,'variants':[]}
            for threshold in (220,235):
                scan=slope_lines(gray,excluded,threshold,charge);scan['gable_pairs']=gable_pairs(scan['lines'],mpp,level,charge);row['variants'].append(scan)
                for pair in scan['gable_pairs']:
                    for model in result['models']:
                        charge();mesh=model['mesh'];ridge=mesh['vertices'][2][2]
                        errors=[abs(pair['left_pitch_degrees']-mesh['left_pitch_degrees']),abs(pair['right_pitch_degrees']-mesh['right_pitch_degrees'])]
                        passed=abs(pair['nominal_ridge_height_m']-ridge)<=.25 and max(errors)<=1.
                        frames=[f['id'] for r in records if r['target_elevation_view_ids']==[key] and r['target_view_key_candidate'][:2]==model['source_project_sheet_key']
                            for f in r['frame_review']['frames'] if abs(float(np.dot(f['diagnostic_axis'],model['source_long_frame_axis_pdf_native'])))<=math.sin(math.radians(5))]
                        target_rows=[targets.get((model['fixed_artwork_pair_id'],tuple(r['target_view_key_candidate']))) for r in records if r['target_elevation_view_ids']==[key]]
                        target_ok=any(c and c['status']=='fixed_non_target_layout_agrees_at_target_annotation' for c in target_rows)
                        result['gable_checks'].append({'model_id':model['id'],'view_id':key,'threshold':threshold,'source_gable_pair_id':pair['id'],
                            'ridge_difference_nominal_m':pair['nominal_ridge_height_m']-ridge,'pitch_differences_degrees':errors,
                            'status':'independent_source_gable_heights_and_pitches_agree' if passed else 'source_gable_measurements_disagree',
                            'source_perpendicular_frame_ids':frames,'target_annotation_check_passed':target_ok,
                            'source_gable_orientation_link_supported':bool(frames) and target_ok,
                            'model_refitted_to_gable':False,'source_gable_eave_depth_not_independently_measured':True,'physical_correspondence_verified':False})
            result['gable_views'].append(row)
        for model in result['models']:
            checks=[c for c in result['gable_checks'] if c['model_id']==model['id'] and c['status']=='independent_source_gable_heights_and_pitches_agree']
            model['independent_gable_checks_passed']=all(any(c['threshold']==t and c['source_gable_orientation_link_supported'] for c in checks) for t in (220,235))
            model['supporting_gable_view_ids']=sorted({c['view_id'] for c in checks})
    except OverflowError as error:
        result.update(status='gable_roof_budget_withheld',reason=str(error),long_profile_reviews=[],plan_reviews=[],gable_views=[],models=[],gable_checks=[])
    automatic_facade_preview._verified_inputs(components,views,corpus)
    if file_hash(profile/'facade-profile.json')!=contract['source_profile_sha256'] or file_hash(preview/'facade-preview.json')!=contract['source_preview_sha256'] or file_hash(components/'component-report.json')!=contract['component_report_sha256'] or file_hash(views/'view-report.json')!=contract['view_report_sha256']:
        raise ValueError('Gable roof source contract changed during build')
    for group in previous['profiles']:
        for variant in group['variants']:
            for name in ('roof','wall'):
                receipt=variant.get(name+'_mask_receipt')
                if receipt and file_hash(profile/receipt['file'])!=receipt['png_sha256']:raise ValueError('Source profile mask changed during gable build')
    for receipt in prior_preview['source_crop_receipts']:
        if file_hash(preview/receipt['file'])!=receipt['png_sha256']:raise ValueError('Original preview crop changed during gable build')
    result['counts']={'long_height_witnesses':sum(len(p['heights']) for p in result['long_profile_reviews']),
        'source_plan_reviews':len(result['plan_reviews']),'native_parallel_triples':sum(len(p['triples']) for p in result['plan_reviews']),
        'source_gable_views':len(result['gable_views']),'source_slope_lines':sum(len(v['lines']) for p in result['gable_views'] for v in p['variants']),
        'source_gable_pairs':sum(len(v['gable_pairs']) for p in result['gable_views'] for v in p['variants']),
        'conditional_roof_models':len(result['models']),'distinct_roof_meshes':len({digest(m['mesh']) for m in result['models']}),
        'models_with_both_source_threshold_checks':sum(m['independent_gable_checks_passed'] for m in result['models']),
        'gable_checks':len(result['gable_checks']),'gable_checks_agree':sum(c['status']=='independent_source_gable_heights_and_pitches_agree' for c in result['gable_checks'])}
    if len(json.dumps(result).encode())>64000000:raise ValueError('Gable roof output budget exceeded')
    root=output/digest(contract)
    if root.exists():
        if digest(_load(root/'gable-roof-review.json'))!=digest(result):raise ValueError('Saved gable roof review changed')
    else:atomic_json(root/'gable-roof-review.json',result)
    return {**result,'directory':str(root)}
