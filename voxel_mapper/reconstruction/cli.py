"""Plan modular geometry against retained terrain and optionally compose a world."""
import argparse,json
from pathlib import Path
from shapely.geometry import shape
from pyproj import CRS
from .model import Source,Feature
from .sources import AdapterRegistry
from .engine import ReconstructionEngine,Context
from .generators import default_registry
from ..terrain import Terrain


def run(manifest_path,terrain_config_path,output,base_world=None,allow_estimates=False):
    manifest_path=Path(manifest_path);manifest=json.loads(manifest_path.read_text());output=Path(output)
    if output.exists():raise ValueError('Use a new output directory')
    sources={}
    for row in manifest['sources']:
        source=Source(**row)
        if source.id in sources:raise ValueError('Duplicate source identity')
        sources[source.id]=source
    features,inputs=AdapterRegistry().load(manifest.get('feeds',[]),sources,manifest['crs'],manifest_path.parent)
    features.extend(Feature(**row) for row in manifest.get('features',[]))
    # Inline features already use target coordinates; feed inputs are projected.
    config=json.loads(Path(terrain_config_path).read_text())
    if config['terrain'].get('vertical_datum')!=manifest.get('vertical_datum'):raise ValueError('Terrain datum mismatch')
    terrain=Terrain(config['terrain'],CRS.from_user_input(manifest['crs']),{s['id']:s for s in config['sources']})
    level=None;occupied=None;cache={}
    try:
        if base_world:
            import amulet
            base_world=Path(base_world);quality=json.loads((base_world/'quality-report.json').read_text())
            if CRS.from_wkt(quality['crs'])!=CRS.from_user_input(manifest['crs']):raise ValueError('Base world CRS mismatch')
            offset=quality['world']['vertical_offset_blocks'];level=amulet.load_level(str(base_world/'bedrock-world'))
            coords=set(level.all_chunk_coords('minecraft:overworld'))
            def occupied(x,y,z):
                key=x//16,(-z)//16
                if key not in coords or not -64<=y+offset<=319:raise ValueError('Reconstruction extends beyond base world')
                if key not in cache:cache[key]=level.get_chunk(*key,'minecraft:overworld')
                chunk=cache[key];return chunk.block_palette[int(chunk.blocks[x%16,y+offset,(-z)%16])]
        context=Context(sources,terrain.sample,shape(manifest['boundary']),manifest.get('vertical_datum'),allow_estimates,
                        manifest.get('max_feature_voxels',100_000),manifest.get('max_total_voxels',2_000_000),occupied)
        rows,report=ReconstructionEngine(default_registry()).plan(features,context)
        report.update(inputs=inputs,sources=[s.__dict__ for s in sources.values()],vertical_datum=context.vertical_datum)
    finally:
        terrain.close()
        if level:level.close()
    if base_world:
        from ..xsector import apply_overlay
        report.update(stations=[],world_name=manifest.get('world_name','Modular park reconstruction'))
        apply_overlay(base_world,output,rows,report,report_key='modular_reconstruction',report_filename='reconstruction-report.json')
    else:output.mkdir(parents=True)
    (output/'reconstruction-overlay.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    (output/'reconstruction-report.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True);parser.add_argument('--terrain-config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--base-world');parser.add_argument('--allow-estimates',action='store_true')
    args=parser.parse_args();report=run(args.manifest,args.terrain_config,args.output,args.base_world,args.allow_estimates)
    print(json.dumps({'features':report['features'],'unique_voxel_cells':report['unique_voxel_cells'],'withheld':sum(d['status']=='withheld' for d in report['decisions'])}))

if __name__=='__main__':main()
