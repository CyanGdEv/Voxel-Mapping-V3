"""Apply source-bound corrections to new, provisional local candidates.

The original candidate, review and learning labels are immutable. Regeneration
creates geometry and native previews; it never establishes park registration.
"""
from concurrent.futures import CancelledError
import copy
import json
import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .building_spec import FRAME, build, digest, _geometry
from .generation_cycles import atomic_json

VERSION = 'building-correction-regeneration-v1'
PROJECTIONS = {'xy': (0, 1), 'xz': (0, 2), 'yz': (1, 2)}
MAX_GUARDS = 100000


def _check(cancelled):
    if cancelled():raise CancelledError()


def _progress(callback, fraction, message):
    if callback:callback({'progress': fraction, 'message': message})


def _mesh_bounds(component):
    vertices = component['mesh']['vertices']
    return [[min(v[i] for v in vertices), max(v[i] for v in vertices)] for i in range(3)]


def _polygon_geometry(geometry):
    polygon = Polygon(geometry['profile'], geometry.get('holes', []))
    if not polygon.is_valid or polygon.area <= 1e-8:
        raise ValueError('The corrected extrusion must remain a valid nonempty polygon')
    return polygon


def _set_polygon(geometry, polygon):
    if polygon.geom_type != 'Polygon' or not polygon.is_valid or polygon.area <= 1e-8:
        raise ValueError('The edit would split or invalidate the component; a single supported extrusion is required')
    geometry['profile'] = [list(p) for p in list(polygon.exterior.coords)[:-1]]
    geometry['holes'] = [[list(p) for p in list(ring.coords)[:-1]] for ring in polygon.interiors]


def _profile_axes(geometry, annotation):
    if geometry['kind'] != 'extrusion':
        raise ValueError('Outline/opening edits require an explicit extrusion; the retained mesh has no unambiguous extrusion depth')
    axes = tuple(i for i in range(3) if i != geometry['axis'])
    if PROJECTIONS[annotation['projection']] != axes:
        raise ValueError('Choose the projection matching the extrusion profile plane')
    return axes


def _scale_component(component, axis, target):
    mesh = {'mesh':_geometry(component['geometry'])}
    low, high = _mesh_bounds(mesh)[axis]
    if high-low <= 1e-8:raise ValueError('Cannot assign a dimension along a zero-span component axis')
    factor = target/(high-low)
    if not 1e-4 <= factor <= 10000:raise ValueError('Dimension scale exceeds the supported budget')
    def scale(value):return low+(value-low)*factor
    geometry = component['geometry']
    if geometry['kind'] == 'mesh':
        for vertex in geometry['mesh']['vertices']:vertex[axis] = scale(vertex[axis])
    elif geometry['axis'] == axis:
        geometry['interval_m'] = [scale(v) for v in geometry['interval_m']]
    else:
        column = [i for i in range(3) if i != geometry['axis']].index(axis)
        for ring in [geometry['profile'], *geometry.get('holes', [])]:
            for point in ring:point[column] = scale(point[column])


def _opening(geometry, annotation, guards):
    axes = _profile_axes(geometry, annotation)
    opening = Polygon(annotation['points_m'])
    outer = Polygon(geometry['profile'])
    if not outer.covers(opening):raise ValueError('An opening must lie within the component outer profile')
    holes = [Polygon(ring) for ring in geometry.get('holes', [])]
    matches = [i for i, hole in enumerate(holes) if hole.intersection(opening).area > 1e-8]
    if len(matches) > 1:raise ValueError('Opening correction overlaps several original holes; identify them separately')
    # A single overlapping hole is replaced; a disjoint polygon adds an opening.
    kept = [ring for i, ring in enumerate(geometry.get('holes', [])) if i not in matches]
    _set_polygon(geometry, Polygon(geometry['profile'], kept).difference(opening))
    # Interior holes already carry their own component-bound guard geometry in
    # the native compiler. Only boundary notches need extra explicit air cells.
    if outer.boundary.intersection(opening.boundary).length <= 1e-8:return
    low, high = geometry['interval_m'];xmin,ymin,xmax,ymax = opening.bounds
    work = (math.ceil(2*xmax)-math.floor(2*xmin))*(math.ceil(2*ymax)-math.floor(2*ymin))*(2*math.ceil(high)-2*math.floor(low))
    if work > 2000000:raise ValueError('Opening protection work budget exceeded')
    from shapely.geometry import Point
    for u in range(math.floor(2*xmin), math.ceil(2*xmax)):
        for v in range(math.floor(2*ymin), math.ceil(2*ymax)):
            if not opening.covers(Point((u+.5)/2, (v+.5)/2)):continue
            for depth in range(2*math.floor(low), 2*math.ceil(high)):
                point = [0, 0, 0];point[axes[0]]=u;point[axes[1]]=v;point[geometry['axis']]=depth
                guards.add((point[0], point[2], point[1]))
                if len(guards)>MAX_GUARDS:raise ValueError('Opening air protection budget exceeded')


