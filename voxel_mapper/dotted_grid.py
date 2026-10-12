"""Bounded dotted straight-line hypotheses; no registration or world geometry."""
import math
import statistics
import re
import numpy as np
from .drawing_landmarks import inspect_named_landmarks, normalise_name


def inspect_labelled_intersections(lines, labels, *, named_labels=(), reference_features=None, metric_crs_hypothesis=None):
    report={'status':'insufficient_labelled_intersections','registration_verified':False,
            'world_geometry_additions':0,'controls_exported':False,
            'limitations':['Unique one-point label-to-line proximity is an attachment hypothesis',
                           'Intersections are limited to reconstructed run extents; missing runs are not bridged',
                           'Internal residuals do not verify CRS, clipped visibility or independent alignment']}
    if len(lines)>64 or len(labels)>64:raise ValueError('Dotted attachment budget exceeded')
    assigned={};ambiguous=unattached=0
    for label in labels:
        axis=label['axis'];x,y=label['origin'];value=label['value']
        if axis not in ('E','N') or not all(math.isfinite(v) for v in (x,y,value)):
            raise ValueError('Finite labelled axes required')
        candidates=[line for line in lines if line['axis']==('vertical' if axis=='E' else 'horizontal')
                    and abs(line['position']-(x if axis=='E' else y))<=1
                    and line['extent'][0]-1<=(y if axis=='E' else x)<=line['extent'][1]+1]
        positions={line['position'] for line in candidates}
        if len(positions)!=1:
            ambiguous+=len(positions)>1;unattached+=not positions;continue
        position=positions.pop();key=(axis,position)
        if key in assigned and assigned[key]!=value:
            return {**report,'status':'conflicting_coordinate_labels'}
        assigned[key]=value
    report.update(attached_coordinate_count=len(assigned),ambiguous_label_count=ambiguous,
                  unattached_label_count=unattached)
    controls=set()
    for vertical in [l for l in lines if l['axis']=='vertical' and ('E',l['position']) in assigned]:
        for horizontal in [l for l in lines if l['axis']=='horizontal' and ('N',l['position']) in assigned]:
            x,y=vertical['position'],horizontal['position']
            if vertical['extent'][0]<=y<=vertical['extent'][1] and horizontal['extent'][0]<=x<=horizontal['extent'][1]:
                controls.add((x,y,assigned[('E',x)],assigned[('N',y)]))
    report['intersection_count']=len(controls)
    if len(controls)>64:return {**report,'status':'intersection_budget_exceeded'}
    if len(controls)<4:return report
    controls=np.array(sorted(controls));pixels=controls[:,:2];coordinates=controls[:,2:]
    design=np.column_stack((pixels-pixels.mean(axis=0),np.ones(len(pixels))))
    if np.linalg.matrix_rank(design)!=3 or np.linalg.cond(design)>10_000:
        return {**report,'status':'degenerate_intersections'}
    fit=np.linalg.lstsq(design,coordinates,rcond=None)[0]
    if fit[0,0]<=0 or fit[1,1]<=0 or abs(np.linalg.det(fit[:2]))<1e-9 or np.any(np.ptp(coordinates,axis=0)>20_000):
        return {**report,'status':'rejected_coordinate_orientation_or_extent'}
    residuals=[]
    for i in range(len(design)):
        training=np.delete(design,i,axis=0)
        if np.linalg.matrix_rank(training)!=3:return {**report,'status':'insufficient_withheld_intersections'}
        fit=np.linalg.lstsq(training,np.delete(coordinates,i,axis=0),rcond=None)[0]
        residuals.append(float(np.linalg.norm(design[i]@fit-coordinates[i])))
    report['max_withheld_error_coordinate_units']=max(residuals)
    report['status']='consistent_labelled_intersections_unverified' if max(residuals)<=.5 else 'inconsistent_labelled_intersections'
    if report['status']=='consistent_labelled_intersections_unverified' and reference_features is not None and metric_crs_hypothesis is not None:
        report['named_landmark_inspection']=inspect_named_landmarks(controls,named_labels,reference_features,metric_crs_hypothesis)
    return report


def reconstruct_dotted_lines(segments, *, max_segments=250_000):
    if len(segments)>max_segments:
        raise ValueError('Dotted segment budget exceeded')
    groups={}
    for start,end in segments:
        x,y=start; X,Y=end
        if not all(math.isfinite(v) for v in (x,y,X,Y)):
            raise ValueError('Finite dotted strokes required')
        length=math.dist(start,end)
        if not .05<=length<=3:continue
        if abs(x-X)<1e-6:
            key=('vertical',round(x,6));interval=sorted((y,Y))
        elif abs(y-Y)<1e-6:
            key=('horizontal',round(y,6));interval=sorted((x,X))
        else:continue
        groups.setdefault(key,[]).append(interval)
    candidates=[]
    for (axis,position),intervals in groups.items():
        intervals=sorted(set(map(tuple,intervals)))
        if len(intervals)<30:continue
        lengths=[b-a for a,b in intervals]
        gaps=[intervals[i+1][0]-intervals[i][1] for i in range(len(intervals)-1)]
        gap=statistics.median(gaps); length=statistics.median(lengths)
        # Do not bridge missing dashes, overlap, or turn irregular hatching
        # into a continuous line. Both ink and gap spacing must be regular.
        if not .05<=gap<=20:continue
        runs=[];run=[]
        for interval in intervals:
            valid_length=abs(interval[1]-interval[0]-length)<=max(.02,.1*length)
            if not valid_length or (run and abs(interval[0]-run[-1][1]-gap)>max(.02,.1*gap)):
                if run:runs.append(run)
                run=[]
            if valid_length:run.append(interval)
        if run:runs.append(run)
        for run in runs:
            low,high=run[0][0],run[-1][1]
            if len(run)<30 or high-low<100:continue
            candidates.append({'axis':axis,'position':position,'extent':[low,high],
                               'stroke_count':len(run),'dash_length':length,'gap':gap})
            if len(candidates)>64:raise ValueError('Dotted line candidate budget exceeded')
    return candidates


