"""Paper-scoped scale and edge diagnostics, never independent checkpoints."""
import math,re
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Point,Polygon,mapping
from .boundary_registration import samples,similarity

PAPER_MM={'A0':(841,1189),'A1':(594,841),'A2':(420,594),
          'A3':(297,420),'A4':(210,297),'A5':(148,210),'A6':(105,148)}


def page_scale(text,width_points,height_points):
    """Use explicit paper-labelled scales; gradients and alternate sheets differ."""
    if not isinstance(text,str) or len(text)>1_000_000 or not np.isfinite([width_points,height_points]).all() or min(width_points,height_points)<=0:
        raise ValueError('Bounded text and finite native page dimensions required')
    dims=sorted([width_points*.0254/72*1000,height_points*.0254/72*1000])
    found=[]
    for m in re.finditer(r'\b1\s*[/ :]\s*(\d{1,6})\s*@\s*(A[0-6])\b',text,re.I):
        denominator=int(m[1]);paper=m[2].upper()
        if not 1<=denominator<=100000:continue
        found.append({'text':m[0],'text_range':[m.start(),m.end()],
            'denominator':denominator,'paper':paper,
            'native_page_size_matches':all(abs(a-b)<=2 for a,b in zip(dims,PAPER_MM[paper]))})
    selected=sorted({r['denominator'] for r in found if r['native_page_size_matches']})
    return {'status':'single_native_page_scale' if len(selected)==1 else 'withheld',
        'page_dimensions_mm':dims,'explicit_paper_scales':found,
        'denominator':selected[0] if len(selected)==1 else None,
        'size_tolerance_mm':2,'physical_geometry_verified':False}


def fixed_scale_edges(local,target,denominator):
    """Retain orientation ambiguity and measure edge residuals at printed scale.

    Residuals reuse the fitted boundary: they are not an independent check or
    measured eave offsets. Positive signed distances mean inside the envelope.
    """
    if type(denominator)!=int or not 1<=denominator<=100000:raise ValueError('Valid printed denominator required')
    for p in (local,target):
        if not isinstance(p,Polygon) or not p.is_valid or p.is_empty or p.interiors or p.area<=0 or len(p.exterior.coords)>256 or not np.isfinite(p.bounds).all():
            raise ValueError('Valid bounded finite single exterior polygons required')
    scale=denominator*.0254/72;a=samples(local,64);b=samples(target,64);fits=[]
    for shift in range(64):
        rolled=np.roll(b,shift,axis=0);matrix,_,free_scale,_=similarity(a,rolled)
        matrix=np.asarray(matrix)*(scale/free_scale);translation=rolled.mean(axis=0)-a.mean(axis=0)@matrix.T
        placed=affine_transform(local,[*matrix[0],*matrix[1],*translation])
        rms=float(np.sqrt(np.mean(np.sum((a@matrix.T+translation-rolled)**2,axis=1))))
        fits.append({'matrix':matrix.tolist(),'translation_m':translation.tolist(),
            'rotation_degrees':math.degrees(math.atan2(matrix[1,0],matrix[0,0])),
            'scale_metres_per_pdf_point':scale,'sample_rms_m':rms,
            'intersection_over_union':placed.intersection(target).area/placed.union(target).area,
            'boundary_hausdorff_m':placed.boundary.hausdorff_distance(target.boundary),
            'placed_geometry':mapping(placed)})
    fits.sort(key=lambda f:(-f['intersection_over_union'],f['boundary_hausdorff_m']))
    best=fits[0];equivalent=[f for f in fits if f['intersection_over_union']>=best['intersection_over_union']-.005 and f['boundary_hausdorff_m']<=best['boundary_hausdorff_m']+.005*math.sqrt(target.area)]
    # Preserve all equivalent transforms; an edge number is local to each hypothesis.
    for f in equivalent:
        matrix=np.asarray(f['matrix']);translation=np.asarray(f['translation_m'])
        coords=np.asarray(local.exterior.coords);edges=[]
        for i,(start,end) in enumerate(zip(coords[:-1],coords[1:])):
            pts=start+(end-start)*np.linspace(0,1,33)[:,None];placed=pts@matrix.T+translation
            distances=np.asarray([Point(q).distance(target.boundary) for q in placed])
            signs=np.asarray([1 if target.covers(Point(q)) else -1 for q in placed]);signed=distances*signs
            edges.append({'source_edge_index':i,'source_endpoints_pdf_points':[start.tolist(),end.tolist()],
                'hypothesis_endpoints_bng_m':[placed[0].tolist(),placed[-1].tolist()],
                'length_at_printed_scale_m':float(np.linalg.norm(end-start)*scale),
                'sample_count':33,'distance_to_envelope_m':{'median':float(np.median(distances)),'p95':float(np.quantile(distances,.95)),'max':float(distances.max())},
                'signed_distance_m':{'min':float(signed.min()),'median':float(np.median(signed)),'max':float(signed.max())},
                'physical_edge_correspondence_verified':False})
        f['edge_diagnostics']=edges
    flags=['independent_physical_checkpoints_missing','roof_to_wall_offset_unmeasured']
    if len(equivalent)>1:flags.append('ambiguous_boundary_orientation')
    if best['intersection_over_union']<.85 or best['boundary_hausdorff_m']/math.sqrt(target.area)>.05:flags.append('poor_boundary_agreement')
    return {'status':'fixed_scale_boundary_hypotheses_only','best_fit':best,
        'equivalent_orientations':equivalent,'review_flags':flags,
        'physical_identity_verified':False,'registration_verified':False,
        'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
        'limitations':['Edge residuals are boundary self-fit diagnostics, not independent accuracy checks',
            'Signed distances are not verified roof-to-wall offsets',
            'Endpoint coordinates are hypothesis locations, not surveyed attachment points']}