def _pose(spec, annotation, guards):
    angle = annotation['rotation_degrees'];translation = annotation['translation_m']
    quarter = round(angle/90)
    protected = bool(guards) or any(c['geometry']['kind']=='extrusion' and c['geometry'].get('holes') for c in spec['components'])
    # Extrusion axes and native half-cubes must retain an exact representation.
    if abs(angle-quarter*90)>1e-8:
        raise ValueError('This preview supports placement rotations in 90-degree steps')
    if protected and any(abs(v*2-round(v*2))>1e-8 for v in translation):
        raise ValueError('Placement with protected openings requires half-metre translations')
    cosine = (1,0,-1,0)[quarter%4];sine = (0,1,0,-1)[quarter%4]
    def transform(point):
        x,y,z=point
        return [cosine*x-sine*y+translation[0], sine*x+cosine*y+translation[1], z+translation[2]]
    for component in spec['components']:
        geometry=component['geometry']
        if geometry['kind']=='mesh':
            geometry['mesh']['vertices']=[transform(v) for v in geometry['mesh']['vertices']]
            continue
        old_axis=geometry['axis'];other=[i for i in range(3) if i!=old_axis]
        new_axis=old_axis if old_axis==2 or quarter%2==0 else 1-old_axis
        new_other=[i for i in range(3) if i!=new_axis]
        intervals=[]
        for value in geometry['interval_m']:
            point=[0,0,0];point[old_axis]=value;intervals.append(transform(point)[new_axis])
        for ring in [geometry['profile'], *geometry.get('holes',[])]:
            for point in ring:
                vertex=[0,0,0];vertex[other[0]],vertex[other[1]]=point
                moved=transform(vertex);point[:]=[moved[i] for i in new_other]
        geometry['axis']=new_axis;geometry['interval_m']=sorted(intervals)
    moved_guards=set()
    for x,height,y in guards:
        vertex=transform([(x+.5)/2,(y+.5)/2,(height+.5)/2])
        half=[round(2*v-.5) for v in vertex]
        moved_guards.add((half[0],half[2],half[1]))
    return moved_guards


def _geometry_signature(spec):
    model=build(spec)
    return digest({'components':[{'id':c['id'],'role':c['role'],
        'vertices':[[round(float(v),9) for v in p] for p in c['mesh']['vertices']],
        'triangles':c['mesh']['triangles']} for c in model['components']],
        'native_air_halves':sorted(spec.get('native_air_halves',[]))})


def _apply(spec, annotations):
    """Geometry stage; caller must first validate the saved source-bound review."""
    build(spec)
    if not annotations:raise ValueError('Save at least one geometry correction before regenerating')
    revised=copy.deepcopy(spec);components={c['id']:c for c in revised['components']}
    guards={tuple(p) for p in spec.get('native_air_halves',[])}
    shape_edits=[a for a in annotations if a['type']!='placement']
    if guards and shape_edits:
        raise ValueError('This mesh has unassigned native air guards; shape/dimension edits need component-bound opening evidence. Local placement remains supported.')
    seen=set();operations=[];opening_edits={}
    for kind in ('outline','dimension','opening','placement'):
        for annotation in (a for a in annotations if a['type']==kind):
            key=(kind,annotation.get('component_id'),annotation.get('axis'))
            if kind!='opening' and key in seen:raise ValueError('Conflicting repeated correction for the same component/axis')
            seen.add(key)
            if kind=='placement':
                guards=_pose(revised,annotation,guards)
                changed=list(components.values())
            else:
                component=components[annotation['component_id']];geometry=component['geometry']
                if kind=='outline':
                    _profile_axes(geometry,annotation)
                    _set_polygon(geometry,Polygon(annotation['points_m'],geometry.get('holes',[])))
                elif kind=='dimension':_scale_component(component,'xyz'.index(annotation['axis']),annotation['value_m'])
                else:
                    opening=Polygon(annotation['points_m'])
                    previous=opening_edits.setdefault(annotation['component_id'],[])
                    if any(opening.intersection(p).area>1e-8 for p in previous):
                        raise ValueError('Overlapping opening corrections have ambiguous replacement intent')
                    previous.append(opening);_opening(geometry,annotation,guards)
                changed=[component]
            source=next((s for s in revised['sources'] if s['sha256']==annotation['source_sha256']),None)
            if source is None:
                identifier='correction-'+annotation['source_sha256'][:16]
                if any(s['id']==identifier for s in revised['sources']):raise ValueError('Correction source identity collision')
                source={'id':identifier,'sha256':annotation['source_sha256'],'state':revised['sources'][0]['state']}
                revised['sources'].append(source)
            for component in changed:
                component['evidence']['class']='inferred'
                refs=component['evidence']['source_ids']
                if source['id'] not in refs:refs.append(source['id'])
                component['evidence']['description']+='; provisional '+kind+' correction from source page '+str(annotation['source_page'])
            operations.append(copy.deepcopy(annotation))
    if guards:revised['native_air_halves']=[list(p) for p in sorted(guards)]
    if _geometry_signature(revised)==_geometry_signature(spec):raise ValueError('The saved corrections do not change the geometry')
    revised.pop('floor_reference',None)
    revised['assumptions']=list(revised['assumptions'])+[
        'Source-linked user corrections create a new provisional interpretation; original geometry and review outcomes are retained.',
        'Dimensions scale one component about its minimum coordinate; local placement is not geographic registration.']
    # Revalidate bounds, polygon topology, meshes and complete building budgets.
    build(revised)
    return revised,{'operation_order':'outline, dimension, opening, then placement',
        'applied':operations,'original_spec_sha256':digest(spec),'corrected_spec_sha256':digest(revised),
        'floor_reference_invalidated':'floor_reference' in spec,'explicit_air_guard_halves':len(guards)}


