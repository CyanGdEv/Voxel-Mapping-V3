"""Conservative straight crosshair and explicit leader candidates in PDF points."""
import math

from .drawing_vectors import extract_vectors


def extract_marks(page, *, reuse_allowed=False, max_segments=500):
    report={'status':'blocked_reuse','marks':[],'segments':[],'world_geometry_additions':0}
    if reuse_allowed is not True:
        return report
    left,bottom,right,top=map(float,page.cropbox)
    registration={'viewports':[{'viewport':0,'status':'internally_consistent_unverified',
        'viewport_bbox':[left,bottom,right,top],'control_hull':[[0,0],[1,0],[1,1],[0,1]],
        'normalised_to_metric':[[right-left,0],[0,top-bottom],[left,bottom]],'metric_crs':'PDF_points'}]}
    vectors=extract_vectors(page,registration,reuse_allowed=True,max_paths=max_segments)
    if vectors['status']!='unverified_candidates':
        return {**report,'status':'unsupported_or_unavailable','vector_status':vectors['status']}
    segments=[]
    for path in vectors['layers'][0]['paths']:
        coords=path['geometry']['coordinates']
        if path['paint_operator'] in ('S','s') and len(coords)==2 and not path['closed']:
            segments.append(coords)
    marks={}
    # Bounded pairwise search: retain centred orthogonal short strokes only.
    for i,a in enumerate(segments):
        ax,ay=a[1][0]-a[0][0],a[1][1]-a[0][1]
        al=math.hypot(ax,ay)
        if not 2<=al<=20:
            continue
        ac=[(a[0][k]+a[1][k])/2 for k in (0,1)]
        for j in range(i+1,len(segments)):
            b=segments[j]
            bx,by=b[1][0]-b[0][0],b[1][1]-b[0][1]
            bl=math.hypot(bx,by)
            bc=[(b[0][k]+b[1][k])/2 for k in (0,1)]
            if 2<=bl<=20 and abs(ax*bx+ay*by)/(al*bl)<1e-6 and math.dist(ac,bc)<1e-6:
                key=tuple(round(v,6) for v in ac)
                marks.setdefault(key,{'page_point':ac,'stroke_indices':set()})['stroke_indices'].update((i,j))
    return {**report,'status':'crosshair_candidates','segments':segments,
            'marks':[{'page_point':m['page_point'],'stroke_indices':sorted(m['stroke_indices'])} for m in marks.values()],
            'limitations':['Short centred orthogonal strokes can be symbols other than survey marks',
                           'Curves, clipping, forms, layers and complex rendering are unsupported',
                           'No grid-line interpretation or independent survey verification']}


def mark_for_label(report, origin, tolerance_points=1):
    """Unique explicit straight leader from label origin to crosshair centre.

    Do not snap a nearby mark. One-point PDF attachment tolerance is heuristic.
    """
    matches=[]
    for index,mark in enumerate(report.get('marks',[])):
        for segment_index,segment in enumerate(report['segments']):
            if segment_index in mark['stroke_indices']:
                continue
            for start,end in (segment,segment[::-1]):
                if math.dist(start,origin)<=tolerance_points and math.dist(end,mark['page_point'])<=1e-6:
                    matches.append(index)
    unique=set(matches)
    return report['marks'][unique.pop()]['page_point'] if len(unique)==1 else None
