"""Exact raster-cell wall/roof projection hypotheses downstream of source previews."""
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, __version__ as PIL_VERSION
import rasterio
from rasterio.features import shapes
import scipy
from scipy import ndimage
import shapely
from shapely.geometry import shape

from . import automatic_facade_preview, automatic_opening_links, generation_cycles, reconstruction_evidence_queue
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-raster-facade-profile-v1'


def runs(mask):
    """Half-open runs of original selected cells, with no bridging or simplification."""
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype('int8')))
    return [(int(a), int(b)) for a,b in zip(edges[::2],edges[1::2])]


def rectangles(mask, charge):
    """Losslessly coalesce identical source row runs; preserve every hole and step."""
    active = {}; result = []
    for y,row in enumerate(mask):
        charge(); current = set(runs(row))
        for interval in sorted(set(active)-current):
            result.append([interval[0],active.pop(interval),interval[1],y])
        for interval in sorted(current-set(active)):active[interval] = y
        if len(result)>8192:raise OverflowError('facade_profile_rectangle_budget')
    for interval,start in sorted(active.items()):result.append([interval[0],start,interval[1],mask.shape[0]])
    if len(result)>8192:raise OverflowError('facade_profile_rectangle_budget')
    return result


def surface(mask, parent, metres_per_pixel, level_pixel, charge):
    if (mask.dtype != bool or mask.ndim != 2 or mask.size>6000000 or
            not math.isfinite(metres_per_pixel) or metres_per_pixel<=0 or not math.isfinite(level_pixel)):
        raise ValueError('Finite bounded source profile mask and scale required')
    rects=rectangles(mask,charge);vertices=[];triangles=[]
    for x0,y0,x1,y1 in rects:
        charge();offset=len(vertices)
        vertices.extend([[(x-parent[0])*metres_per_pixel,0.,(level_pixel-y)*metres_per_pixel]
                         for x,y in [(x0,y1),(x1,y1),(x1,y0),(x0,y0)]])
        triangles.extend([[offset,offset+1,offset+2],[offset,offset+2,offset+3]])
    polygons=[]
    for geometry,value in shapes(mask.astype('uint8'),mask=mask,connectivity=4):
        charge()
        if value:polygons.append(geometry)
        if len(polygons)>256:raise OverflowError('facade_profile_polygon_budget')
    return {'source_rectangles_pixels':rects,'source_polygons_pixels':polygons,
        'vertices_nominal_local_m':vertices,'triangles':triangles,'source_cell_count':int(mask.sum()),
        'projected_area_nominal_m2':float(mask.sum()*metres_per_pixel**2),
        'source_grid_mask_sha256':hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest(),
        'source_hole_count':sum(len(p['coordinates'])-1 for p in polygons),
        'source_gap_repair_applied':False,'physical_surface_verified':False,
        'holes_are_verified_apertures':False,'wall_thickness_m':None,'roof_pitch_degrees':None}