def geometry_metrics(spec, component_id=None):
    """Derive measurements, without fitting geometry to a supplied reference."""
    model=build(spec);components=model['components']
    if component_id:
        components=[c for c in components if c['id']==component_id]
        if not components:raise ValueError('Benchmark reference names an unknown component')
    vertices=[v for c in components for v in c['mesh']['vertices']]
    polygons=[];checks=0
    for component in components:
        mesh=component['mesh']
        for triangle in mesh['triangles']:
            checks+=1
            if checks>20000:raise ValueError('Projected benchmark geometry exceeds its triangle budget')
            polygon=Polygon([mesh['vertices'][i][:2] for i in triangle])
            if polygon.is_valid and polygon.area>1e-10:polygons.append(polygon)
    footprint=unary_union(polygons)
    if footprint.geom_type!='Polygon' or footprint.is_empty:
        raise ValueError('Benchmark needs a single nonempty projected footprint; choose a supported component')
    exterior=[list(p) for p in list(footprint.exterior.coords)[:-1]]
    result={'footprint_m':{'exterior':exterior,'holes':[[list(p) for p in list(r.coords)[:-1]] for r in footprint.interiors]},
        'height_m':max(v[2] for v in vertices)-min(v[2] for v in vertices),
        'position_m':[min(v[i] for v in vertices) for i in range(3)]}
    if component_id:
        geometry=next(c for c in spec['components'] if c['id']==component_id)['geometry']
        if geometry['kind']=='extrusion':result['openings_m']=copy.deepcopy(geometry.get('holes',[]))
    return result


def _benchmarks(config, original, corrected, row, model):
    from .reconstruction_benchmark import evaluate
    if config.get('coordinate_frame')!=FRAME:raise ValueError('Correction benchmarks require the explicit local XYZ metre frame')
    before=copy.deepcopy(config);after=copy.deepcopy(config)
    for target,spec in ((before,original),(after,corrected)):
        for case in target.get('cases',[]):
            if case.get('building_id')!=row['building_id'] or set(case.get('source_sha256',[]))!=set(row['source_sha256']):
                raise ValueError('Benchmark references must bind this building and its complete original source set')
            reference=case.get('reference',{})
            if reference.get('geometry_definition')!='projected_xy_bounds_origin_v1':
                raise ValueError('References must declare the projected-XY footprint and bounds-minimum origin convention')
            case['prediction']=geometry_metrics(spec,reference.get('component_id'))
            if 'openings_m' in reference.get('geometry',{}):
                projection=reference.get('opening_projection')
                if projection not in PROJECTIONS:raise ValueError('Opening references need an explicit XY, XZ or YZ comparison plane')
                component=next((c for c in spec['components'] if c['id']==reference.get('component_id')),None)
                geometry=component['geometry'] if component else {}
                if geometry.get('kind')!='extrusion' or PROJECTIONS[projection]!=tuple(i for i in range(3) if i!=geometry.get('axis')):
                    # Rotating a facade does not make its openings agree with a
                    # reference in another physical plane.
                    case['prediction'].pop('openings_m',None)
    return evaluate(before,model=model),evaluate(after,model=model)


