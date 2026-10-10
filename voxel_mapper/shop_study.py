"""Isolated surface-voxel study; never accepted park reconstruction."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from shapely.geometry import Point, Polygon

VERSION='shop-local-surface-study-v1'


def raster_mesh(mesh, scale):
    if scale not in (1,4) or isinstance(scale,bool):raise ValueError('Study scale must be 1 or 4')
    vertices=np.asarray(mesh['vertices'],dtype=float)*scale
    triangles=mesh['triangles']
    if vertices.ndim!=2 or vertices.shape[1]!=3 or len(vertices)>500 or len(triangles)>500 or not np.isfinite(vertices).all() or np.max(np.abs(vertices))>200:
        raise ValueError('Bounded finite study mesh required')
    cells=set();per_triangle=[];probes=0
    for indices in triangles:
        if len(indices)!=3 or any(type(i) is not int or not 0<=i<len(vertices) for i in indices):raise ValueError('Valid triangle indices required')
        pts=vertices[indices];normal=np.cross(pts[1]-pts[0],pts[2]-pts[0])
        if np.linalg.norm(normal)<1e-9:raise ValueError('Degenerate study triangle')
        axis=int(np.argmax(np.abs(normal)));other=[i for i in range(3) if i!=axis]
        polygon=Polygon(pts[:,other]);bounds=polygon.bounds;count=0
        for a in range(math.floor(bounds[0]),math.ceil(bounds[2])):
            for b in range(math.floor(bounds[1]),math.ceil(bounds[3])):
                probes+=1
                if probes>200000:raise ValueError('Study surface raster budget exceeded')
                sample=np.zeros(3);sample[other]=[a+.5,b+.5]
                if not polygon.covers(Point(sample[other])):continue
                sample[axis]=pts[0,axis]-sum(normal[j]*(sample[j]-pts[0,j]) for j in other)/normal[axis]
                cell=tuple(math.floor(v) for v in sample)
                cells.add((cell[0],cell[2],cell[1]));count+=1
        per_triangle.append(count)
    return cells,{'per_triangle_surface_samples':per_triangle,'projection_sample_probes':probes,
                  'triangles_without_centroid_sample':sum(n==0 for n in per_triangle)}


def join_wall_columns(wall, roof, scale):
    """Estimated vertical closure of existing wall columns, bounded to one metre.

    Uses the main roof only. Never extends below an existing wall top, so doors
    and other holes below it remain untouched. Refuses missing/remote roofs.
    """
    tops={};roof_bottom={}
    for x,y,z in wall:tops[x,z]=max(tops.get((x,z),y),y)
    for x,y,z in roof:roof_bottom[x,z]=min(roof_bottom.get((x,z),y),y)
    added=set();columns=[]
    for (x,z),top in sorted(tops.items()):
        bottom=roof_bottom.get((x,z))
        if bottom is None or bottom<top or bottom-top-1>scale:
            raise ValueError('Wall column lacks a bounded overhead main roof')
        missing=[(x,y,z) for y in range(top+1,bottom)]
        added.update(missing)
        columns.append({'local_xz':[x,z],'wall_top':top,'roof_bottom':bottom,'added_levels':[p[1] for p in missing]})
    return added,{'rule':'vertical closure above existing wall tops to main-roof underside; at most one source metre',
                  'status':'estimated display join, not measured construction','added_cells':len(added),
                  'columns':columns,'all_columns_connected':True}


def plan(model_path, expected_sha256, scale=1, joined=False, closed=False):
    path=Path(model_path);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('Pinned study model checksum mismatch')
    model=json.loads(raw)
    if model['geographic_registration'] is not None or model['world_placement_eligible']:
        raise ValueError('Only isolated unplaced shop models supported')
    wall,wall_audit=raster_mesh(model['wall_mesh'],scale)
    roof,roof_audit=raster_mesh(model['roof_mesh'],scale)
    closure_audit=None
    if closed:
        if not joined:raise ValueError('Closed review requires joined mode')
        from .shop_shell import close_shell
        wall,roof,closure_audit=close_shell(model,wall,roof,scale)
    joins=set();join_audit=None;projection=set();projection_audit=None
    if joined:
        if not closed:joins,join_audit=join_wall_columns(wall,roof,scale)
        if 'projection_mesh' in model:
            projection,projection_audit=raster_mesh(model['projection_mesh'],scale)
    # Roof wins aliasing intersections in the display study, with every conflict counted.
    cells={p:'spruce_planks' for p in wall|joins};cells.update({p:'dark_oak_planks' for p in roof|projection})
    rows=[{'x':x,'y':y,'z':z,'kind':'study_surface','material':material,'feature':'shop-local-study','source':'reviewed-proposed-model'}
          for (x,y,z),material in sorted(cells.items())]
    radius=12*scale
    ground=[{'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'} for x in range(-radius,radius) for z in range(-radius,radius)]
    openings=[]
    for opening in model['opening_base_segments']:
        a,b=opening['endpoints'];x=math.floor((a[0]+b[0])/2*scale);z=math.floor((a[1]+b[1])/2*scale)
        levels=list(range(math.floor(opening['height_metres']*scale)))
        openings.append({'id':opening['id'],'sample_column_local_xz':[x,z],
                         'sampled_levels':levels,'all_centre_samples_air':all((x,y,z) not in cells for y in levels),
                         'full_width_clearance_verified':False,'player_movement_verified':False})
    report={'version':VERSION,'voxel_size_m':1,'model_blocks_per_source_metre':scale,'crs':None,
            'vertical_datum':'STUDY_ZERO','geographic_placement':'withheld','park_world_blocks_added':0,
            'model_sha256':expected_sha256,'source_assembly_hypothesis':model['assembly_hypothesis'],
            'source_unresolved':model['unresolved'],'model_watertight':model['wall_mesh']['watertight'],
            'wall_thickness_metres':None,'wall_cells':len(wall),'roof_cells':len(roof),
            'wall_roof_alias_cells':len(wall&roof),'surface_cells':len(cells),'platform_cells':len(ground),
            'wall_sampling':wall_audit,'roof_sampling':roof_audit,'spawn_local_xyz_m':[0,2,-10*scale],
            'opening_centre_sample_audit':openings,
            'surface_raster_rule':'dominant-axis triangle projection; source plane at projected cell centres; one-block display surfaces',
            'display_palette_only':{'walls':'spruce_planks','roof':'dark_oak_planks'},
            'sources':[{'id':'reviewed-proposed-model','url':'local://wicker-shop-wall-model','license':'source-linked proposed drawing study',
                        'attribution':'2967-21/26/48; local manual traces and provisional sheet-layout normalization'}],
            'limitations':['Isolated proposed-drawing study, not a placed or as-built park building.',
                'Roof/wall centring and 180-degree correspondence remain assembly hypotheses.',
                'Northwest opening uses the retained manual 0.901 m normalized span; recovered 1.011 m cap span remains unresolved.',
                'One-block display surfaces do not establish physical wall or roof thickness. Fine details alias at 1:1.',
                'Palette is illustrative; fascia, canopy, cladding/bunding, interior and construction joints are omitted.',
                'This surface model is not watertight; no shell-completeness or in-game movement claim is made.',
                'The 4:1 world, when requested, is four blocks per source metre; geographic use is forbidden.']}
    report['review_mode']='joined-canopy-hypothesis' if joined else 'source-surfaces'
    report['estimated_join_audit']=join_audit
    report['projection_cells']=len(projection)
    report['projection_sampling']=projection_audit
    report['boundary_closure_audit']=closure_audit
    if joined:
        report['version']='shop-local-joined-study-v2'
        report['projection_review']=model.get('projection_review')
        report['limitations']=[s for s in report['limitations'] if 'fascia, canopy' not in s]
        report['limitations'].append('Estimated wall-to-roof joins close sampled columns only; construction thickness and full shell completeness remain unresolved.')
        report['limitations'].append('Canopy/front fascia use the retained NE-height hypothesis; side fascia and cross-view height discrepancy remain unresolved.')
    if closed:
        report['version']='shop-local-boundary-review-v3'
        report['review_mode']='closed-boundary-canopy-hypothesis'
        report['limitations'].append('Boundary and roof-riser closure is an estimated voxel display; six-neighbour air closure does not establish real construction thickness or water tightness.')
    return ground+rows,report


def run(model_path, expected_sha256, output, scale=1, joined=False, closed=False):
    from .bedrock import export_world
    output=Path(output)
    if output.exists():raise ValueError('Use a new study output directory')
    rows,report=plan(model_path,expected_sha256,scale,joined,closed);output.mkdir(parents=True)
    path=output/'voxels.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    label='JOINED REVIEW' if joined else 'LOCAL STUDY'
    if closed:label='BOUNDARY V3 REVIEW'
    report['world']=export_world(path,output,report,name=f'Wicker Shop {label} {scale}:1',ground_depth=4)
    (output/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