def profiles(gray, parent, charge):
    """Broad closed roof projection plus a source shaded-band interface, in two variants.

    This recipe deliberately withholds a pitched/fragmented upper projection.
    It does not assign a ground contact as a physical wall base or floor.
    """
    if gray.dtype!=np.uint8 or gray.ndim!=2 or gray.size>6000000 or max(gray.shape)>3000:
        raise ValueError('Bounded uint8 original elevation required')
    if (len(parent)!=4 or any(type(v) is not int for v in parent) or
            not 0<=parent[0]<parent[2]<=gray.shape[1] or not 0<=parent[1]<parent[3]<=gray.shape[0]):
        raise ValueError('Whole integer original parent bounds required')
    x0,y0,x1,y1=parent;result=[]
    if y0<24 or y1-y0<24:return [{'status':'sufficient_source_profile_height_required','threshold':t} for t in (220,235)]
    for threshold in (220,235):
        dark=gray<threshold;labels,count=ndimage.label(~dark)  # Four-connected original white cells.
        if count>8192:raise OverflowError('facade_profile_source_region_budget')
        border=np.unique(np.r_[labels[0,:],labels[-1,:],labels[:,0],labels[:,-1]])
        closed=(labels>0)&~np.isin(labels,border);solid=closed|dark
        full_rows=np.flatnonzero(solid[:y0,x0:x1].all(axis=1));row_spans=[]
        for y in full_rows:
            charge();left=x0;right=x1
            while left>0 and solid[y,left-1]:left-=1
            while right<gray.shape[1] and solid[y,right]:right+=1
            row_spans.append({'row':int(y),'span':[left,right]})
        review={'threshold':threshold,'status':'broad_closed_upper_projection_required',
            'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),
            'parent_bounds_pixels':parent,'full_width_source_rows':row_spans,
            'roof_source_regions':[],'deferred_upper_source_regions':[],'ground_columns':[]}
        if not row_spans:result.append(review);continue
        first=row_spans[0]['row'];height=y0-first
        if height<24 or len(row_spans)<.95*height:
            review['status']='continuous_broad_upper_projection_required';result.append(review);continue
        frequencies=Counter(tuple(r['span']) for r in row_spans);maximum=max(frequencies.values())
        modes=sorted(span for span,n in frequencies.items() if n==maximum)
        if len(modes)!=1 or maximum<.5*len(row_spans):
            review['status']='unique_repeated_original_upper_span_required';result.append(review);continue
        left,right=modes[0]
        review.update(source_upper_span_pixels=[left,right],source_upper_span_support_rows=maximum,
                      first_full_width_row=first)
        if left==0 or right==gray.shape[1] or not x1-x0<=right-left<=1.5*(x1-x0):
            review['status']='whole_bounded_upper_projection_required';result.append(review);continue
        areas=np.bincount(labels.ravel());objects=ndimage.find_objects(labels);ids=[];borders=set(border.tolist())
        for identity,box in enumerate(objects,1):
            charge()
            if box is None or identity in borders or box[0].stop>y0 or box[0].stop<first:continue
            bounds=[box[1].start,box[0].start,box[1].stop,box[0].stop]
            if bounds[2]<=left or bounds[0]>=right:continue
            record={'label':identity,'bounds_pixels':bounds,'source_cell_count':int(areas[identity]),
                'source_membership_sha256':hashlib.sha256(np.packbits(labels[box]==identity).tobytes()).hexdigest()}
            if bounds[0]>=left and bounds[2]<=right:
                ids.append(identity);review['roof_source_regions'].append(record)
            else:review['deferred_upper_source_regions'].append({**record,'reason':'whole_original_region_crosses_main_projection_span'})
        if not ids:
            review['status']='whole_closed_upper_source_regions_required';result.append(review);continue
        selected=np.isin(labels,ids)
        # Only original dark cells adjoining selected closed white regions are added.
        # No outside white pixel, smoothing, inferred edge or line extension is used.
        roof=selected|(ndimage.binary_dilation(selected)&dark)
        wall=np.zeros_like(roof)
        for x in range(x0,x1):
            charge();top=y1
            while top>y0 and 128<=int(gray[top-1,x])<=224:top-=1
            supported=y1-top>=16
            review['ground_columns'].append({'column':x,'shade_row_interval':[top,y1],
                'supported':supported,'contact_role_verified':False})
            if supported:wall[y0:top,x]=solid[y0:top,x]
        review.update(status='source_profile_masks_only',roof_mask=roof,wall_mask=wall,
            full_ground_column_support=all(c['supported'] for c in review['ground_columns']),
            source_roof_wall_overlap_cells=int(np.count_nonzero(roof&wall)),
            source_roof_wall_overlap_repaired=False,physical_wall_base_verified=False)
        result.append(review)
    return result


def _load(path):
    path=Path(path)
    if path.stat().st_size>64000000:raise ValueError('Bounded facade profile input required')
    return json.loads(path.read_text())


