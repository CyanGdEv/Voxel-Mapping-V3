"""Plot separate proposed roof/wall extents and frozen native supports."""
import argparse, json, hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['review', 'planes', 'site', 'svg']: p.add_argument('--'+name, required=True)
    a = p.parse_args(); r = json.loads(Path(a.review).read_text())
    planes = json.loads(Path(a.planes).read_text()); site = json.loads(Path(a.site).read_text())
    if hashlib.sha256(Path(a.site).read_bytes()).hexdigest() != planes['input_sha256']['review']:
        raise ValueError('Matched native plane and site reviews required')
    hypotheses = r['shop_only_drawing_correspondence_hypotheses']
    # This selects the drawing arrangement, not a fit against native cloud observations.
    h = min(hypotheses, key=lambda x: x['plan_correspondence_checks']['station']['roof_vs_site_inner']['centroid_separation_metres'])
    primary = next(s for s in planes['sweeps'] if s['vertical_residual_tolerance_m'] == .12)
    plt.rcParams.update({'svg.fonttype':'none', 'svg.hashsalt':'wicker-architectural-outlines', 'font.size':9})
    fig, axes = plt.subplots(1, 2, figsize=(13, 6)); left, right = axes
    styles = [('6ede3a', 'maintenance_main_roof', '#0c6c7a', 'Roof plan'),
              ('457947', 'maintenance_outer_walls', '#9b4275', 'Dedicated wall plan'),
              ('08afa2', 'maintenance_outer_walls', '#cc8f16', 'Normalized overall wall plan')]
    for prefix, role, colour, label in styles:
        row = next(v for v in r['measurements'] if v['source_sha256'].startswith(prefix) and v['role'] == role)
        length, width = row['opposite_edge_mean_dimensions_metres']
        left.add_patch(Rectangle((-length/2, -width/2), length, width, fill=False,
                                edgecolor=colour, linewidth=2, linestyle='--' if prefix == '08afa2' else '-',
                                label=f'{label}: {length:.2f} × {width:.2f} m'))
    left.set(xlim=(-13, 13), ylim=(-8, 8), aspect='equal', xlabel='Centered long dimension (m)', ylabel='Centered transverse dimension (m)',
             title='Maintenance roof and wall dimensions\nCentered for size comparison; not registered positions')
    left.legend(loc='lower center', fontsize=8); left.grid(alpha=.2)
    origin = np.array([407590., 343590.])
    for i, patch in enumerate(primary['patches']):
        xy = np.asarray(patch['support_geometry']['coordinates'][0])-origin
        right.fill(xy[:,0], xy[:,1], color=plt.get_cmap('tab10')(i), alpha=.25)
        centre = xy[:-1].mean(axis=0); right.text(*centre, f'P{i+1}', fontsize=8)
    for name, colour, label in [('maintenance_main_roof', '#0c6c7a', 'Architectural maintenance roof'),
                                ('communications_roof', '#e88200', 'Architectural communications roof'),
                                ('station_main_roof', '#7733aa', 'Architectural station roof')]:
        xy = np.asarray(h['native_geometries'][name]['coordinates'][0])-origin
        right.plot(xy[:,0], xy[:,1], color=colour, linewidth=2, label=label)
    xy = np.asarray(site['frozen_hypotheses'][0]['placed_building_geometries']['maintenance']['coordinates'][0])-origin
    right.plot(xy[:,0], xy[:,1], color='#555555', linestyle=':', linewidth=2, label='Previously selected inner outline')
    right.set(aspect='equal', xlabel='Easting minus 407590 (m)', ylabel='Northing minus 343590 (m)',
              title='Frozen shop placement; no additional building fit\nNative support polygons are not surveyed eaves')
    right.legend(loc='lower right', fontsize=7); right.grid(alpha=.2)
    fig.suptitle('Wicker test · separate roof, wall and communications outlines\nProposed drawing geometry; world placement remains blocked', fontsize=13)
    fig.tight_layout(rect=(0,0,1,.92)); fig.savefig(a.svg, metadata={'Date':None}); plt.close(fig)
    path = Path(a.svg); path.write_text('\n'.join(v.rstrip() for v in path.read_text().splitlines())+'\n')


if __name__ == '__main__': main()
