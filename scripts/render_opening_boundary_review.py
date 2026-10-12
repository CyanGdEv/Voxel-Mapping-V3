"""Render source linework in a local facade plane beside unresolved trace support."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import proj3d
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.affinity import affine_transform
from shapely.geometry import shape


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['review','inventory','model','output','obj']:p.add_argument('--'+key,required=True,type=Path)
    a=p.parse_args();r=json.loads(a.review.read_text());raw=a.inventory.read_bytes();i=json.loads(raw);model=json.loads(a.model.read_text())
    if hashlib.sha256(raw).hexdigest()!=r['inventory_sha256'] or model['source_pdf_sha256']['elevation']!=r['document_sha256']:
        raise ValueError('Matching source-pinned model and inventory required')
    m=i['native_to_pixel_matrix'];transform=[m[0],m[2],m[1],m[3],m[4],m[5]]
    x0,y0=model['reviewed_traces']['elevation']['baseline_endpoints'][0];unit=i['metres_per_pixel_nominal']
    rows=r['comparison']['rows'];sources={s['id']:s for s in r['source_candidates']}
    ids=sorted({s['source_candidate_id'] for row in rows for s in row['trace_proximity_review']['original_source_lines']} |
               {e['source_candidate_id'] for row in rows for gap in row['endpoint_gap_candidates'] for e in gap['endpoints']})
    projected=[];obj=['# Original source lines projected onto reviewed facade plane; metre units; no park pose',
                     '# This layer is drawing geometry, not newly accepted physical apertures.'];offset=1
    for key in ids:
        source=sources[key]
        if source['geometry']['type']!='LineString':continue
        pixels=list(affine_transform(shape(source['geometry']),transform).coords)
        vertices=[((x-x0)*unit,0,(y0-y)*unit) for x,y in pixels]
        projected.append((key,pixels,vertices));obj.append('o source_'+key)
        obj.extend('v '+' '.join(map(str,v)) for v in vertices)
        obj.append('l '+' '.join(str(n) for n in range(offset,offset+len(vertices))));offset+=len(vertices)
    a.obj.write_text('\n'.join(obj)+'\n')
    fig=plt.figure(figsize=(16,10),dpi=300,facecolor='#0b1420');ax=fig.add_axes([.025,.37,.95,.48],projection='3d',computed_zorder=False)
    ax.set_facecolor('#0b1420');ax.set_proj_type('ortho');ax.view_init(elev=19,azim=-67)
    for key,color in [('wall_mesh','#c4b99b'),('roof_mesh','#536b80')]:
        mesh=model[key];ax.add_collection3d(Poly3DCollection([[mesh['vertices'][v] for v in t] for t in mesh['triangles']],facecolors=color,linewidths=0,shade=True,zorder=2),autolim=False)
    for key,pixels,vertices in projected:
        ax.plot([v[0] for v in vertices],[-.04]*len(vertices),[v[2] for v in vertices],color='#56d9e8',lw=.65,zorder=4)
    length=model['width_check']['elevation_length_m'];measure=model['measurements']
    ax.set_xlim(-1,length+1);ax.set_ylim(-1,measure['depth_m']+1);ax.set_zlim(-.2,measure['ridge_m']+1)
    ax.set_box_aspect((length,measure['depth_m']+2,measure['ridge_m']+1),zoom=1.05);ax.set_axis_off()
    # Crop the rendered 3D panel to its projected geometry before laying out the report.
    # Coordinates and camera stay unchanged; the full facade remains visible.
    fig.canvas.draw();pixels=np.asarray(fig.canvas.buffer_rgba()).copy()
    vertices=[v for key in ('wall_mesh','roof_mesh') for v in model[key]['vertices']]
    vertices.extend(v for _,_,points in projected for v in points)
    screen=[ax.transData.transform(proj3d.proj_transform(*v,ax.get_proj())[:2]) for v in vertices]
    sx=np.array(screen);height,width=pixels.shape[:2]
    left=max(0,int(sx[:,0].min())-12);right=min(width,int(sx[:,0].max())+12)
    top=max(0,height-int(sx[:,1].max())-12);bottom=min(height,height-int(sx[:,1].min())+12)
    cropped=pixels[top:bottom,left:right];ax.remove()
    panel=fig.add_axes([.05,.36,.90,.48]);panel.imshow(cropped);panel.set_axis_off()
    detail=fig.add_axes([.08,.11,.48,.23],facecolor='#0b1420');arch=next(row for row in rows if row['seed_id']=='archway-3')
    source_ids={s['source_candidate_id'] for s in arch['trace_proximity_review']['original_source_lines']} | {e['source_candidate_id'] for gap in arch['endpoint_gap_candidates'] for e in gap['endpoints']}
    for key,pixels,_ in projected:
        if key in source_ids:detail.plot([p[0] for p in pixels],[p[1] for p in pixels],color='#56d9e8',lw=1)
    unsupported=shape(arch['trace_proximity_review']['unsupported_reviewed_trace'])
    parts=list(unsupported.geoms) if hasattr(unsupported,'geoms') else [unsupported]
    for part in parts:
        if not part.is_empty:detail.plot(*part.xy,color='#fc8a8a',lw=2)
    for gap in arch['endpoint_gap_candidates']:
        points=[e['pixel_point'] for e in gap['endpoints']];detail.scatter([p[0] for p in points],[p[1] for p in points],s=24,facecolor='none',edgecolor='#ffd17d')
    detail.set_xlim(735,920);detail.set_ylim(420,275);detail.set_aspect('equal');detail.set_axis_off()
    fig.text(.05,.94,'MUTINY BAY · SOURCE BOUNDARY REVIEW',color='#a6b9cf',fontsize=12,weight='bold')
    fig.text(.05,.885,'3D source linework over the partial study',color='#eef5fc',fontsize=24,weight='bold')
    fig.text(.60,.29,'Archway 3: closure remains unresolved',color='#eef5fc',fontsize=14,weight='bold')
    fig.text(.60,.24,f"{arch['trace_proximity_review']['near_source_fraction']:.1%} of the reviewed perimeter lies\nwithin two pixels of retained straight source linework.",color='#a6b9cf',fontsize=12)
    fig.text(.60,.17,'Cyan: original source lines\nRed: unsupported reviewed trace\nAmber circles: nearby unjoined source endpoints',color='#d2dfed',fontsize=11)
    fig.text(.05,.065,'Existing wall/roof meshes unchanged. Corrected window IDs. Source lines are a separate local review layer.',color='#d2dfed',fontsize=11)
    fig.text(.05,.028,'Reviewed view and floor zero · provisional roof assembly · no new physical apertures or park placement',color='#94a9c2',fontsize=10)
    fig.savefig(a.output,dpi=160,facecolor=fig.get_facecolor());plt.close(fig)


if __name__=='__main__':main()
