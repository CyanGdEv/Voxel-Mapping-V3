"""Bounded native-text anchor associations, never verified world features."""
import math
import re

from shapely.geometry import Point, shape

from .drawing_evidence import evidence_candidates
from .geopdf import page_point_to_metric

FEATURES = {'plaza':r'\bplaza\b', 'path':r'\b(?:path|pathway|walkway|footpath)\b',
            'ride_structure':r'\bride structure\b',
            'building_component':r'\b(?:dome|building component)\b'}


def associate_labels(polygons, labels, max_labels=1000):
    """Require a unique strict interior match in the same viewport and CRS.

    A text origin is not its bounding box or a leader-line target. Matches remain
    hypotheses; overlapping polygons, holes and boundary anchors are withheld.
    """
    result={'status':'unverified_associations','associations':[], 'unmatched_labels':0,
            'ambiguous_labels':0,'world_geometry_additions':0}
    if polygons.get('status')!='unplaced_candidates':
        return {**result,'status':'unavailable'}
    if len(labels)>max_labels:
        return {**result,'status':'budget_rejected'}
    for label in labels:
        point=Point(label['metric_anchor'])
        matches=[]
        for layer in polygons['layers']:
            if (layer['viewport'],layer['metric_crs'])!=(label['viewport'],label['metric_crs']):
                continue
            for polygon in layer['polygons']:
                if shape(polygon['geometry']).contains(point):
                    matches.append(polygon)
        if len(matches)!=1:
            result['ambiguous_labels' if matches else 'unmatched_labels']+=1
            continue
        result['associations'].append({**label,'paint_group':matches[0]['paint_group'],
            'association_status':'text_origin_inside_polygon_unverified',
            'construction_status':'not_verified'})
    return result


def extract_associations(page, registration, polygons, *, reuse_allowed=False,
                         max_fragments=2000, max_text=500_000):
    """Extract native PDF text origins; no OCR or nearest-feature guesses."""
    base={'status':'blocked_reuse','associations':[],'world_geometry_additions':0}
    if reuse_allowed is not True:
        return base
    if polygons.get('status')!='unplaced_candidates':
        return {**base,'status':'geometry_unavailable'}
    labels=[]
    fragments=characters=omitted=0

    def visit(text, cm, tm, font, size):
        nonlocal fragments,characters,omitted
        if not text.strip():
            return
        fragments+=1
        characters+=len(text)
        if fragments>max_fragments or characters>max_text:
            raise ValueError('Text association budget exceeded')
        # Multiple extracted lines may have different origins. Never collapse
        # them onto the single visitor anchor.
        if len(text.strip().splitlines())!=1 or len(text)>2000:
            omitted+=1
            return
        evidence=evidence_candidates(text)
        features=[kind for kind,pattern in FEATURES.items() if re.search(pattern,text,re.I)]
        if not (features or evidence['levels'] or evidence['materials']):
            return
        x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4]
        y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Nonfinite text origin')
        if not (float(page.cropbox.left)<x<float(page.cropbox.right) and
                float(page.cropbox.bottom)<y<float(page.cropbox.top)):
            omitted+=1
            return
        for viewport in registration.get('viewports',[]):
            try:
                anchor=page_point_to_metric(viewport,x,y)
            except ValueError:
                continue
            labels.append({'viewport':viewport['viewport'],'metric_crs':viewport['metric_crs'],
                           'metric_anchor':list(anchor),'fragment_index':fragments,
                           'feature_type_candidates':features,'levels':evidence['levels'],
                           'materials':evidence['materials']})

    try:
        page.extract_text(visitor_text=visit)
        result=associate_labels(polygons,labels)
        result['omitted_text_fragments']=omitted
        result['limitations']=['Native text origins may be unreliable and are not text extents or leader targets',
                              'Interior containment is not semantic, survey or construction verification',
                              'No cross-page elevation association, OCR or world insertion']
        return result
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**base,'status':'unsupported_or_rejected','reason':str(error)}
