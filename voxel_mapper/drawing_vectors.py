"""Conservative, reuse-gated straight PDF boundary candidates; never world features."""
import numpy as np
from shapely.geometry import LineString, Polygon, box

from .geopdf import page_point_to_metric


def extract_vectors(page, registration, *, reuse_allowed=False, max_operations=100_000,
                    max_paths=2000, max_points=20_000):
    """Keep viewports/CRSs separate. Unsupported rendering rejects the whole page.

    Filled paths are boundaries, not inferred footprints. Curves, clipping, forms,
    optional content and external graphics states need a richer renderer.
    """
    report = {'status':'blocked_reuse', 'layers':[], 'world_geometry_additions':0,
              'semantic_status':'unclassified', 'construction_status':'not_verified'}
    if reuse_allowed is not True:
        return report
    viewports = [v for v in registration.get('viewports',[])
                 if v.get('status') == 'internally_consistent_unverified']
    if not viewports:
        return {**report, 'status':'registration_unavailable'}
    if min(max_operations,max_paths,max_points) < 1:
        raise ValueError('Positive extraction budgets required')
    try:
        stream = page.get_contents()
        if stream is None:
            return {**report, 'status':'no_vector_paths'}
        if len(stream.get_data()) > 10_000_000:
            raise ValueError('Content byte budget exceeded')
        operations = stream.operations
        if len(operations) > max_operations:
            raise ValueError('Operator budget exceeded')
        matrix = np.eye(3)
        stack, subpaths, current, painted = [], [], None, []
        point_count = 0
        paint_group = 0

        def point(x,y):
            nonlocal point_count
            point_count += 1
            if point_count > max_points:
                raise ValueError('Point budget exceeded')
            values = np.array([float(x),float(y),1.]) @ matrix
            if not np.all(np.isfinite(values)):
                raise ValueError('Nonfinite path coordinates')
            return values[:2].tolist()

        # State/text/style operators that cannot introduce geometric paths.
        harmless = set(b'BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ \' " w J j M d ri G g RG rg K k CS cs SC SCN sc scn'.split())
        paint = {b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'n'}
        for operands, op in operations:
            if op == b'q':
                if len(stack) >= 64:
                    raise ValueError('Graphics stack budget exceeded')
                stack.append(matrix.copy())
            elif op == b'Q':
                if not stack:
                    raise ValueError('Unbalanced graphics restore')
                matrix = stack.pop()
            elif op == b'cm':
                a,b,c,d,e,f = map(float,operands)
                transform = np.array([[a,b,0.],[c,d,0.],[e,f,1.]])
                if not np.all(np.isfinite(transform)) or abs(a*d-b*c)<1e-12:
                    raise ValueError('Invalid content transformation')
                matrix = transform @ matrix
            elif op == b'm':
                current = [point(*operands)]; subpaths.append(current)
            elif op == b'l':
                if current is None:
                    raise ValueError('Line without a current path')
                current.append(point(*operands))
            elif op == b're':
                x,y,w,h = map(float,operands)
                current = [point(x,y),point(x+w,y),point(x+w,y+h),point(x,y+h)]
                current.append(current[0]); subpaths.append(current)
            elif op == b'h':
                if not current:
                    raise ValueError('Close without a current path')
                if current[-1] != current[0]:
                    current.append(current[0])
            elif op in paint:
                if op in {b's',b'b',b'b*'} and current and current[-1] != current[0]:
                    current.append(current[0])
                if op != b'n':
                    for path in subpaths:
                        if len(path)<2:
                            continue
                        # Fill implicitly closes every subpath; retain its boundary only.
                        boundary = list(path)
                        if op not in {b'S',b's'} and boundary[-1] != boundary[0]:
                            boundary.append(boundary[0])
                        painted.append((boundary,op.decode('ascii'),paint_group))
                        if len(painted)>max_paths:
                            raise ValueError('Path budget exceeded')
                subpaths, current = [], None
                paint_group += 1
            elif op == b'Tr' and int(operands[0]) >= 4:
                raise ValueError('Text clipping is unsupported')
            elif op not in harmless:
                raise ValueError('Unsupported rendering operator: '+op.decode('ascii',errors='replace'))
        if stack or subpaths:
            raise ValueError('Unbalanced graphics state or unfinished path')
        layers = []
        for viewport in viewports:
            left,bottom,right,top = viewport['viewport_bbox']
            domain = Polygon([(left+u*(right-left),bottom+v*(top-bottom))
                              for u,v in viewport['control_hull']])
            domain = domain.intersection(box(*map(float,page.cropbox)))
            paths, omitted = [], 0
            incomplete_groups = set()
            for index,(boundary,operator,group) in enumerate(painted):
                line = LineString(boundary)
                if line.length == 0 or not domain.covers(line):
                    omitted += 1
                    incomplete_groups.add(group)
                    continue
                coordinates = [list(page_point_to_metric(viewport,*p)) for p in boundary]
                paths.append({'path_index':index,'paint_operator':operator,
                              'paint_group':group,
                              'closed':boundary[0]==boundary[-1],
                              'geometry':{'type':'LineString','coordinates':coordinates}})
            layers.append({'viewport':viewport['viewport'], 'metric_crs':viewport['metric_crs'],
                           'status':'unclassified_boundary_candidates', 'paths':paths,
                           'incomplete_paint_groups':sorted(incomplete_groups),
                           'omitted_outside_domain_or_degenerate':omitted})
        return {**report,'status':'unverified_candidates' if painted else 'no_vector_paths',
                'layers':layers, 'painted_subpaths':len(painted),
                'limitations':['No footprint/road/ride classification or fill topology inferred',
                               'Embedded registration is not independent surveyed accuracy',
                               'No world insertion; viewports remain separate']}
    except (ValueError,TypeError,KeyError,IndexError) as error:
        return {**report,'status':'unsupported_or_rejected','reason':str(error)}
