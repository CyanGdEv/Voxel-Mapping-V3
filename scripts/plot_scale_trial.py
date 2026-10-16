"""Plot verified native top surfaces and the retained scale-run measurements.

Requires matplotlib as a separate plotting dependency; generation does not.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, to_rgb
from matplotlib.patches import Patch, Rectangle
import numpy as np

from voxel_mapper.generation_cycles import file_hash


def plot(trial, measurements, output):
    trial=Path(trial);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    checked=json.loads((trial/'cold-validation.json').read_text())
    if checked['status']!='passed':raise ValueError('Cold native validation is required')
    for name,digest in checked['native_preview_arrays_sha256'].items():
        if file_hash(trial/name)!=digest:raise ValueError('Verified native preview changed')
    compiled=json.loads((trial/'prepared/compile-report.json').read_text())
    materials=compiled['materials'];top=np.load(trial/'native-top-material.npy')
    heights=np.load(trial/'native-top-height.npy');half=top.shape[0]//2
    colors={'air':'#ffffff','black_concrete':'#41464c','coarse_dirt':'#a38b69',
            'cobblestone':'#a1a29b','dirt':'#9e7b52','grass_block':'#8ea778',
            'gravel':'#c5bca5','iron_block':'#dae0df','oak_planks':'#b59563',
            'stone':'#aeb5ad','stone_bricks':'#747d89'}
    rgb=np.array([to_rgb(colors.get(name,'#bd9fb9')) for name in materials])[top]
    shade=LightSource(azdeg=315,altdeg=40).hillshade(heights,vert_exag=1,dx=1,dy=1)
    rgb=np.clip(rgb*(0.65+0.4*shade[...,None]),0,1)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'figure.facecolor':'#fafaf7'})
    fig,axes=plt.subplots(1,3,figsize=(15,6.4))
    for ax,side in zip(axes,compiled['stages_chunks_per_side']):
        span=side*8;crop=rgb[half-span:half+span,half-span:half+span]
        ax.imshow(crop,extent=[-span,span,-span,span],origin='upper',interpolation='nearest')
        ax.plot(0,0,'*',color='#f7cb52',markersize=10,markeredgecolor='#514a29',markeredgewidth=0.6)
        for previous in compiled['stages_chunks_per_side']:
            if previous<side:
                radius=previous*8
                ax.add_patch(Rectangle((-radius,-radius),2*radius,2*radius,fill=False,
                                       edgecolor='#fff7df',linewidth=1.3,linestyle='--'))
                ax.text(-radius+8,radius-16,f'{previous} × {previous}',color='white',fontsize=8,
                        va='top',bbox={'facecolor':'#34423a','alpha':0.8,'pad':2,'edgecolor':'none'})
        bar=100 if side==32 else 200
        x,y=-span+span*0.1,-span+span*0.12
        ax.plot([x,x+bar],[y,y],color='#26342c',lw=4)
        ax.text(x+bar/2,y+span*0.05,f'{bar} m',ha='center',fontsize=9,color='#26342c')
        ax.text(span*0.88,span*0.87,'N ↑',ha='center',color='#26342c',fontweight='bold')
        ax.set_title(f'{side} × {side} chunks\n{side*16:,} × {side*16:,} metres',fontsize=12,pad=12)
        ax.set_xlabel('East offset (m)');ax.set_ylabel('North offset (m)')
    fig.suptitle('Forbidden Valley • saved Bedrock geometry at three scales',fontsize=17,x=0.5,y=0.96)
    fig.legend(handles=[Patch(color=colors['grass_block'],label='Terrain'),
                        Patch(color=colors['black_concrete'],label='Mapped paving (mixed materials)'),
                        Patch(color=colors['stone_bricks'],label='Solid building profiles'),
                        Patch(color='#f7cb52',label='Forbidden Valley anchor / spawn vicinity')],
               loc='lower center',bbox_to_anchor=(0.5,0.11),ncol=4,frameon=False,fontsize=9)
    fig.text(0.5,0.055,'Native block readback with elevation shading; this is a plan view, not a Minecraft screenshot.',ha='center',fontsize=9)
    fig.text(0.5,0.023,'© OpenStreetMap contributors (2026 snapshot) • Environment Agency LiDAR (2022) • Ride tracks, water and unsupported geometry withheld.',ha='center',fontsize=8,color='#555d54')
    fig.subplots_adjust(left=0.055,right=0.985,top=0.81,bottom=0.24,wspace=0.28)
    fig.savefig(output/'native-scale-overview.png',dpi=160);plt.close(fig)

    measured=json.loads(Path(measurements).read_text());stages=list(measured['stages'].values())
    positions=np.arange(len(stages));width=0.34
    fig,axes=plt.subplots(1,2,figsize=(10,5.2))
    for ax,field,title,unit in [(axes[0],'peak_process_rss_mib','Peak process memory','MiB'),
                                (axes[1],'export_seconds','Native export and verification time','Seconds')]:
        for offset,prefix,color,label in [(-width/2,'baseline','#b77b6c','First trial: 64-chunk checkpoints'),
                                          (width/2,'final','#3b7c90','Final: 1,024-chunk checkpoints')]:
            values=[s[prefix+'_'+field] for s in stages]
            bars=ax.bar(positions+offset,values,width,color=color,label=label)
            ax.bar_label(bars,labels=[f'{v:,.0f}' if unit=='MiB' else f'{v:.1f}' for v in values],padding=3,fontsize=9)
        ax.set_xticks(positions,[str(int(s['chunks']**0.5))+' × '+str(int(s['chunks']**0.5)) for s in stages])
        ax.set_xlabel('Chunks per side');ax.set_ylabel(unit);ax.set_title(title,fontsize=12,pad=14)
        ax.set_ylim(0,ax.get_ylim()[1]*1.13);ax.grid(axis='y',alpha=0.2);ax.set_axisbelow(True)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(0.5,0.14),ncol=2,frameon=False,fontsize=9)
    fig.suptitle('Forbidden Valley scale trial • observed resource use',fontsize=16,y=0.97)
    fig.text(0.5,0.08,'Same geometry in all 15,120 before/after chunk comparisons. One run per size; no large-scale extrapolation.',ha='center',fontsize=8)
    fig.text(0.5,0.035,'32 × 32 includes the 128-chunk checkpoint and resumed export. Shared preparation (16.0 s) and source download excluded.',ha='center',fontsize=8,color='#555d54')
    fig.subplots_adjust(left=0.08,right=0.98,top=0.8,bottom=0.3,wspace=0.28)
    fig.savefig(output/'resource-comparison.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',type=Path,required=True)
    parser.add_argument('--measurements',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();plot(args.trial,args.measurements,args.output)
