"""Bounded explicitly labelled straight coordinate-grid candidates."""
import math
import re

from .coordinate_text import coordinate_runs

from shapely.geometry import LineString

from .drawing_marks import extract_marks

LABEL=re.compile(r'^\s*(E|Easting|N|Northing)\s*[:=]\s*([+-]?\d{1,9}(?:\.\d{1,4})?)\s*(?:m\b)?\s*$',re.I)


def extract_grid_controls(page, *, reuse_allowed=False, max_fragments=2000, max_text=500_000):
    result={'status':'blocked_reuse','pairs':[],'world_geometry_additions':0}
    if reuse_allowed is not True:
        return result
    try:
        vectors=extract_marks(page,reuse_allowed=True)
        if vectors['status']!='crosshair_candidates':
            raise ValueError('Supported native straight strokes required')
        segments=[s for s in vectors['segments'] if math.dist(*s)>=50]
        labels=[]
        fragments=characters=0

        def visit(text,cm,tm,font,size):
            nonlocal fragments,characters
            fragments+=1;characters+=len(text)
            if fragments>max_fragments or characters>max_text:
                raise ValueError('Grid text budget exceeded')
            match=LABEL.fullmatch(text)
            if match:
                labels.append((match[1][0].upper(),float(match[2]),
                    [tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5]]))
                if len(labels)>64:
                    raise ValueError('Grid label budget exceeded')

        for run in coordinate_runs(page,max_fragments=max_fragments,max_text=max_text):
            visit(run['text'],run['cm'],run['tm'],run['font'],run['size'])
        groups={'E':[],'N':[]}
        used=set()
        for axis,value,origin in labels:
            # Explicit attachment only: a line endpoint within one PDF point
            # of the native label origin. Do not select the nearest grid line.
            matches=[i for i,s in enumerate(segments) if min(math.dist(origin,p) for p in s)<=1]
            if len(matches)!=1 or matches[0] in used:
                raise ValueError('Grid label requires one unique unused line endpoint')
            used.add(matches[0])
            groups[axis].append((value,segments[matches[0]]))
        if min(len(g) for g in groups.values())<2 or len(groups['E'])*len(groups['N'])>64:
            raise ValueError('Two lines per coordinate axis and at most 64 intersections required')
        for group in groups.values():
            if len({value for value,_ in group})!=len(group):
                raise ValueError('Duplicate grid coordinate labels')
            first=group[0][1]
            ax,ay=first[1][0]-first[0][0],first[1][1]-first[0][1]
            for _,segment in group[1:]:
                bx,by=segment[1][0]-segment[0][0],segment[1][1]-segment[0][1]
                if abs(ax*by-ay*bx)/(math.hypot(ax,ay)*math.hypot(bx,by))>1e-6:
                    raise ValueError('Same-axis grid lines must be parallel')
        pairs=[]
        for east,e_line in groups['E']:
            for north,n_line in groups['N']:
                ax,ay=e_line[1][0]-e_line[0][0],e_line[1][1]-e_line[0][1]
                bx,by=n_line[1][0]-n_line[0][0],n_line[1][1]-n_line[0][1]
                if abs(ax*by-ay*bx)/(math.hypot(ax,ay)*math.hypot(bx,by))<.1:
                    raise ValueError('Coordinate axes are nearly parallel')
                point=LineString(e_line).intersection(LineString(n_line))
                if point.geom_type!='Point' or point.is_empty:
                    raise ValueError('Grid strokes must intersect without extrapolation')
                pairs.append((point.x,point.y,east,north))
        return {**result,'status':'grid_intersection_candidates','pairs':pairs,
                'limitations':['Explicit endpoint-label attachment uses a one-point PDF tolerance',
                               'Grid coordinate declarations and line identity are unverified',
                               'No unlabeled grid, split strokes, curved/raster rendering or world insertion']}
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**result,'status':'rejected','reason':str(error)}