def build(preview,components,views,corpus,output,*,max_checks=100000):
    bounded_work(max_checks)
    preview,components,views,corpus,output=map(Path,(preview,components,views,corpus,output))
    preview_path=preview/'facade-preview.json';prior=_load(preview_path)
    if prior['version']!=automatic_facade_preview.VERSION:raise ValueError('Current automatic facade preview required')
    # Reproduce the complete source preview before using any parent/opening witness.
    with tempfile.TemporaryDirectory() as temp:
        replay=automatic_facade_preview.build(components,views,corpus,temp,max_checks=prior['contract']['max_checks'])
        replay.pop('directory')
        if digest(prior)!=digest(replay):raise ValueError('Original facade preview replay changed')
    for receipt in prior['source_crop_receipts']:
        path=(preview/receipt['file']).resolve()
        if not path.is_relative_to(preview.resolve()) or file_hash(path)!=receipt['png_sha256']:
            raise ValueError('Original facade preview crop changed')
    report,vr,inventories,source_views,reviews=automatic_facade_preview._verified_inputs(components,views,corpus)
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),
        'source_preview_sha256':file_hash(preview_path),'component_report_sha256':file_hash(components/'component-report.json'),
        'view_report_sha256':file_hash(views/'view-report.json'),'max_checks':max_checks,
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (automatic_facade_preview,automatic_opening_links,
            generation_cycles,reconstruction_evidence_queue)},'numpy_version':np.__version__,'scipy_version':scipy.__version__,
        'rasterio_version':rasterio.__version__,'shapely_version':shapely.__version__,'pillow_version':PIL_VERSION}
    result={'version':VERSION,'contract':contract,'status':'unplaced_raster_profile_hypotheses_only',
        'profiles':[],'source_raster_receipts':[],'checks':0,
        'recipe':{'thresholds':[220,235],'connectivity':4,'minimum_upper_height_pixels':24,
            'minimum_full_width_row_fraction':.95,'minimum_unique_span_mode_fraction':.5,
            'maximum_upper_to_parent_width_ratio':1.5,'roof_cells':'whole closed original white regions; one adjoining original dark cell layer',
            'ground':'contiguous original midtone run [128,224] ending at raw parent bottom, minimum 16 rows; all columns retained',
            'mesh':'lossless coalesced original-cell row rectangles; zero-thickness elevation planes; no aperture carve',
            'source_grid_repair_allowed':False},
        'physical_scale_verified':False,'physical_wall_base_verified':False,'roof_pitch_degrees':None,
        'wall_thickness_m':None,'world_placement_eligible':False,'world_geometry_additions':0,
        'accepted_physical_components':0,'training_labels_generated':0,
        'unresolved':['Adjacent gable/wing association and other facade silhouettes',
            'Raster gaps and callout overlaps are not verified apertures',
            'Physical wall, roof, ground contact, floor and threshold roles',
            'Roof depth/pitch, wall thickness, source state, physical scale and park registration']}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('facade_profile_work_budget')
    images={};groups={};levels={v['view_id']:v for v in reviews['elevation_level_context']['views']}
    for p in prior['previews']:groups.setdefault((p['view_id'],tuple(p['source_parent_bounds_pixels'])),[]).append(p)
    try:
        if len(groups)>8:raise OverflowError('facade_profile_view_budget')
        for (view_id,bounds),alternatives in sorted(groups.items()):
            charge();inv=inventories[view_id];source,view=source_views[view_id]
            if inv['raster_coordinate_receipt']['quarter_turns_counterclockwise']!=0:
                raise ValueError('Unrotated original profile raster required')
            png=views/view['render']['png'];receipt=_load(views/view['render']['receipt'])
            if file_hash(png)!=receipt['png_sha256'] or receipt['png_sha256']!=inv['source_png_sha256']:
                raise ValueError('Matching original profile raster required')
            with Image.open(png) as image:
                if list(image.size)!=receipt['size_pixels'] or image.width*image.height>6000000 or max(image.size)>3000:
                    raise ValueError('Bounded original profile raster dimensions required')
                gray=np.asarray(image.convert('L')).copy()
            matrix=levels[view_id]['pixel_edge_to_source_display_matrix'];unit=inv['nominal_metres_per_pdf_point']
            if (len(matrix)!=6 or not all(math.isfinite(v) for v in [*matrix,unit]) or
                    matrix[0]<=0 or matrix[3]<=0 or matrix[1:3]!=[0.,0.] or abs(matrix[0]-matrix[3])>1e-6 or unit<=0):
                raise ValueError('Uniform original profile display scale required')
            mpp=matrix[0]*unit;datum=levels[view_id]['relative_reference']['datum_y_display_points']
            level_pixel=(datum-matrix[5])/matrix[3]
            result['source_raster_receipts'].append({'view_id':view_id,'png_sha256':file_hash(png),
                'render_receipt_sha256':file_hash(views/view['render']['receipt']),'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),
                'size_pixels':receipt['size_pixels'],'document_sha256':source['document_sha256'],'page':source['page']})
            variants=[];masks=[]
            for review in profiles(gray,list(bounds),charge):
                charge();roof=review.pop('roof_mask',None);wall=review.pop('wall_mask',None)
                if roof is not None:
                    for name,mask in [('roof',roof),('wall',wall)]:
                        review[name+'_surface']=surface(mask,list(bounds),mpp,level_pixel,charge)
                        path='masks/'+digest([view_id,bounds,review['threshold'],name])+'.png';stream=io.BytesIO()
                        Image.fromarray(mask.astype('uint8')*255).save(stream,format='PNG');data=stream.getvalue();images[path]=data
                        review[name+'_mask_receipt']={'file':path,'png_sha256':hashlib.sha256(data).hexdigest(),'size_pixels':receipt['size_pixels']}
                    masks.append((review['threshold'],roof,wall))
                variants.append(review)
            comparison=None
            if len(masks)==2:
                comparison={}
                for index,name in [(1,'roof'),(2,'wall')]:
                    a,b=masks[0][index],masks[1][index];union=np.count_nonzero(a|b)
                    comparison[name]={'shared_cells':int(np.count_nonzero(a&b)),'different_cells':int(np.count_nonzero(a^b)),
                        'intersection_over_union':float(np.count_nonzero(a&b)/union) if union else None,
                        'variants_merged':False}
            row={'id':digest([VERSION,view_id,bounds]),'view_id':view_id,'caption':inv['caption'],
                'source_parent_bounds_pixels':list(bounds),'source_alternative_ids':[p['id'] for p in alternatives],
                'source_opening_alternatives':[{k:p[k] for k in ('id','source_child_bounds_pixels','source_child_witness_sha256',
                    'source_crop_receipt_id','base_band_relative_to_printed_level_nominal_m','mesh')} for p in alternatives],
                'nominal_metres_per_source_pixel':mpp,'printed_level_pixel':level_pixel,
                'coordinate_frame':'nominal metres; x from original parent left, y=0 elevation plane, z relative to printed Shop Level',
                'printed_state':inv['printed_claim']['printed_state'],'variants':variants,'threshold_comparison':comparison,
                'physical_surface_roles_verified':False,'apertures_carved':0}
            result['profiles'].append(row)
    except OverflowError as error:
        result.update(status='facade_profile_budget_withheld',reason=str(error),profiles=[],source_raster_receipts=[]);images={}
    automatic_facade_preview._verified_inputs(components,views,corpus)
    if file_hash(preview_path)!=contract['source_preview_sha256'] or file_hash(components/'component-report.json')!=contract['component_report_sha256'] or file_hash(views/'view-report.json')!=contract['view_report_sha256']:
        raise ValueError('Facade profile source contract changed during build')
    for receipt in prior['source_crop_receipts']:
        if file_hash(preview/receipt['file'])!=receipt['png_sha256']:raise ValueError('Facade profile source crop changed during build')
    variants=[v for p in result['profiles'] for v in p['variants']]
    result['counts']={'source_profile_groups':len(result['profiles']),'threshold_variants':len(variants),
        'supported_profile_variants':sum(v['status']=='source_profile_masks_only' for v in variants),
        'source_opening_alternatives':sum(len(p['source_alternative_ids']) for p in result['profiles']),
        'source_masks':len(images),'mesh_triangles':sum(len(v[n+'_surface']['triangles']) for v in variants for n in ('roof','wall') if n+'_surface' in v)}
    if sum(len(v) for v in images.values())+len(json.dumps(result).encode())>64000000:raise ValueError('Facade profile output budget exceeded')
    root=output/digest(contract)
    if root.exists():
        if digest(_load(root/'facade-profile.json'))!=digest(result):raise ValueError('Saved facade profile changed')
        for name,data in images.items():
            if (root/name).read_bytes()!=data:raise ValueError('Saved source profile mask changed')
    else:
        root.mkdir(parents=True)
        for name,data in images.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        atomic_json(root/'facade-profile.json',result)
    return {**result,'directory':str(root)}
