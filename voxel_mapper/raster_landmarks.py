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
