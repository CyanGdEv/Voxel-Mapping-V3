"""Bounded dotted straight-line hypotheses; no registration or world geometry."""
import math
import statistics


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


def inspect_dotted_grid(page):
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
        return {**report,'status':'dotted_line_hypotheses' if candidates else 'no_supported_dotted_lines',
                'candidate_count':len(candidates),
                'vertical_candidate_count':sum(c['axis']=='vertical' for c in candidates),
                'horizontal_candidate_count':sum(c['axis']=='horizontal' for c in candidates),
                'clipping_operator_count':clipping,'form_operator_count':forms,
                'visible_rendering_verified':False}
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**report,'status':'rejected_dotted_inspection','reason':str(error)}
