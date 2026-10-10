"""Surface observations within comparison outlines; never surveyed attachment points."""
import numpy as np
from rasterio.features import geometry_mask
from shapely.geometry import mapping


def observations(geometry, terrain, surface, transform):
    if terrain.shape!=surface.shape or terrain.ndim!=2 or terrain.size>1000000:raise ValueError('Matched bounded raster windows required')
    inside=geometry_mask([mapping(geometry)],out_shape=terrain.shape,transform=transform,invert=True,all_touched=False)
    ground=np.ma.asarray(terrain);top=np.ma.asarray(surface)
    valid=inside & ~np.ma.getmaskarray(ground) & ~np.ma.getmaskarray(top) & np.isfinite(ground.data) & np.isfinite(top.data)
    n=int(inside.sum());count=int(valid.sum());delta=top.data[valid]-ground.data[valid]
    def stats(values):return {'min':float(values.min()),'median':float(np.median(values)),'max':float(values.max())} if len(values) else None
    return {'pixel_centres_in_outline':n,'valid_paired_pixels':count,'paired_coverage_fraction':count/n if n else None,'ground_odn_m':stats(ground.data[valid]),'observed_surface_odn_m':stats(top.data[valid]),'surface_above_ground_m':stats(delta),'pixels_surface_at_least_3m_above_ground':int((delta>=3).sum()),'checkpoint_attachment_verified':False,'physical_identity_verified':False,'world_geometry_additions':0}


def elevated_regions(terrain,surface,transform,*,threshold_m=3.,min_area_m2=8.,max_regions=1000):
    """Exact pixel-region candidates, without footprint fitting or gap filling."""
    import math
    from rasterio.features import shapes
    from shapely.geometry import shape,mapping
    if terrain.shape!=surface.shape or terrain.ndim!=2 or terrain.size>1000000:raise ValueError('Matched bounded raster windows required')
    if not math.isfinite(threshold_m) or threshold_m<=0 or not math.isfinite(min_area_m2) or min_area_m2<=0 or type(max_regions) is not int or not 1<=max_regions<=1000:raise ValueError('Bounded surface-region options required')
    # A rotated metre grid is supported; area comes from its affine determinant.
    area=abs(transform.a*transform.e-transform.b*transform.d)
    if not math.isfinite(area) or area<=0:raise ValueError('Finite nondegenerate raster grid required')
    ground=np.ma.asarray(terrain);top=np.ma.asarray(surface)
    valid=~np.ma.getmaskarray(ground)&~np.ma.getmaskarray(top)&np.isfinite(ground.data)&np.isfinite(top.data)
    mask=valid & ((top.data-ground.data)>=threshold_m);regions=[]
    for geometry,value in shapes(mask.astype('uint8'),mask=mask,transform=transform,connectivity=4):
        g=shape(geometry)
        if g.area<min_area_m2:continue
        if len(regions)>=max_regions:raise ValueError('Surface-region budget exceeded; reduce crop')
        regions.append({'geometry':mapping(g),'area_m2':g.area,'status':'unclassified_elevated_pixel_region','physical_identity_verified':False,'checkpoint_attachment_verified':False,'registration_verified':False})
    return {'threshold_m':threshold_m,'minimum_region_area_m2':min_area_m2,'valid_paired_pixels':int(valid.sum()),'elevated_pixels':int(mask.sum()),'regions':regions,'world_geometry_additions':0,'limitations':['Elevated surfaces may be roofs, trees, supports or other objects','Pixel-region corners are not verified physical building corners','No snapping, interpolation or reference-footprint fitting']}


def attachment_stability(terrain,surface,transform,references,*,thresholds=(1.5,2.,2.5,3.,3.5,4.)):
    """Review candidates and threshold sensitivity; never accept attachment points."""
    import math
    from shapely.geometry import shape,mapping
    if not isinstance(thresholds,(list,tuple)) or not 2<=len(thresholds)<=8 or len(set(thresholds))!=len(thresholds) or any(not isinstance(v,(float,int)) or not math.isfinite(v) or v<=0 for v in thresholds):raise ValueError('Two to eight distinct positive thresholds required')
    if not isinstance(references,list) or not 1<=len(references)<=32 or len({r['id'] for r in references})!=len(references):raise ValueError('Bounded unique comparison references required')
    result={r['id']:[] for r in references}
    for threshold in sorted(thresholds):
        regions=elevated_regions(terrain,surface,transform,threshold_m=threshold)
        for reference in references:
            candidates=[];g=reference['geometry']
            if g.is_empty or not g.is_valid or g.geom_type!='Polygon':raise ValueError('Valid polygon comparison reference required')
            for region in regions['regions']:
                h=shape(region['geometry']);intersection=g.intersection(h).area
                if intersection>0:candidates.append((intersection/g.union(h).area,h))
            if not candidates:result[reference['id']].append({'threshold_m':threshold,'status':'no_overlapping_region'});continue
            iou,h=max(candidates,key=lambda pair:pair[0])
            result[reference['id']].append({'threshold_m':threshold,'status':'unreviewed_region_comparison','intersection_over_union':iou,'centroid_distance_m':g.centroid.distance(h.centroid),'region_area_m2':h.area,'region_geometry':mapping(h),'rectangle_corner_estimates':list(map(list,h.minimum_rotated_rectangle.exterior.coords))[:-1],'rectangle_corners_are_physical_points':False})
    rows=[]
    for reference in references:
        comparisons=result[reference['id']];geometries=[shape(c['region_geometry']) for c in comparisons if 'region_geometry' in c]
        spread=max((a.boundary.hausdorff_distance(b.boundary) for i,a in enumerate(geometries) for b in geometries[i+1:]),default=None)
        rows.append({'reference_id':reference['id'],'name':reference.get('name',''),'comparisons':comparisons,'maximum_threshold_boundary_spread_m':spread,'native_attachment_uncertainty_m':None,'roof_to_wall_offset_m':None,'status':'withheld_attachment_identification','accepted_control_points':0,'accepted_checkpoint_points':0,'reasons':['Physical corner correspondence unreviewed','Threshold boundaries are elevated pixel regions, not verified walls','Native edge accuracy and roof-to-wall offsets not established'],'physical_identity_verified':False,'registration_verified':False})
    return {'landmarks':rows,'pixel_half_diagonal_m':max(math.hypot(transform.a+transform.b,transform.d+transform.e),math.hypot(transform.a-transform.b,transform.d-transform.e))/2,'accepted_control_points':0,'accepted_checkpoint_points':0,'world_geometry_additions':0,'status':'attachment_review_queue_only'}
