"""Retained Forbidden Valley plans, component evidence and bounded draft overlays.

Source coordinates are displayed PDF points (rotation applied). Draft world
placement uses printed scale and an explicitly estimated OSM ride pose.
Building sheets and coaster plan views retain separate registration/3D gates.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.affinity import affine_transform, translate
from shapely.geometry import Polygon, Point, shape, mapping
from shapely.ops import transform, unary_union

from .park_paving_plans import surface_boundaries
from .wicker_surfaces import visible_fills
from .wicker_registration import similarity_candidates, apply_candidate
from .reconstruction.geometry import roof_cells
from .reconstruction.rocks import rock_cells
from .paving_palette import palette_block

APPLICATIONS = ('SMD/2024/0064', 'SMD/2023/0515', 'SMD/2023/0516', 'SMD/2022/0032')
OCEAN = '1f63552a5939d90185011fa3c7c71cd755b4fb2c44b59f52b71ae1b7133372be'
RETAIL = 'f797c8eae1dcb2bf3203eab48294d9cc8ceca7c72b5dfffab22be8b94d1d0c2b'
ARCADE = 'c672f480553cacee525d5f11356526ba0737f76fed83717968d3a73bbd28f076'
SCALE = 100 / (1000 * 72 / 25.4)


def displayed(geometry, page):
    m = page.rotation_matrix
    return affine_transform(geometry, [m.a, m.c, m.b, m.d, m.e, m.f])


def reviewed_outline(page, targets, tolerance=4):
    """Snap explicit reviewed corners to native straight-line endpoints."""
    vertices = []
    for path in page.get_drawings():
        for item in path['items']:
            if item[0] == 'l':
                vertices.extend(tuple(p * page.rotation_matrix) for p in item[1:])
    if not vertices:
        raise ValueError('Reviewed native outline has no straight-line endpoints')
    result = []
    for target in targets:
        nearest = min(vertices, key=lambda p: math.dist(p, target))
        if math.dist(nearest, target) > tolerance:
            raise ValueError('Reviewed native outline corner no longer matches source')
        result.append(nearest)
    polygon = Polygon(result)
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError('Invalid reviewed building outline')
    return polygon


def queue_mask(page):
    """Reviewed native colour mask, bounded to the ground-floor plan panel.

    Colour is used to recover this reviewed legend class only, not to infer
    construction materials. Annotation knockouts and raster edges remain in
    the geometry; no holes are filled or corridors extrapolated.
    """
    import pymupdf
    from rasterio.features import shapes
    from affine import Affine
    clip = pymupdf.Rect(78, 40, 1300, 1135)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), clip=clip, alpha=False)
    pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    colour = np.array([199, 186, 156])
    mask = np.max(np.abs(pixels.astype(np.int16) - colour), axis=2) <= 3
    polygons = [shape(g) for g, value in shapes(mask.astype('uint8'), mask=mask,
                transform=Affine.translation(pix.x, pix.y)) if value == 1]
    polygons = [g for g in polygons if g.area * SCALE**2 >= .15]
    if not polygons:
        raise ValueError('Reviewed queue mask missing')
    return unary_union(polygons)


def extract(planning_cache):
    import pymupdf
    cache = Path(planning_cache)
    catalogue = json.loads((Path(__file__).parent / 'data/alton-planning-catalogue.json').read_text())
    entries = [r for r in catalogue['entries'] if r.get('applicationReference') in APPLICATIONS]
    documents = []
    for entry in entries:
        path = cache / (entry['sha256'] + '.pdf')
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Missing or changed Forbidden Valley PDF: ' + entry['title'])
        with pymupdf.open(path) as pdf:
            documents.append({**entry, 'pages': len(pdf),
                              'native_text_available': any(page.get_text().strip() for page in pdf)})
    with pymupdf.open(cache / (OCEAN + '.pdf')) as pdf:
        page = pdf[0]
        if 'P0.5' not in page.get_text() or 'New Rockwork' not in page.get_text():
            raise ValueError('Reviewed Ocean revision or rockwork label mismatch')
        faces = surface_boundaries(page.get_drawings(extended=True), SCALE, min_area=.15, max_area=1500)
        deck = displayed(shape(faces[0]['geometry']), page)
        if not 190 <= deck.area * SCALE**2 <= 205 or deck.centroid.x < 1300:
            raise ValueError('Reviewed first-floor deck no longer matches')
        fills, withheld = visible_fills(page.get_drawings(extended=True))
        rocks = []
        for fill in fills:
            g = displayed(fill['polygon'], page)
            if (max(abs(a-b) for a,b in zip(fill['fill'], (.699219,)*3)) < .001
                    and g.bounds[0] < 1300 and g.bounds[3] < 520 and g.area * SCALE**2 > .15):
                rocks.append({'id': 'ocean-rock-' + str(fill['sequence']), 'kind': 'rock',
                              'geometry': mapping(g), 'source_sequence': fill['sequence']})
        if len(rocks) != 9:
            raise ValueError('Reviewed nine ground-floor rockwork profiles no longer match')
        queue = queue_mask(page)
    with pymupdf.open(cache / (RETAIL + '.pdf')) as pdf:
        retail = reviewed_outline(pdf[0], [(289,811), (671,811), (671,731), (801,599),
                                          (1103,599), (1234,731), (1234,1178), (289,1178)])
    with pymupdf.open(cache / (ARCADE + '.pdf')) as pdf:
        arcade = reviewed_outline(pdf[0], [(388,205), (1584,205), (1584,758), (388,758)])
        arcade_revision = 'P0.2' if 'P0.2' in pdf[0].get_text() else 'unresolved'
    return {'status': 'reviewed_proposed_components_with_separate_placement_gates',
            'registration_verified': False, 'as_built_verified': False, 'documents': documents,
            'ocean': {'document_id': OCEAN, 'page': 1, 'native_revision': 'P0.5',
                      'scale_m_per_displayed_point': SCALE,
                      'deck_first_floor_geometry': mapping(deck),
                      'ground_to_first_floor_display_shift': [779.88, 0],
                      'panel_shift_basis': 'Matching repeated native stair face at the same height; no vertical datum inferred',
                      'queue_geometry': mapping(queue), 'queue_mask_area_m2': queue.area*SCALE**2,
                      'queue_printed_area_approx_m2': 205,
                      'queue_geometry_method': 'Reviewed legend-colour raster mask in ground-floor panel; no annotation-hole filling',
                      'queue_material': 'porous surfacing; composition/colour unspecified',
                      'resurfacing': {'kind': 'block paving', 'approx_area_m2': 260,
                                      'status': 'withheld_unbounded_extent_to_be_agreed'},
                      'rocks': rocks, 'withheld_fill_paths': withheld,
                      'underpass': {'destination': 'Galactica', 'status': 'withheld_missing_absolute_deck_and_clearance_levels'},
                      'fences': {'queue_heights_m': [1.1, 1.3], 'status': 'retained_not_rasterized_without_reviewed_routes'},
                      'stairs_and_retaining_structure': 'Sections retained; final detail explicitly deferred in plan'},
            'buildings': [
                {'id': 'nemesis-retail', 'document_id': RETAIL, 'page': 1,
                 'geometry': mapping(retail), 'scale_m_per_displayed_point': SCALE/2,
                 'printed_max_dimensions_m': [16.7,10.2], 'ridge_height_m': 4.1, 'eaves_height_m': 3.5,
                 'dimension_source': '42a89a088e08ec46927b2feb2603085f2656c531271241e39e58fe9d55edbda7',
                 'walls': 'insulated profiled metal panels', 'roof': 'insulated profiled metal panels',
                 'colour': 'unspecified', 'status': 'relative_footprint_ready_world_placement_withheld'},
                {'id': 'edge-arcade', 'document_id': ARCADE, 'page': 1,
                 'geometry': mapping(arcade), 'scale_m_per_displayed_point': SCALE/2,
                 'native_revision': arcade_revision,
                 'catalogue_revision_warning': 'Catalogue says P0.3; native sheet is Option 2 / P0.2. Not claimed as latest/as-built',
                 'height_m': 5.7,
                 'dimension_source': 'feae4e281b7415335257f5fbb0da0693b7a5ec94d933553c581ba5c6be588991',
                 'walls': 'insulated profiled metal panels', 'roof': 'insulated profiled metal panels',
                 'exposed_upper_elements': 'black RAL 9005', 'wall_panel_colour': 'client confirmation required',
                 'status': 'relative_footprint_ready_world_placement_withheld'}],
            'rides': {'nemesis': {'application': 'SMD/2022/0032',
                                  'status': 'plan_layout_retained_3d_track_withheld',
                                  'missing': ['absolute rail heights', 'banking', 'inversion and support geometry']},
                      'galactica': {'status': 'mapped_layout_and_underpass_context_only'},
                      'ocean': {'status': 'proposed_deck_footprint_ready_height_and_mechanism_withheld'}},
            'limitations': ['Proposed and existing plan revisions do not establish current construction',
                            'Building sheets retain independent local drawing frames; no cross-sheet placement is assumed',
                            'Rock height, shape recipe and vanilla texture choices are estimates; generic rockwork does not identify lithology']}


def ocean_pose(inventory, raw):
    """Printed scale is preserved even when an OSM shape-fit prefers stretching."""
    project = Transformer.from_crs(4326, 27700, always_xy=True)
    way = next(e for e in raw['elements'] if e.get('type') == 'way' and e['id'] == 1478683702)
    target = Polygon([project.transform(p['lon'],p['lat']) for p in way['geometry']])
    deck = shape(inventory['ocean']['deck_first_floor_geometry'])
    candidates = similarity_candidates(list(deck.minimum_rotated_rectangle.exterior.coords)[:4],
                                       list(target.minimum_rotated_rectangle.exterior.coords)[:4])
    # Reviewed Ground Command Coffee Outpost position excludes the flipped pose.
    checkpoint = [[1040 + 779.88, 160]]
    coffee = np.array([407957.7506521623, 343257.32799039414])
    candidate = min(candidates, key=lambda c: np.linalg.norm(apply_candidate(checkpoint,c)[0]-coffee))
    fitted_scale = candidate['scale_m_per_pdf_point']
    candidate.pop('shop_corner_rms_m', None)
    candidate['scale_m_per_pdf_point'] = SCALE
    centre = np.array([deck.centroid.x, -deck.centroid.y])
    candidate['translation_epsg27700_m'] = (np.array(target.centroid.coords[0])-SCALE*centre@np.array(candidate['rotation'])).tolist()
    error = float(np.linalg.norm(apply_candidate(checkpoint,candidate)[0]-coffee))
    if error > 5:
        raise ValueError('Estimated pose fails bounded coffee-outpost context check')
    return candidate, {'status': 'estimated_current_osm_ride_centroid_and_orientation',
                       'osm_way': way['id'], 'printed_scale_preserved': True,
                       'rejected_shape_fit_scale_m_per_point': fitted_scale,
                       'coffee_context_error_m': error,
                       'check_status': 'approximate context check, not independently surveyed accuracy',
                       'candidate': candidate, 'registration_verified': False}


def generate(source, output, planning_cache, osm):
    from .xsector import apply_overlay
    import amulet
    source, output = Path(source), Path(output)
    inventory = extract(planning_cache)
    raw_bytes = Path(osm).read_bytes()
    raw = json.loads(raw_bytes)
    pose, placement = ocean_pose(inventory, raw)
    quality = json.loads((source/'quality-report.json').read_text())
    bng = Transformer.from_crs(27700, quality['crs'], always_xy=True)
    def local(g):
        g = translate(g, xoff=779.88)
        def convert(x,y,z=None):
            points = apply_candidate(list(zip(x,y)),pose)
            return bng.transform(points[:,0],points[:,1])
        return transform(convert,g)
    queue = local(shape(inventory['ocean']['queue_geometry']))
    offset = quality['world']['vertical_offset_blocks']
    level = amulet.load_level(str(source/'bedrock-world'))
    chunks, floors, rows, decisions = {}, {}, {}, []
    def native(x,y,z):
        key = x//16, (-z)//16
        if key not in chunks:
            chunks[key] = level.get_chunk(*key,'minecraft:overworld')
        chunk = chunks[key]
        return chunk.block_palette[int(chunk.blocks[x%16,y+offset,(-z)%16])]
    def floor(x,z):
        if (x,z) not in floors:
            ys = [y+1 for y in range(160,190) if native(x,y,z).base_name == 'dirt']
            floors[x,z] = max(ys) if ys else None
        return floors[x,z]
    def put(k,m,feature):
        rows[k] = dict(x=k[0],y=k[1],z=k[2],material=m,feature=feature,
                       source='forbidden-valley-proposed-plans',document_id=OCEAN,page=1)
    try:
        applied = blocked = partial = 0
        for x,z in roof_cells(queue):
            y = floor(x,z)
            if y is None:
                blocked += 1
                continue
            old = native(x,y,z)
            if old.base_name in ('slab','stairs'):
                partial += 1
                continue
            if (old.base_name not in ('grass_block','stone','cobblestone','stone_bricks','concrete')
                    or old.extra_blocks or any(native(x,yy,z).base_name!='air' for yy in (y+1,y+2))):
                blocked += 1
                continue
            put((x,y,z),palette_block('stone',x,z),'ocean-porous-queue')
            applied += 1
        decisions.append({'id':'ocean-porous-queue','kind':'path','status':'emitted' if applied else 'withheld',
                          'emitted_columns':applied,'protected_columns':blocked,'preserved_partial_columns':partial,
                          'geometry':mapping(queue),'material_status':'User stone palette proxy; porous composition unspecified',
                          'walking_status':'Individual headroom checked; complete queue connectivity not claimed'})
        for rock in inventory['ocean']['rocks']:
            g = local(shape(rock['geometry']))
            if g.intersects(queue.buffer(.5)):
                decisions.append({'id':rock['id'],'kind':'rock','status':'withheld','reason':'Queue envelope overlap'})
                continue
            blocks, detail = rock_cells(g, floor, 'jagged', 2)
            if not blocks or any(native(*k).base_name!='air' or k in rows for k in blocks):
                decisions.append({'id':rock['id'],'kind':'rock','status':'withheld','reason':'Existing solid or empty voxel footprint'})
                continue
            for k,m in blocks.items():
                put(k,m,rock['id'])
            decisions.append({'id':rock['id'],'kind':'rock','status':'emitted','blocks':len(blocks),
                              'geometry':mapping(g),'shape':detail})
    finally:
        level.close()
    if not rows:
        raise ValueError('No safe Forbidden Valley additions')
    report = {'stations':[],'world_name':'Alton Towers V20 — Forbidden Valley planning draft',
              'status':'partial_proposed_plan_overlay_with_estimated_placement',
              'inventory':inventory,'placement':placement,'features':decisions,
              'osm_sha256':hashlib.sha256(raw_bytes).hexdigest(),
              'limitations':inventory['limitations']+[
                  'Ocean placement uses the current mapped ride pose; independent survey registration remains unresolved',
                  'Buildings, ride mechanism, deck elevation and underpass are retained in inventory but not emitted',
                  'Only safe queue columns and unobstructed rock objects are applied; no complete queue route is claimed']}
    bridge_report = source/'bedrock-world'/'garden-bridges-report.json'
    verify_world = None
    if bridge_report.exists():
        from .reconstruction.walking_audit import require_bridge_walks
        bridges = json.loads(bridge_report.read_text())['features']
        verify_world = lambda world, shift: require_bridge_walks(world, shift, bridges)
    apply_overlay(source,output,list(rows.values()),report,'forbidden_valley',
                  'forbidden-valley-report.json',verify_world=verify_world)
    (output/'forbidden-valley-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows.values()))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--planning-cache',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--source-output')
    parser.add_argument('--osm')
    parser.add_argument('--estimated-placement',action='store_true')
    args = parser.parse_args()
    if args.source_output:
        if not args.estimated_placement or not args.osm:
            parser.error('Draft world output requires --estimated-placement and --osm')
        report = generate(args.source_output,args.output,args.planning_cache,args.osm)
        print(json.dumps({'features':[{k:v for k,v in f.items() if k!='geometry'}
                                      for f in report['features']],
                          'native':report['world_verification']},indent=2))
    else:
        out = Path(args.output)
        if out.exists():
            raise ValueError('Refusing to overwrite output')
        out.mkdir(parents=True)
        report = extract(args.planning_cache)
        (out/'forbidden-valley-inventory.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'documents':len(report['documents']),'rocks':len(report['ocean']['rocks']),
                          'building_profiles':len(report['buildings'])}))


if __name__ == '__main__':
    main()
