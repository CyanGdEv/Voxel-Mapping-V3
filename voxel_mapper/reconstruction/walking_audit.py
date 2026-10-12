"""Conservative support, connectivity and headroom checks for bridge profiles.

The graph uses cardinal neighbours and at most one metre of rise. Stair tops
use the taller tread; this is a voxel envelope check, not player movement or
in-game visual validation.
"""
import argparse
import json
import math
from pathlib import Path


def audit_walking_profile(walk, block_at, max_columns=100000):
    """Read universal blocks in the profile's local east/north metre frame."""
    if not walk or len(walk) > max_columns:
        raise ValueError('Nonempty bounded walking profile required')
    for (x, z), h in walk.items():
        if (not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, z))
                or not isinstance(h, (int, float)) or isinstance(h, bool) or not math.isfinite(h)
                or h * 2 != round(h * 2)):
            raise ValueError('Integer columns and finite half-metre walking heights required')
    support_errors = []
    headroom_errors = []
    abrupt_edges = []
    neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for (x, z), h in sorted(walk.items()):
        y = math.ceil(h) - 1
        block = block_at(x, y, z)
        name = block.base_name
        if name == 'slab':
            form = str(block.properties.get('type', '')).strip('"')
            actual = y + (.5 if form == 'bottom' else 1) if form in ('bottom', 'top', 'double') else None
        elif name == 'stairs':
            half = str(block.properties.get('half', '')).strip('"')
            actual = y + 1 if half in ('bottom', 'top') else None
        else:
            actual = y + 1 if name in ('stone', 'stone_bricks', 'cobblestone', 'concrete',
                                      'sandstone', 'bricks', 'planks') else None
        if actual != h or block.extra_blocks:
            support_errors.append([x, y, z, str(block), h])
        for yy in range(math.ceil(h), math.ceil(h) + 2):
            overhead = block_at(x, yy, z)
            if overhead.base_name != 'air' or overhead.extra_blocks:
                headroom_errors.append([x, yy, z, str(overhead)])
        for dx, dz in ((1, 0), (0, 1)):
            q = x + dx, z + dz
            if q in walk and abs(walk[q] - h) > 1:
                abrupt_edges.append([[x, z], list(q), abs(walk[q] - h)])
    remaining = set(walk)
    component_sizes = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = [start]
        size = 0
        while queue:
            k = queue.pop()
            size += 1
            for dx, dz in neighbours:
                q = k[0] + dx, k[1] + dz
                if q in remaining and abs(walk[q] - walk[k]) <= 1:
                    remaining.remove(q)
                    queue.append(q)
        component_sizes.append(size)
    passed = not support_errors and not headroom_errors and not abrupt_edges and len(component_sizes) == 1
    return {'status': 'passed' if passed else 'failed', 'walk_columns': len(walk),
            'connected': len(component_sizes) == 1, 'component_sizes': sorted(component_sizes, reverse=True),
            'support_error_count': len(support_errors), 'headroom_error_count': len(headroom_errors),
            'abrupt_edge_count': len(abrupt_edges),
            'examples': {'support': support_errors[:8], 'headroom': headroom_errors[:8],
                         'abrupt_edges': abrupt_edges[:8]},
            'check': 'Native support height, cardinal connectivity, maximum one-block rise and two air blocks overhead',
            'limitations': 'Conservative taller stair tread envelope; player movement and stair-facing transitions not tested'}


def audit_bridge_world(level, offset, features):
    """Audit emitted bridges against final native blocks, including composition."""
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError('Integer native vertical offset required')
    chunks = {}
    def native(x, y, z):
        if not -64 <= y + offset <= 319:
            raise ValueError('Walking envelope outside Bedrock height limits')
        key = x // 16, (-z) // 16
        if key not in chunks:
            chunks[key] = level.get_chunk(*key, 'minecraft:overworld')
        chunk = chunks[key]
        return chunk.block_palette[int(chunk.blocks[x % 16, y + offset, (-z) % 16])]
    results = []
    for feature in features:
        if feature.get('status') != 'emitted':
            continue
        rows = feature.get('walk_heights', [])
        if not rows or len(rows) > 100000:
            raise ValueError('Emitted bridge needs a bounded retained walking profile')
        walk = {(x, z): h for x, z, h in rows}
        if len(walk) != len(rows) or feature.get('walk_columns') != len(walk):
            raise ValueError('Duplicate or inconsistent retained bridge columns')
        results.append({'id': feature['id'], **audit_walking_profile(walk, native)})
    if not results:
        raise ValueError('No emitted bridge profiles to audit')
    return {'status': 'passed' if all(r['status'] == 'passed' for r in results) else 'failed',
            'bridges': results}


def require_bridge_walks(level, offset, features):
    result = audit_bridge_world(level, offset, features)
    if result['status'] != 'passed':
        failed = [r['id'] for r in result['bridges'] if r['status'] != 'passed']
        raise ValueError('Final native bridge walking audit failed: ' + ', '.join(failed)
                         + '; ' + json.dumps(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world', required=True, help='Extracted native Bedrock world directory')
    args = parser.parse_args()
    root = Path(args.world)
    report = json.loads((root / 'garden-bridges-report.json').read_text())
    import amulet
    level = amulet.load_level(str(root))
    try:
        result = audit_bridge_world(level, report['world_verification']['vertical_offset_blocks'],
                                    report['features'])
    finally:
        level.close()
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
