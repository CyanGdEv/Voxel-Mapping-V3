"""Render frozen plan hypotheses against native building returns."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,laspy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.geometry import shape


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['review','cloud','svg']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=json.loads(Path(a.review).read_text())
    if hashlib.sha256(Path(a.cloud).read_bytes()).hexdigest()!=r['input_sha256']['cloud']:raise ValueError('Pinned comparison cloud required')
    cloud=laspy.read(a.cloud);x,y,z=np.asarray(cloud.x),np.asarray(cloud.y),np.asarray(cloud.z)
    mask=(np.asarray(cloud.classification)==6)&(~np.asarray(cloud.withheld,dtype=bool))&(~np.asarray(cloud.synthetic,dtype=bool))&(x>=407519)&(x<=407613)&(y>=343561)&(y<=343613)
    plt.rcParams.update({'svg.fonttype':'none','svg.hashsalt':'wicker-site-roofs','font.size':9})
    fig,axes=plt.subplots(1,2,figsize=(12,5.2),layout='constrained')
    colours={'shop':'#d02830','station':'#0e7fb4','maintenance':'#078552'}
    for ax,h in zip(axes,r['frozen_hypotheses']):
        ax.scatter(x[mask]-407500,y[mask]-343550,c='#777777',s=2,alpha=.35,rasterized=True,label='Native class-6 returns')
        for name,geometry in h['placed_building_geometries'].items():
            poly=shape(geometry);xy=np.array(poly.exterior.coords)
            ax.plot(xy[:,0]-407500,xy[:,1]-343550,color=colours[name],linewidth=1.5,label=name.title()+' outline')
        ax.set(xlim=(19,113),ylim=(11,63),aspect='equal',xlabel='Easting minus 407500 (m)',ylabel='Northing minus 343550 (m)',title=f'Frozen shop-fit rotation {h["rotation_degrees"]:.3f}°')
        ax.grid(alpha=.2);ax.legend(loc='lower left',fontsize=8)
    fig.suptitle('Revised SW8 site outlines vs EA 2022-01-05 returns\nStation / maintenance share one native component; no independent checkpoints',fontsize=12)
    fig.savefig(a.svg,metadata={'Date':None})
    path=Path(a.svg);path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')

if __name__=='__main__':main()