def inspect_dotted_grid(page, reference_features=None, metric_crs_hypothesis=None):
    report={'status':'unavailable','world_geometry_additions':0,'registration_verified':False,
            'controls_exported':False,'limitations':[
                'Periodic collinear strokes are line hypotheses, not labelled grid controls',
                'Curves, fills, forms and clipped visibility are not reconstructed',
                'No coordinates, intersections, transforms or polygons exported']}
    try:
        stream=page.get_contents()
        if stream is None:return {**report,'status':'empty_page'}
        if len(stream.get_data())>10_000_000:raise ValueError('Dotted content byte budget exceeded')
        operations=stream.operations
        if len(operations)>1_000_000:raise ValueError('Dotted operator budget exceeded')
        matrix=(1,0,0,1,0,0);stack=[];path=[];segments=[];clipping=forms=0
        left,bottom,right,top=map(float,page.cropbox)
        def point(args):
            x,y=map(float,args);a,b,c,d,e,f=matrix
            result=(a*x+c*y+e,b*x+d*y+f)
            if not all(math.isfinite(v) for v in result):raise ValueError('Nonfinite dotted path')
            return result
        for args,op in operations:
            if op==b'q':
                if len(stack)>=64:raise ValueError('Dotted graphics stack budget exceeded')
                stack.append(matrix)
            elif op==b'Q':
                if not stack:raise ValueError('Unbalanced dotted graphics restore')
                matrix=stack.pop()
            elif op==b'cm':
                a,b,c,d,e,f=map(float,args);A,B,C,D,E,F=matrix
                if not all(math.isfinite(v) for v in (a,b,c,d,e,f)) or abs(a*d-b*c)<1e-12:
                    raise ValueError('Invalid dotted transformation')
                matrix=(a*A+b*C,a*B+b*D,c*A+d*C,c*B+d*D,e*A+f*C+E,e*B+f*D+F)
            elif op==b'm':path=[point(args)]
            elif op==b'l':
                if path is not None:
                    path.append(point(args))
                    if len(path)>2:path=None
            elif op in (b'c',b'v',b'y',b're',b'h'):path=None
            elif op in (b'W',b'W*'):clipping+=1
            elif op==b'Do':forms+=1
            elif op in (b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'n'):
                if op==b'S' and path is not None and len(path)==2:
                    if all(left<=x<=right and bottom<=y<=top for x,y in path):
                        segments.append(path)
                    if len(segments)>250_000:raise ValueError('Dotted segment budget exceeded')
                path=[]
        if stack:raise ValueError('Unbalanced dotted graphics save')
        candidates=reconstruct_dotted_lines(segments)
        labels=[];named_labels=[];callbacks=characters=0
        names={normalise_name(f['properties']['name']) for f in reference_features or []
               if isinstance(f.get('properties',{}).get('name'),str) and f.get('properties',{}).get('source_id')=='osm'}
        def visit(text,cm,tm,font,size):
            nonlocal callbacks,characters
            callbacks+=1;characters+=len(text)
            if callbacks>200_000 or characters>500_000:raise ValueError('Dotted label text budget exceeded')
            match=re.fullmatch(r'(\d{6})([EN])',text.strip(),re.I)
            if normalise_name(text) in names:
                named_labels.append({'text':text.strip(),'origin':[tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5]]})
                if len(named_labels)>64:raise ValueError('Named landmark label budget exceeded')
            if match:
                labels.append({'axis':match[2].upper(),'value':int(match[1]),
                               'origin':[tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5]]})
                if len(labels)>64:raise ValueError('Dotted label budget exceeded')
        page.extract_text(visitor_text=visit)
        attachment=inspect_labelled_intersections(candidates,labels,named_labels=named_labels,
                                                 reference_features=reference_features,metric_crs_hypothesis=metric_crs_hypothesis)
        return {**report,'status':'dotted_line_hypotheses' if candidates else 'no_supported_dotted_lines',
                'labelled_intersection_inspection':attachment,
                'candidate_count':len(candidates),
                'vertical_candidate_count':sum(c['axis']=='vertical' for c in candidates),
                'horizontal_candidate_count':sum(c['axis']=='horizontal' for c in candidates),
                'clipping_operator_count':clipping,'form_operator_count':forms,
                'visible_rendering_verified':False}
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**report,'status':'rejected_dotted_inspection','reason':str(error)}
