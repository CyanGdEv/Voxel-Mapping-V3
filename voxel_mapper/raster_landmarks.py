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
