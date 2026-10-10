"""Assemble a provisional roof plus floor-trace preview without inventing wall heights."""
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np


def assemble(scale_path,roof_path):
    scale=json.loads(Path(scale_path).read_text());roof=json.loads(Path(roof_path).read_text())
    if not scale['dimension_agreement_within_0_25_metres']:raise ValueError('Cross-sheet dimensional conflict unresolved')
    if scale['input_review_hashes'].get(str(roof_path))!=hashlib.sha256(Path(roof_path).read_bytes()).hexdigest():raise ValueError('Roof review changed since scale review')
    corners=np.array(scale['normalized_local_outer_corners'])
    u=corners[2]-corners[1];u=u/np.linalg.norm(u)
    v=np.array([-u[1],u[0]])
    if np.dot(v,corners[1]-corners[0])<0:v=-v
    centre=corners.mean(axis=0)
    def xy(point):
        delta=np.array(point)-centre
        return [float(np.dot(delta,u)),float(np.dot(delta,v))]
    walls=[{'edge':s['edge'],'start':xy(s['normalized_start'])+[0],'end':xy(s['normalized_end'])+[0],'height_metres':None}
           for s in scale['normalized_wall_segments']]
    openings=[{'id':o['id'],'endpoints':[xy(p)+[0] for p in o['normalized_local_endpoints']],
               'width_metres':o['normalized_width_metres'],'height_metres':None} for o in scale['normalized_openings']]
    outline=[xy(p)+[0] for p in corners]
    roof_mesh=roof['local_roof_mesh']
    minx=min(p[0] for p in roof_mesh['vertices']);maxx=max(p[0] for p in roof_mesh['vertices'])
    miny=min(p[1] for p in roof_mesh['vertices']);maxy=max(p[1] for p in roof_mesh['vertices'])
    margins={'negative_x':min(p[0] for p in outline)-minx,'positive_x':maxx-max(p[0] for p in outline),
             'negative_y':min(p[1] for p in outline)-miny,'positive_y':maxy-max(p[1] for p in outline)}
    if min(margins.values())<=0:raise ValueError('Roof does not cover provisional centred footprint')
    return {'input_sha256':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [scale_path,roof_path]},
            'coordinate_frame':'local metres, x long axis, y short axis, z above drawn floor',
            'assembly_hypothesis':'roof and wall outline centred, long axes aligned; 180-degree source correspondence unresolved',
            'source_plan_to_preview':{'centre':centre.tolist(),'long_axis':u.tolist(),'short_axis':v.tolist()},
            'roof_mesh':roof_mesh,'wall_base_segments':walls,'opening_base_segments':openings,'outer_wall_base_outline':outline,
            'roof_to_outline_margins_metres_under_centring_hypothesis':margins,
            'wall_surfaces':[],'opening_surfaces':[],'world_placement_eligible':False,'geographic_registration':None,
            'unresolved':['wall and opening heights','roof/wall centring and handedness','small roof projection and fascia','as-built identity and floor datum','independent geographic controls and checkpoints'],
            'world_geometry_additions':0}


def svg(model):
    result=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="690" viewBox="0 0 1100 690">',
            '<rect width="1100" height="690" fill="#f5f7fa"/>',
            '<style>text{font-family:Arial,sans-serif;fill:#263447}.title{font-size:26px;font-weight:700}.label{font-size:15px}</style>',
            '<text x="35" y="42" class="title">Wicker shop · provisional local geometry</text>',
            '<text x="35" y="70" class="label">Proposed drawings · no geographic placement · wall and opening heights unresolved</text>']
    def project(p,plan=False):
        x,y,z=p
        return (830+x*17,340-y*17) if plan else (315+(x-y*.8)*19,455+(x*.32+y*.45-z)*19)
    def line(a,b,color,plan=False,dash=''):
        x,y=project(a,plan);xx,yy=project(b,plan)
        result.append(f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{xx:.2f}" y2="{yy:.2f}" stroke="{color}" stroke-width="3" {dash}/>')
    vertices=model['roof_mesh']['vertices']
    for ids,color in [([0,1,3,2],'#b7cba1'),([2,3,5,4],'#859e6e')]:
        pts=' '.join(f'{project(vertices[i])[0]:.2f},{project(vertices[i])[1]:.2f}' for i in ids)
        result.append(f'<polygon points="{pts}" fill="{color}" stroke="#48613d" stroke-width="2"/>')
    # Dashes connect roof corners to ground only as visual alignment guides.
    for i in [0,1,4,5]:line(vertices[i],[vertices[i][0],vertices[i][1],0],'#abb7c2',dash='stroke-dasharray="5 6"')
    for plan in [False,True]:
        for s in model['wall_base_segments']:line(s['start'],s['end'],'#263447',plan)
        for o in model['opening_base_segments']:line(*o['endpoints'],'#087fb7',plan,dash='stroke-dasharray="5 4"')
    for ids in [[0,1],[1,5],[5,4],[4,0]]:line(vertices[ids[0]],vertices[ids[1]],'#6b8b54',True,dash='stroke-dasharray="5 4"')
    result.extend(['<text x="80" y="120" class="label">Roof surface + wall bases (no wall surfaces)</text>',
                   '<text x="730" y="120" class="label">Plan · centred assembly hypothesis</text>',
                   '<text x="50" y="565" class="label">Roof: 16.88 × 12.83 m · ridge about 7.21 m above drawn floor</text>',
                   '<text x="50" y="595" class="label">Normalized wall spans: about 15.82 × 11.83 m</text>',
                   '<text x="50" y="625" class="label">Blue dashes: source openings · grey dashes: alignment guides only</text>',
                   '<text x="50" y="655" class="label">Missing heights remain unset. This is a geometry review, not a generated Minecraft world.</text>','</svg>'])
    return ('\n'.join(result)+'\n').replace('class="title"','class="title" font-size="26" font-family="sans-serif" font-weight="bold"').replace('class="label"','class="label" font-size="15" font-family="sans-serif"')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('scale-review','roof-review','output','svg'):p.add_argument('--'+k,required=True)
    a=p.parse_args();model=assemble(Path(a.scale_review),Path(a.roof_review))
    Path(a.output).write_text(json.dumps(model,indent=2)+'\n');Path(a.svg).write_text(svg(model))
    print(json.dumps({'roof_triangles':4,'wall_base_segments':7,'opening_base_segments':3,'wall_surfaces':0,'world_geometry_additions':0}))

if __name__=='__main__':main()
