"""Recover a native metre world grid against terrain, without editing the world."""
import numpy as np


def orientation_scores(world, reference, valid, *, step=8):
    """Bounded normalized correlation; all eight axis orientations are compared.

    Returns the reference pixel offset of the supplied world window. These are
    grid matches, not independent survey controls or a material classifier.
    """
    from scipy.signal import fftconvolve
    if world.ndim != 2 or reference.ndim != 2 or valid.shape != world.shape:
        raise ValueError("Matching two-dimensional grids and mask required")
    if type(step) is not int or step < 1 or max(world.size, reference.size) > 16_000_000:
        raise ValueError("Invalid registration sampling or pixel budget")
    a, mask = world[::step, ::step], valid[::step, ::step]
    ref = reference[::step, ::step].astype(float)
    finite = np.isfinite(ref)
    f = np.where(finite, ref, 0)
    results = []
    for name, transform in (("identity", lambda x:x), ("flip_x", lambda x:x[:,::-1]),
                            ("flip_z", lambda x:x[::-1]), ("rotate180", lambda x:x[::-1,::-1]),
                            ("transpose", lambda x:x.T), ("transpose_flip_x", lambda x:x.T[:,::-1]),
                            ("transpose_flip_z", lambda x:x.T[::-1]), ("transpose_flip_both", lambda x:x.T[::-1,::-1])):
        t, m = transform(a), transform(mask)
        m = m & np.isfinite(t)
        if any(s > r for s, r in zip(t.shape, ref.shape)) or m.sum() < 64:
            continue
        n = int(m.sum())
        centered = np.where(m, t-np.mean(t[m]), 0)
        variance = np.sum(centered**2)
        if variance <= 0:
            raise ValueError("World window has no terrain variation")
        kernel = m[::-1,::-1].astype(float)
        sums = fftconvolve(f, kernel, mode="valid")
        squares = fftconvolve(f*f, kernel, mode="valid")
        covariance = fftconvolve(f, centered[::-1,::-1], mode="valid")
        count = fftconvolve(finite.astype(float), kernel, mode="valid")
        denominator = np.sqrt(np.maximum(0, squares-sums*sums/n)*variance)
        score = np.divide(covariance, denominator, out=np.full(covariance.shape, -np.inf),
                          where=(denominator > 0) & (count > n-.1))
        if not np.isfinite(score).any():
            continue
        y, x = np.unravel_index(np.argmax(score), score.shape)
        results.append({"orientation":name, "correlation":float(score[y,x]),
                        "reference_pixel_offset":[int(x*step),int(y*step)], "sampled_points":n})
    if not results:
        raise ValueError("No complete, varying terrain overlap")
    return sorted(results, key=lambda r:r["correlation"], reverse=True)


def refine_translation(world, reference, valid, initial, fit_bounds, validation_bounds, *, radius=12, step=4):
    """Fit translation/height offset on one area; report separate held-out areas.

    Bounds are half-open [x0,z0,x1,z1]. Every candidate must cover all selected
    world cells. Median residuals tolerate roofs/trees above the terrain.
    """
    if world.ndim != 2 or reference.ndim != 2 or valid.shape != world.shape:
        raise ValueError("Matching two-dimensional grids and mask required")
    if max(world.size, reference.size) > 16_000_000:
        raise ValueError("Registration pixel budget exceeded")
    if not 0 <= radius <= 32 or step < 1:
        raise ValueError("Registration search budget exceeded")
    def samples(bounds, stride):
        x0,y0,x1,y1 = bounds
        if not (0 <= x0 < x1 <= world.shape[1] and 0 <= y0 < y1 <= world.shape[0]):
            raise ValueError("Area outside world grid")
        yy,xx = np.mgrid[y0:y1:stride,x0:x1:stride]
        mask = valid[yy,xx] & np.isfinite(world[yy,xx])
        if mask.sum() < 64:
            raise ValueError("Insufficient valid terrain points")
        return yy[mask],xx[mask],world[yy[mask],xx[mask]]
    for bounds in validation_bounds:
        if min(bounds[2],fit_bounds[2]) > max(bounds[0],fit_bounds[0]) and min(bounds[3],fit_bounds[3]) > max(bounds[1],fit_bounds[1]):
            raise ValueError("Validation must not overlap fitted area")
    yy,xx,values = samples(fit_bounds,step)
    fit_points = len(values)
    ranked = []
    for row in range(initial[1]-radius,initial[1]+radius+1):
        for col in range(initial[0]-radius,initial[0]+radius+1):
            if row+yy.min() < 0 or col+xx.min() < 0 or row+yy.max() >= reference.shape[0] or col+xx.max() >= reference.shape[1]:
                continue
            delta = reference[row+yy,col+xx]-values
            if not np.isfinite(delta).all():
                continue
            offset = float(np.median(delta))
            ranked.append({"median_absolute_residual_m":float(np.median(np.abs(delta-offset))),
                           "reference_minus_heightmap_m":offset, "reference_pixel_offset":[col,row]})
    if not ranked:
        raise ValueError("No complete terrain overlap in search region")
    ranked.sort(key=lambda r:r["median_absolute_residual_m"])
    best = ranked[0]
    col,row = best["reference_pixel_offset"]
    offset = best["reference_minus_heightmap_m"]
    regions = []
    for bounds in validation_bounds:
        yy,xx,values = samples(bounds,max(1,step//2))
        if row+yy.min() < 0 or col+xx.min() < 0 or row+yy.max() >= reference.shape[0] or col+xx.max() >= reference.shape[1]:
            raise ValueError("Validation outside reference raster")
        delta = reference[row+yy,col+xx]-values
        if not np.isfinite(delta).all():
            raise ValueError("Missing validation terrain")
        regions.append({"world_bounds":list(bounds), "points":len(delta),
                        "median_offset_m":float(np.median(delta)),
                        "median_absolute_residual_m":float(np.median(np.abs(delta-offset))),
                        "fraction_within_1m":float(np.mean(np.abs(delta-offset) < 1))})
    return {"best":best, "nearby_candidates":ranked[:10], "fit_bounds":list(fit_bounds),
            "fit_points":fit_points,
            "validation":regions, "world_blocks_changed":0,
            "policy":"Relative source-grid recovery only. A shared terrain lineage is not independent survey validation. No automatic world placement."}
