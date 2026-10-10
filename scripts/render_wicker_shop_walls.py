"""Render a local proposed wall/roof mesh as a deterministic SVG review."""
import argparse,json
from pathlib import Path

def render(model, reverse=False):
    def project(p):
        if reverse:p=[-p[0],-p[1],p[2]]
        return (510+(p[0]-.8*p[1])*24,450+(p[0]*.32+p[1]*.45-p[2])*24)
    panels=[(s['vertices'],'#c4a97c' if s['role']!='gable-wall' else '#b19368') for s in model['wall_surfaces']]
    v=model['roof_mesh']['vertices']
    panels += [([v[i] for i in ids],color) for ids,color in [([0,1,3,2],'#b7cba1'),([2,3,5,4],'#859e6e')]]
    panels += [(s['vertices'],'#a1b98c' if s['role']=='canopy-roof' else '#71865f') for s in model.get('projection_surfaces',[])]
    sign=-1 if reverse else 1
    panels.sort(key=lambda row:sum(sign*(.8*p[0]+p[1])+.706*p[2] for p in row[0])/len(row[0]))
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="720" viewBox="0 0 1050 720">','<rect width="1050" height="720" fill="#f5f7fa"/>']
    def text(x,y,value,size=16):svg.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="#263447">{value}</text>')
    text(35,45,'Wicker shop · proposed wall and roof surfaces',25)
    text(35,78,'Local assembly hypothesis · opening heights traced from elevations · no park registration')
    for points,color in panels:
        coords=' '.join(f'{project(p)[0]:.2f},{project(p)[1]:.2f}' for p in points)
        svg.append(f'<polygon points="{coords}" fill="{color}" stroke="#574f40" stroke-width="1.3"/>')
    text(35,620,'12 wall panels · 22 wall triangles · 4 roof triangles · 4 canopy/fascia triangles' if model.get('projection_surfaces') else '12 wall panels · 22 wall triangles · 4 main roof triangles')
    text(35,650,'Shoulder about 3.3 m · gable apex about 6.9 m · broad openings about 2.5 m high')
    text(35,680,'Canopy is a source-height hypothesis; cross-view discrepancy retained. No park/world placement.' if model.get('projection_surfaces') else 'Wall thickness, fascia and roof projection remain unresolved. Proposed geometry; not as-built.')
    svg.append('</svg>');return '\n'.join(svg)+'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',required=True);p.add_argument('--output',required=True);p.add_argument('--reverse',action='store_true');a=p.parse_args()
    Path(a.output).write_text(render(json.loads(Path(a.model).read_text()),a.reverse))

if __name__=='__main__':main()
