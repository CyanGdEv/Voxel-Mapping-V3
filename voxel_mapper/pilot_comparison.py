"""Compare projected source geometry with material readback from a pilot world."""
from collections import Counter
from html import escape
import json
from pathlib import Path

import amulet
from shapely.geometry import Point, shape

from .bedrock import MATERIALS, material_block

VERSION = 'pilot-source-native-comparison-v1'


def write(output, quality, world):
    output = Path(output)
    features = json.loads((output / 'features-local.geojson').read_text())['features']
    geometry = {feature['id']: shape(feature['geometry']) for feature in features}
    counts = {identifier: Counter() for identifier in geometry}
    distances = {identifier: 0. for identifier in geometry}
    terrain, cells = {}, {}
    level = amulet.load_level(str(output / 'bedrock-world'))
    try:
        with (output / 'voxels.jsonl').open(encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                row = json.loads(line)
                x, y, z = row['x'], row['y'], row['z']
                if row['kind'] == 'terrain':
                    terrain[x, z] = y
                    continue
                identifier = row.get('feature')
                if identifier not in geometry:
                    continue
                expected = material_block(row.get('material', MATERIALS.get(row['kind'], 'stone')))
                actual = level.get_block(x, y + world['vertical_offset_blocks'], -z, 'minecraft:overworld')
                matches = (actual.namespaced_name == expected.namespaced_name
                           and all(actual.properties.get(key) == value for key, value in expected.properties.items()))
                counts[identifier]['emitted_voxel_records'] += 1
                counts[identifier]['native_material_matches' if matches else 'native_material_overrides'] += 1
                distances[identifier] = max(distances[identifier], geometry[identifier].distance(Point(x + .5, z + .5)))
                cells.setdefault((x, z), set()).add(bool(matches))
                if len(cells) + len(terrain) > 100_000:
                    raise ValueError('Pilot comparison cell budget exceeded')
                if index % 4096 == 0:
                    level.unload()
    finally:
        level.close()
    report = {'version': VERSION, 'source_voxel_sha256': quality['sha256'],
              'coordinate_frame': 'Local x east / z north in quality-report.json CRS; native Minecraft z is negative north.',
              'crs': quality['crs'], 'native_vertical_offset_blocks': world['vertical_offset_blocks'],
              'features': [{'id': identifier, **dict(counter),
                            'maximum_block_center_distance_outside_projected_geometry_m': distances[identifier]}
                           for identifier, counter in sorted(counts.items())],
              'planning_features_with_emitted_records': sum(identifier.startswith('planning/') and bool(counter)
                                                            for identifier, counter in counts.items()),
              'independent_placement_accuracy': 'not_verified',
              'limitations': ['Material agreement can be shared by overlapping features; it does not prove unique provenance.',
                              'Block-centre distance is a rasterization diagnostic, not source registration error.',
                              'Projected mapped paths can include assumed widths. No missing planning geometry is inferred.']}
    (output / 'placement-comparison.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    positions = set(terrain) | set(cells)
    if not positions:
        raise ValueError('No pilot comparison cells')
    minx = min(x for x, _ in positions)
    maxx = max(x for x, _ in positions) + 1
    minz = min(z for _, z in positions)
    maxz = max(z for _, z in positions) + 1
    scale = min(900 / max(1, maxx - minx), 570 / max(1, maxz - minz))
    def point(x, z):
        return 50 + (x - minx) * scale, 90 + (maxz - z) * scale
    def rectangle(x, z, colour):
        px, py = point(x, z + 1)
        return f'<rect x="{px:.3f}" y="{py:.3f}" width="{scale:.3f}" height="{scale:.3f}" fill="{colour}"/>'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="760" viewBox="0 0 1000 760">',
           '<rect width="1000" height="760" fill="white"/>',
           '<text x="50" y="30" font-family="sans-serif" font-size="22">Pilot source and saved-world comparison</text>',
           '<text x="50" y="57" font-family="sans-serif" font-size="14">Blue: projected source boundary | Orange: matching saved material | Magenta: overridden material</text>']
    low, high = min(terrain.values(), default=0), max(terrain.values(), default=0)
    for (x, z), elevation in sorted(terrain.items()):
        shade = round(245 - 65 * (elevation - low) / max(1, high - low))
        svg.append(rectangle(x, z, f'rgb({shade},{shade},{shade})'))
    for (x, z), matches in sorted(cells.items()):
        svg.append(rectangle(x, z, '#e69f00' if matches == {True} else '#cc3399'))
    def paths(geom):
        if geom.geom_type == 'Polygon':
            return [geom.exterior, *geom.interiors]
        if geom.geom_type in ('LineString', 'LinearRing'):
            return [geom]
        return [ring for part in getattr(geom, 'geoms', []) for ring in paths(part)]
    for identifier, geom in sorted(geometry.items()):
        for ring in paths(geom):
            points = ' '.join(f'{x:.3f},{y:.3f}' for x, y in (point(*v[:2]) for v in ring.coords))
            svg.append(f'<polyline points="{points}" fill="none" stroke="#0072b2" stroke-width="1"><title>{escape(identifier)}</title></polyline>')
    svg += ['<text x="50" y="697" font-family="sans-serif" font-size="15">North is up. Grey: generated terrain surface. One block per metre.</text>',
            '<text x="50" y="723" font-family="sans-serif" font-size="15">This checks rasterization and saved materials; independent registration and visual fidelity remain unverified.</text>',
            '</svg>']
    (output / 'placement-comparison.svg').write_text('\n'.join(svg) + '\n', encoding='utf-8')
    return {'file': 'placement-comparison.json', 'overlay': 'placement-comparison.svg',
            'features_compared': len(geometry),
            'native_material_matches': sum(counter['native_material_matches'] for counter in counts.values()),
            'native_material_overrides': sum(counter['native_material_overrides'] for counter in counts.values()),
            'independent_placement_accuracy': 'not_verified'}
