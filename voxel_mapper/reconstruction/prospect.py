"""A relative Prospect Tower study; no geographic placement or terrain alteration."""
import argparse,json,math
from pathlib import Path
from shapely.geometry import Point,Polygon,box,shape,mapping
from shapely.ops import unary_union
from shapely.affinity import scale as scale_geometry
from .model import Source,Feature
from .sources import evidence
from .engine import Context,ReconstructionEngine
from .generators import default_registry

DATA=Path(__file__).resolve().parents[1]/'data'


def components(model_scale=1):
    if isinstance(model_scale,bool) or model_scale not in (1,4):raise ValueError('Study scale must be 1 or 4 blocks per source metre')
    ground=json.loads((DATA/'prospect-ground-profiles.json').read_text())
    upper=json.loads((DATA/'prospect-upper-profiles.json').read_text())
    levels=json.loads((DATA/'prospect-elevation-review.json').read_text())
    heights={r['name']:r['height_above_reference_m'] for r in levels['relative_levels']}
    storeys=[ground['components'],upper['storeys'][0]['components'],upper['storeys'][1]['components']]
    ranges=[(0,heights['first_balcony_underside']), (heights['first_balcony_top'],heights['second_balcony_top']-.28), (heights['second_balcony_top'],heights['roof_column_top'])]
    parts=[]
    def add(identifier,geom,bottom,top,material,priority=0,rule='overlap',status='estimated',note=''):
        parts.append({'id':identifier,'geometry_source':'study-profiles','geometry':mapping(scale_geometry(geom,xfact=model_scale,yfact=model_scale,origin=(0,0))),
            'parameters':{k:evidence(v,'study-profiles',status) for k,v in {'bottom_m':bottom*model_scale,'top_m':top*model_scale,'material':material}.items()} |
                {k:evidence(v,'study-proxies') for k,v in {'voxel_priority':priority,'raster_rule':rule}.items()},
            'review_note':note})
    columns=[]
    for floor,(members,(bottom,top)) in enumerate(zip(storeys,ranges)):
        for p in members:
            geom=shape(p['geometry']);outer=geom.centroid.distance(Point(0,0))>1.25
            if outer:
                if floor==0:columns.append(geom)
                material='sandstone_wall' if model_scale==1 else 'sandstone'
                add(f'floor-{floor}/{p["id"]}',geom,bottom,top,material,20,'centroid',note='Measured member footprint; vertical interval uses reviewed balcony levels; wall block is a thin-column proxy')
            else:
                add(f'floor-{floor}/{p["id"]}',geom,bottom,top,'red_terracotta',10,note='Stair enclosure/member proxy; openings and carved profiles incomplete')
    # Pair the closely spaced external columns at the eight plan corners.
    ordered=sorted((g.centroid for g in columns),key=lambda q:math.atan2(q.y,q.x))
    corners=[Point((ordered[i].x+ordered[i+1].x)/2,(ordered[i].y+ordered[i+1].y)/2) for i in range(0,16,2)]
    for floor,top in enumerate((heights['first_balcony_underside'],heights['second_balcony_top']-.28)):
        for side,(a,b) in enumerate(zip(corners,corners[1:]+corners[:1])):
            for j in range(12):
                t0=j/12;t1=(j+1)/12;t=(t0+t1)/2
                x0=a.x+(b.x-a.x)*t0;z0=a.y+(b.y-a.y)*t0
                x1=a.x+(b.x-a.x)*t1;z1=a.y+(b.y-a.y)*t1
                from shapely.geometry import LineString
                profile=LineString([(x0,z0),(x1,z1)]).buffer(.09,cap_style=2)
                arch_y=top-.70+.70*math.sqrt(max(0,1-abs(2*t-1)))
                add(f'arch-{floor}-{side}-{j}',profile,arch_y-.12,arch_y+.08,'sandstone',25,note='Pointed arch proxy between plan column pairs; carved tracery omitted')
    outer=unary_union(columns).convex_hull.buffer(.12,join_style=2)
    # Platform remains an annulus around the actual stair opening.
    void=Point(0,0).buffer(.77,quad_segs=8)
    platform=outer.difference(void)
    add('ground-platform',platform,-.25,0,'sandstone',40,note='Envelope inferred from member extent, not a traced paving outline')
    for number,key in enumerate(('first_balcony_top','second_balcony_top'),1):
        top=heights[key];add(f'balcony-{number}',platform,top-.28,top,'sandstone_slab_top' if model_scale==1 else 'sandstone',40)
        railing=outer.difference(outer.buffer(-.10,join_style=2))
        add(f'railing-{number}',railing,top,top+1.0,'green_stained_glass_pane',15,note='Proposed Grass Green cast-iron railing represented by green panes; profile and height are proxies')
    # Numbered plan steps establish a spiral; tread geometry remains a proxy.
    for i in range(44):
        angle=math.radians(0+i*360/15);next_angle=angle+math.radians(360/15)
        wedge=Polygon([(0,0),(.77*math.cos(angle),.77*math.sin(angle)),(.77*math.cos(next_angle),.77*math.sin(next_angle))])
        top=(i+1)*heights['second_balcony_top']/44
        add(f'spiral-step-{i+1}',wedge,max(0,top-.16),top,'stone_slab' if model_scale==1 else 'stone',30)
    # Eight roof facets follow reviewed octagonal plan topology. Intermediate
    # radius samples approximate the drawn curve, not a surveyed roof mesh.
    roof=[(heights['roof_column_top'],1.32),(9.25,1.19),(9.70,.82),(10.15,.43),(10.55,.20),(heights['roof_cap_upper_edge'],.15)]
    for k,((y0,r0),(y1,r1)) in enumerate(zip(roof,roof[1:])):
        steps=max(1,math.ceil((y1-y0)/.1))
        for j in range(steps):
            a=y0+(y1-y0)*j/steps;b=y0+(y1-y0)*(j+1)/steps;r=r0+(r1-r0)*(j+.5)/steps
            octagon=Polygon([(r*math.cos(math.pi/8+i*math.pi/4),r*math.sin(math.pi/8+i*math.pi/4)) for i in range(8)])
            shell=octagon.difference(octagon.buffer(-.10,join_style=2))
            add(f'roof-{k}-{j}',shell,a,b,'iron_bars' if b<9.7 else 'stone',50 if b<9.7 else 51,note='Faceted radial approximation; detailed cast-iron tracery not reproduced')
    add('finial-proxy',Point(0,0).buffer(.13,quad_segs=4),heights['roof_cap_upper_edge'],11.12,'sandstone_wall' if model_scale==1 else 'sandstone',60,'centroid' if model_scale==1 else 'overlap')
    return parts