def _comparison_svg(original, corrected, path):
    models=[build(original),build(corrected)];panels=[]
    for offset,axes,title in ((0,(0,1),'Plan XY'),(480,(0,2),'Elevation XZ')):
        vertices=[v for model in models for c in model['components'] for v in c['mesh']['vertices']]
        lo=[min(v[a] for v in vertices) for a in axes];hi=[max(v[a] for v in vertices) for a in axes]
        scale=min(420/max(hi[0]-lo[0],.1),300/max(hi[1]-lo[1],.1))
        panels.append(f'<text x="{offset+25}" y="45">{title}</text>')
        for model,colour in zip(models,('#3766b0','#d36b18')):
            edges=set()
            for component in model['components']:
                mesh=component['mesh']
                for triangle in mesh['triangles']:
                    for i in range(3):
                        a,b=[mesh['vertices'][j] for j in (triangle[i],triangle[(i+1)%3])]
                        edge=tuple(sorted((tuple(a),tuple(b))))
                        if edge in edges:continue
                        edges.add(edge)
                        if len(edges)>20000:raise ValueError('Geometry comparison display budget exceeded')
                        x1=offset+25+(a[axes[0]]-lo[0])*scale;y1=370-(a[axes[1]]-lo[1])*scale
                        x2=offset+25+(b[axes[0]]-lo[0])*scale;y2=370-(b[axes[1]]-lo[1])*scale
                        panels.append(f'<path d="M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}" stroke="{colour}" fill="none"/>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="430"><rect width="960" height="430" fill="white"/><g font-family="sans-serif" font-size="15"><text x="25" y="22">Original: blue | corrected proposal: orange | local metres</text>'+''.join(panels)+'</g></svg>',encoding='utf-8')


