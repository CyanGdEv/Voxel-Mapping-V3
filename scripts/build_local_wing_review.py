"""Build a pinned local 3D review; optional isolated Bedrock study, never park placement."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.local_wing_review import run


def export_obj(model, target):
    lines=['# Local survey review: X frontage / Y depth / Z height; metres; no park pose']
    offset=0
    for key in ['wall_mesh','roof_mesh']:
        mesh=model[key];lines.append('o '+key)
        lines.extend('v '+' '.join(map(str,v)) for v in mesh['vertices'])
        lines.extend('f '+' '.join(str(i+offset+1) for i in face) for face in mesh['triangles'])
        offset+=len(mesh['vertices'])
    target.write_text('\n'.join(lines)+'\n')


def isolated_world(model, output):
    from voxel_mapper.shop_study import raster_mesh
    from voxel_mapper.bedrock import export_world
    from shapely.geometry import Polygon,Point
    walls,wall_review=raster_mesh(model['wall_mesh'],1);roof,roof_review=raster_mesh(model['roof_mesh'],1)
    holes=[Polygon(r['local_polygon_xz']) for r in model['openings']]
    # Conservative aperture clearance. Do not fill a sampled arch, window or door.
    removed={p for p in walls if any(g.covers(Point(p[0]+.5,p[1]+.5)) for g in holes)}
    walls-=removed
    cells={p:'stone_bricks' for p in walls};cells.update({p:'dark_oak_planks' for p in roof})
    rows=[{'x':x,'y':y,'z':z,'kind':'review_surface','material':mat,'feature':model['component_id']}
          for (x,y,z),mat in sorted(cells.items())]
    length=model['width_check']['elevation_length_m'];depth=model['measurements']['depth_m']
    rows.extend({'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'}
                for x in range(-6,int(length)+7) for z in range(-12,int(depth)+7))
    report={'version':'isolated-wing-world-review-v1','voxel_size_m':1,'model_blocks_per_source_metre':1,
            'crs':None,'vertical_datum':'STUDY_ZERO','spawn_local_xyz_m':[length/2,2,-7],
            'geographic_registration':None,'park_world_blocks_added':0,'world_placement_eligible':False,
            'local_review_surface_cells':len(cells),'wall_cells':len(walls),'roof_cells':len(roof),
            'aperture_alias_cells_removed':len(removed),'wall_sampling':wall_review,'roof_sampling':roof_review,
            'wall_roof_alias_cells':len(walls&roof),'unresolved':model['unresolved'],
            'display_palette_only':{'walls':'stone_bricks','roof':'dark_oak_planks'},
            'limitations':['Partial open surface study: outer facade, end walls, adjacent roofs and interiors omitted.',
                           'One-block surface thickness and materials are display proxies.',
                           'Roof assembly remains a cross-date hypothesis; no accepted park registration.',
                           'Centroid sampling aliases small details; no complete doorway clearance claim.'],
            'sources':[{'id':k,'url':'local://'+v,'attribution':'Checksum-pinned existing source drawing; reviewed trace seed'} for k,v in model['source_pdf_sha256'].items()]}
    output.mkdir();voxels=output/'voxels.jsonl';voxels.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report['world']=export_world(voxels,output,report,name='Mutiny North Range — PARTIAL LOCAL REVIEW',ground_depth=4)
    (output/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--recipe',required=True,type=Path)
    p.add_argument('--sources',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--isolated-world',action='store_true');a=p.parse_args()
    recipe=json.loads(a.recipe.read_text());paths={k:a.sources/(v['sha256']+'.pdf') for k,v in recipe['documents'].items()}
    report=run(a.recipe,paths,a.output);model=json.loads(Path(report['model_path']).read_text())
    if model['wall_mesh'] is not None:
        export_obj(model,a.output/'local-wing.obj')
        if a.isolated_world:report['isolated_world']=isolated_world(model,a.output/'isolated-world')
    (a.output/'review-report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='isolated_world'}))


if __name__=='__main__':main()