def plan(model_scale=1):
    parts=components(model_scale)
    sources={'study-profiles':Source('study-profiles','relative_drawing_profile','https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/ApplicationSearchServlet?PKID=71254','unconfirmed-drawing-reuse','LOCAL_METRIC_STUDY','STUDY_ZERO','accepted',metadata={'registration_scope':'local paper profiles only; geographic placement withheld'}),
             'study-proxies':Source('study-proxies','study_design','local://prospect-study','project','LOCAL_METRIC_STUDY','STUDY_ZERO','accepted')}
    feature=Feature('prospect-study','architectural_components',mapping(Point(.5,.5)),'study-profiles',
        {k:evidence(v,'study-proxies') for k,v in {'base_elevation_m':0,'rotation_degrees':0,'components':parts}.items()},
        {'geographic_placement':'withheld','purpose':'relative geometry review only','model_blocks_per_source_metre':model_scale})
    rows,report=ReconstructionEngine(default_registry()).plan([feature],Context(sources,lambda x,z:-1,box(-32,-32,32,32),'STUDY_ZERO',True))
    if not rows:raise ValueError('Study reconstruction withheld: '+str(report['decisions']))
    report.update(voxel_size_m=1,crs=None,vertical_datum='STUDY_ZERO',sources=[s.__dict__ for s in sources.values()],
        model_blocks_per_source_metre=model_scale,physical_height_reference_m=11.12,
        component_count=len(parts),geographic_placement='withheld',park_world_blocks_added=0,
        limitations=['Relative review model, not positioned in Alton Towers.', 'Printed scale is not independent survey verification.',
                    'Proposed 2014 colours are not verified current condition.', 'Block palette, balcony envelope, railings, stair treads and roof radii are proxies.',
                    'Openings, carved arches, glazing and roof tracery are incomplete.', 'Native one-metre blocks merge some fine members; enlarged study is explicitly 4:1.'])
    return rows,report,parts


def run(output,model_scale=1):
    from ..bedrock import export_world
    output=Path(output)
    if output.exists():raise ValueError('Use new output directory')
    rows,report,parts=plan(model_scale);output.mkdir(parents=True)
    compact=[{k:r[k] for k in ('x','y','z','kind','material','feature','source')} for r in rows]
    ground=[{'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'} for x in range(-16,16) for z in range(-16,16)]
    path=output/'voxels.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in ground+compact))
    (output/'components.json').write_text(json.dumps(parts,indent=2)+'\n')
    report['spawn_local_xyz_m']=[0,2,-12]
    report['world']=export_world(path,output,report,name=f'Prospect Tower STUDY {model_scale}:1',ground_depth=4)
    (output/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--model-scale',type=int,choices=(1,4),default=1);a=p.parse_args()
    print(json.dumps(run(a.output,a.model_scale)['world']))

if __name__=='__main__':main()