def run(saved_review, output, *, world=True, benchmark_path=None, model=None, cancelled=lambda:False, progress=None):
    """Regenerate from an immutable saved draft/review in a managed worker."""
    from .desktop_review import resume_review
    from .desktop_runtime import file_hash,read_json
    from .building_native import compile_spec,export_preview
    from .building_learning import FEATURES,GATES
    from .study_mesh_export import write_glb
    if type(world) is not bool:raise ValueError('Native world output setting must be boolean')
    root=Path(output).expanduser().resolve()
    if root.exists():raise ValueError('A fresh correction regeneration output directory is required')
    _check(cancelled);_progress(progress,.05,'Checking saved corrections and original source evidence')
    restored=resume_review(saved_review);session=restored['session']
    row=next(r for r in session['records'] if r['building_id']==restored['building_id'] and r['candidate_sha256']==restored['candidate_sha256'])
    original=row['candidate']['spec'];corrected,operations=_apply(original,restored['corrections'])
    _check(cancelled);_progress(progress,.2,'Checking the corrected model and protected openings')
    _,original_audit=compile_spec(original);_,corrected_audit=compile_spec(corrected)
    benchmark_pin=None;benchmarks=None
    if benchmark_path:
        benchmark_pin=file_hash(benchmark_path);config=read_json(benchmark_path)
        if file_hash(benchmark_path)!=benchmark_pin:raise ValueError('Benchmark references changed during loading')
        benchmarks=_benchmarks(config,original,corrected,row,model)
    _check(cancelled);root.mkdir(parents=True)
    atomic_json(root/'original-spec.json',original);atomic_json(root/'corrected-spec.json',corrected)
    write_glb(build(original),root/'original.glb');write_glb(build(corrected),root/'corrected.glb')
    _progress(progress,.4,'Generating original and corrected native previews')
    native_original=export_preview(original,root/'original-native',world=world)
    _check(cancelled)
    native_corrected=export_preview(corrected,root/'corrected-native',world=world)
    _comparison_svg(original,corrected,root/'geometry-comparison.svg')
    features=dict.fromkeys(FEATURES,0.)
    features['source_coverage']=sum(sha in session['resolved_sources'] for sha in row['source_sha256'])/len(row['source_sha256'])
    topology=corrected_audit['structural_review'].get('native_diagnostic_score')
    if topology is not None:features['topology_quality']=topology
    candidate={'id':'corrected-'+digest(operations)[:16],'spec':corrected,'features':features,'gates':dict.fromkeys(GATES,False),
        'source_feed':{'version':VERSION,'original_pdf_sha256':row['source_sha256'],
            'verified_pdf_sha256':sorted(sha for sha in row['source_sha256'] if sha in session['resolved_sources']),
            'missing_features':[f for f in FEATURES if f not in ('source_coverage','topology_quality') or (f=='topology_quality' and topology is None)]},
        'correction_lineage':{'original_candidate_sha256':row['candidate_sha256'],
            'review_sha256':restored['report']['content_sha256'],'corrections_sha256':restored['report']['corrections_sha256']}}
    candidate['candidate_sha256']=digest(candidate)
    queue={'version':'building-review-queue-v1','records':[{'building_id':row['building_id'],'candidate_id':candidate['id'],
        'candidate_sha256':candidate['candidate_sha256'],'features':features,'source_sha256':row['source_sha256'],
        'outcome':None,'review_basis':None,'review_scope':'New corrected local candidate; requires an independent decision. Physical placement remains unresolved.'}]}
    queue['content_sha256']=digest(queue)
    atomic_json(root/'buildings.json',{'version':'building-batch-v1','buildings':[{'building_id':row['building_id'],'candidates':[candidate]}]})
    atomic_json(root/'review-queue.json',queue)
    if benchmarks:
        atomic_json(root/'benchmark-reference.json',config)
        atomic_json(root/'benchmark-before.json',benchmarks[0]);atomic_json(root/'benchmark-after.json',benchmarks[1])
    _check(cancelled)
    # No report or successful job is published from changed review/source bytes.
    if resume_review(saved_review)!=restored:raise ValueError('Saved review inputs changed during regeneration')
    if benchmark_path and file_hash(benchmark_path)!=benchmark_pin:raise ValueError('Benchmark references changed during regeneration')
    result={'version':VERSION,'status':'corrected_local_preview_generated','building_id':row['building_id'],
        'original_candidate_sha256':row['candidate_sha256'],'corrected_candidate_sha256':candidate['candidate_sha256'],
        'operations':operations,'queue_path':str(root/'review-queue.json'),'batch_path':str(root/'buildings.json'),
        'source_paths':[session['resolved_sources'][sha]['path'] for sha in row['source_sha256'] if sha in session['resolved_sources']],
        'benchmark_path':str(root/'benchmark-reference.json') if benchmarks else None,
        'comparison_path':str(root/'geometry-comparison.svg'),'corrected_model_path':str(root/'corrected.glb'),
        'corrected_world_path':str(root/'corrected-native'/'park.mcworld') if world else None,
        'original_native':native_original,'corrected_native':native_corrected,
        'benchmark':{'status':'measured','measurement_scope':'continuous candidate geometry; native occupancy is checked separately',
            'geometry_definition':'XY triangle projection union; XYZ minimum bounds as position; height as Z span; interior extrusion holes only in the declared opening plane',
            'before':benchmarks[0]['summary'],'after':benchmarks[1]['summary'],
            'reference_sha256':config['reference_sha256'],'real_world_accuracy_established':False} if benchmarks else {'status':'awaiting_independent_reference'},
        'geometry_modified':True,'corrected_geometry_verified':False,'world_placement_eligible':False,
        'park_world_blocks_added':0,'training_labels_generated':0,'model_promoted':False,
        'limitations':['Isolated local study worlds; no geographic registration, real terrain alignment or park path/plaza connection is established.',
            'Source, identity, dimension and topology acceptance gates remain withheld for the new candidate.',
            'No original-candidate label is transferred to corrected geometry.']}
    atomic_json(root/'report.json',result);_progress(progress,1.,'Corrected preview and new independent review queue are ready')
    return result


def main(argv=None):
    import argparse
    from .desktop_runtime import read_json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',required=True,help='Existing immutable saved correction draft/review directory')
    parser.add_argument('--output',required=True,help='Fresh output directory')
    parser.add_argument('--no-world',action='store_true',help='Write models/native cells without constructing world packages')
    parser.add_argument('--benchmark',help='Frozen independently supplied reference JSON')
    parser.add_argument('--model',help='Optional evaluated model lineage for the reference overlap check')
    args=parser.parse_args(argv)
    if args.model and not args.benchmark:parser.error('--model requires --benchmark')
    result=run(args.review,args.output,world=not args.no_world,benchmark_path=args.benchmark,
        model=read_json(args.model,1000000) if args.model else None)
    print(json.dumps({'status':result['status'],'corrected_candidate_sha256':result['corrected_candidate_sha256'],
        'corrected_world_path':result['corrected_world_path'],'benchmark':result['benchmark']['status'],
        'training_labels_generated':0}))
    return 0


if __name__=='__main__':raise SystemExit(main())
