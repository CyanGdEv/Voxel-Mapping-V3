"""Plot candidate native roof surfaces and the frozen plan comparison."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['planes','site','svg']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=json.loads(Path(a.planes).read_text());site=json.loads(Path(a.site).read_text())
    import hashlib
    if hashlib.sha256(Path(a.site).read_bytes()).hexdigest()!=r['input_sha256']['review']:raise ValueError('Matched site comparison required')
    s=next(v for v in r['sweeps'] if v['vertical_residual_tolerance_m']==.12);origin=np.array([407590.,343590.])
    plt.rcParams.update({'svg.fonttype':'none','svg.hashsalt':'wicker-native-roof-planes','font.size':9})
    fig=plt.figure(figsize=(12,5.5));left=fig.add_subplot(121);right=fig.add_subplot(122,projection='3d')
    palette=plt.get_cmap('tab10')
    for i,patch in enumerate(s['patches']):
        xy=np.asarray(patch['support_geometry']['coordinates'][0]);local=xy-origin
        z=(xy-np.array(s['origin_bng_m']))@np.array(patch['slope_xy'])+patch['height_at_origin_odn_m'];colour=palette(i)
        left.fill(local[:,0],local[:,1],facecolor=colour,alpha=.35,edgecolor=colour,label=f'P{i+1} · {patch["point_count"]} returns')
        right.add_collection3d(Poly3DCollection([np.column_stack((local,z))],facecolor=colour,alpha=.6,edgecolor=colour,linewidth=.6))
    for crease in s['creases']:
        xyz=np.asarray(crease['candidate_xyz_odn_m']);colour='#111111' if crease['type']=='ridge_like' else '#777777'
        left.plot(xyz[:,0]-origin[0],xyz[:,1]-origin[1],color=colour,linewidth=1.8,linestyle='-' if crease['type']=='ridge_like' else '--')
        right.plot(xyz[:,0]-origin[0],xyz[:,1]-origin[1],xyz[:,2],color=colour,linewidth=2)
    for name in ['station','maintenance']:
        xy=np.asarray(site['frozen_hypotheses'][0]['placed_building_geometries'][name]['coordinates'][0])-origin
        left.plot(xy[:,0],xy[:,1],color='#aa1520',linestyle=':',linewidth=2,label=name.title()+' plan outline')
    left.set(aspect='equal',xlabel='Easting minus 407590 (m)',ylabel='Northing minus 343590 (m)',title='Native support patches vs frozen site outlines')
    left.grid(alpha=.2);left.legend(fontsize=7,loc='lower left')
    right.set(xlim=(-17,20),ylim=(-17,17),zlim=(183,191),xlabel='Local easting (m)',ylabel='Local northing (m)',zlabel='ODN (m)',title='Fitted patches / intersection candidates')
    right.view_init(elev=27,azim=-63)
    fig.suptitle('Shared roof component · seven native plane patches at 0.12 m residual tolerance\nConvex support surfaces and ridge candidates remain unverified',fontsize=12)
    fig.tight_layout(rect=(0,0,1,.92));fig.savefig(a.svg,metadata={'Date':None});plt.close(fig)
    path=Path(a.svg);path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')

if __name__=='__main__':main()
