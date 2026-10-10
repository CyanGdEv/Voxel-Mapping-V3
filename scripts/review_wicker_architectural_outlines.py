"""Separate proposed roof/wall outlines before frozen native-roof comparison."""
import argparse, hashlib, json, sys
from pathlib import Path
import fitz
import numpy as np
from shapely.geometry import Polygon, shape
from shapely.affinity import affine_transform
from shapely.ops import unary_union
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.drawing_page_tools import pixel_to_native
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page

ROOF = '6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047'
FLOOR = '08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3'
MAINT = '457947fa1c1d4fb52ac51fcc6bc759f5e42c7a5e516ce0cb0ef1532b4893417f'
SITE = '3a8a18eb3959a39e7559309046b0815469b9f9baa52a5d1364a0cc4aa2cbb279'
OUTER = '9f75eb71c01873f01f5a4ffb62c24e1364518eab5253281ac1e996c1ff8d8652'
METRES_PER_POINT = 100 * .0254 / 72


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(a, b):
    return {'iou': a.intersection(b).area / a.union(b).area,
            'boundary_hausdorff_metres': a.boundary.hausdorff_distance(b.boundary),
            'centroid_separation_metres': a.centroid.distance(b.centroid)}


def dimensions(polygon):
    xy = np.array(polygon.exterior.coords)
    lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    return {'opposite_edge_mean_dimensions_metres': sorted(
        [float(lengths[::2].mean()), float(lengths[1::2].mean())], reverse=True),
        'area_metres_squared': polygon.area}


def fixed_scale_alignments(source, target):
    """Enumerate corner correspondences; rotate/translate only, never stretch."""
    x = np.asarray(source.exterior.coords)[:-1]
    y = np.asarray(target.exterior.coords)[:-1]
    if x.shape != (4, 2) or y.shape != (4, 2):
        raise ValueError('Four-corner shop outlines required')
    if source.exterior.is_ccw != target.exterior.is_ccw:
        y = y[::-1]
    result = []
    for shift in range(4):
        q = np.roll(y, shift, axis=0)
        u, _, vt = np.linalg.svd((x-x.mean(axis=0)).T @ (q-q.mean(axis=0)))
        rotation = u @ vt
        if np.linalg.det(rotation) < 0:
            raise ValueError('Reflection is not a supported correspondence')
        translation = q.mean(axis=0)-x.mean(axis=0) @ rotation
        errors = np.linalg.norm(x @ rotation+translation-q, axis=1)
        result.append({'corner_shift': shift, 'row_rotation': rotation.tolist(),
                       'translation_m': translation.tolist(),
                       'shop_corner_rms_metres': float(np.sqrt(np.mean(errors**2))),
                       'shop_corner_max_metres': float(errors.max())})
    return sorted(result, key=lambda v: (v['shop_corner_rms_metres'], v['corner_shift']))[:2]


def transform(p, rotation, translation):
    r = np.asarray(rotation)
    return affine_transform(p, [r[0, 0], r[1, 0], r[0, 1], r[1, 1], *translation])


def review(annotations, pdf_paths, floor_scale, site_pdf, site_review, plane_review):
    a = json.loads(Path(annotations).read_text())
    if len(a['sheets']) != 3 or {v['source_sha256'] for v in a['sheets']} != {ROOF, FLOOR, MAINT}:
        raise ValueError('Exactly three distinct reviewed architectural sheets required')
    scale = json.loads(Path(floor_scale).read_text())
    site = json.loads(Path(site_review).read_text())
    planes = json.loads(Path(plane_review).read_text())
    if set(pdf_paths) != {ROOF, FLOOR, MAINT} or digest(site_pdf) != SITE:
        raise ValueError('Pinned architectural and site sheets required')
    if (scale['floor_sha256'] != FLOOR or scale['roof_plan_sha256'] != ROOF
            or site['document_sha256'] != SITE or planes['input_sha256']['site'] != digest(site_review)):
        raise ValueError('Matched scale, site and native plane reviews required')
    furniture = np.asarray(scale['roof_to_floor_matrix_row_convention'])
    if furniture.shape != (3, 2) or scale['heldout_max_residual_pdf_points'] > .25:
        raise ValueError('Reviewed floor reduction required')
    rows = []; roof_geometry = {}
    for annotation in a['sheets']:
        sha = annotation['source_sha256']; path = pdf_paths[sha]
        if (digest(path) != sha or annotation['scale_denominator'] != 100
                or annotation['render_width_pixels'] != 1888 or annotation['manual_endpoint_bound_pixels'] != 2):
            raise ValueError('Source checksum or scale changed')
        with fitz.open(path) as doc:
            p = doc[0]; pix = p.get_pixmap(matrix=fitz.Matrix(1888/p.rect.width, 1888/p.rect.width))
            if ([pix.width, pix.height] != annotation['render_size_pixels']
                    or digest_samples(pix) != annotation['render_samples_sha256']):
                raise ValueError('Annotated source raster changed')
            matrix = fitz.Matrix(pixel_to_native(p, pix.width, pix.height))
            for role, points in annotation['outlines_pixels'].items():
                xy = np.asarray(points, dtype=float)
                if xy.shape != (4, 2) or not np.isfinite(xy).all() or np.any(xy < 0) or np.any(xy >= [pix.width, pix.height]):
                    raise ValueError('Invalid bounded four-corner annotation')
                native = np.array([list(fitz.Point(*point)*matrix) for point in xy])
                normalized = ((native-furniture[2]) @ np.linalg.inv(furniture[:2])) if sha == FLOOR else native
                polygon = Polygon(normalized*METRES_PER_POINT)
                if not polygon.is_valid or polygon.area <= 0:
                    raise ValueError('Invalid outline')
                row = {'source_sha256': sha, 'role': role, 'native_pdf_corners_y_up': native.tolist(),
                       'measurement_frame': 'roof-sheet furniture-normalized metres' if sha == FLOOR else 'own-sheet printed-scale metres',
                       'geometry': polygon.__geo_interface__, **dimensions(polygon)}
                rows.append(row)
                if sha == ROOF: roof_geometry[role] = polygon
    with fitz.open(site_pdf) as doc:
        raw, _ = extract_page(doc[0], SITE, 1); candidates, _ = recover_page(raw)
    outer = next(c for c in candidates if c['id'] == OUTER)
    site_outlines = {name: shape(c['geometry']) for name, c in site['source_candidates'].items()}
    site_outlines['maintenance_outer_candidate'] = shape(outer['geometry'])
    site_metres = {name: transform(g, np.eye(2)*2.5*METRES_PER_POINT, [0, 0]) for name, g in site_outlines.items()}
    fits = fixed_scale_alignments(roof_geometry['shop_main_roof'], site_metres['shop'])
    hypotheses = []
    for fit in fits:
        placed = {name: transform(g, fit['row_rotation'], fit['translation_m']) for name, g in roof_geometry.items()}
        # Furniture transform is only used to normalize drawing coordinates, not geographical controls.
        plan_checks = {name: {'roof_vs_site_inner': metrics(placed[name+'_main_roof'], site_metres[name])}
                       for name in ['station', 'maintenance']}
        plan_checks['maintenance']['roof_vs_site_outer_candidate'] = metrics(placed['maintenance_main_roof'], site_metres['maintenance_outer_candidate'])
        native_cases = {}
        # Convert site metres back to site PDF points before applying the already frozen shop fit.
        h = site['frozen_hypotheses'][0]
        for name, g in placed.items():
            native_cases[name] = transform(g, np.asarray(h['matrix']).T/(2.5*METRES_PER_POINT), h['translation_m'])
        native_cases['site_maintenance_outer_candidate'] = affine_transform(
            site_outlines['maintenance_outer_candidate'], [*h['matrix'][0], *h['matrix'][1], *h['translation_m']])
        native_cases['maintenance_and_communications_roofs'] = unary_union([
            native_cases['maintenance_main_roof'], native_cases['communications_roof']])
        comparisons = {}
        for name, g in native_cases.items():
            if name == 'shop_main_roof': continue
            comparisons[name] = [{'pair_index': i, **metrics(g, shape(pair['support_envelope']))}
                                 for i, pair in enumerate(planes['ridge_pairs'])]
        hypotheses.append({**fit, 'plan_correspondence_checks': plan_checks,
                           'native_geometries': {n: g.__geo_interface__ for n, g in native_cases.items()},
                           'all_native_pair_comparisons': comparisons})
    return {'status': 'proposed_line_role_and_cross_sheet_review_only', 'measurements': rows,
            'site_outer_candidate': outer, 'shop_only_drawing_correspondence_hypotheses': hypotheses,
            'input_sha256': {str(p): digest(p) for p in [annotations, floor_scale, site_pdf, site_review, plane_review, *pdf_paths.values()]},
            'drawing_correspondence_is_not_geographic_registration': True,
            'additional_roofs_used_to_refit_geographic_transform': False,
            'limitations': ['All architectural sheets are proposed, not verified as-built.',
                           'Four-corner manual traces have a two-pixel endpoint sampling bound, not physical positional uncertainty.',
                           'The shop defines drawing correspondences at fixed printed scale; both half-turn alternatives are retained.',
                           'Floor furniture normalization is provisional for additional building dimensions; their placement relative to the roof sheet is not verified.',
                           'Site inner/outer line roles are tested by comparison, not promoted to surveyed physical edges.',
                           'A communications-roof union is an explicit hypothesis; it is not one surveyed main roof.',
                           'Datum and independent geographical checkpoints remain unresolved.'],
            'accepted_controls': 0, 'accepted_checkpoints': 0, 'world_geometry_additions': 0}


def digest_samples(pix):
    return hashlib.sha256(pix.samples).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['annotations', 'roof-pdf', 'floor-pdf', 'maintenance-pdf', 'floor-scale', 'site-pdf', 'site-review', 'plane-review', 'output']:
        p.add_argument('--'+name, required=True)
    a = p.parse_args()
    result = review(a.annotations, {ROOF:a.roof_pdf, FLOOR:a.floor_pdf, MAINT:a.maintenance_pdf}, a.floor_scale, a.site_pdf, a.site_review, a.plane_review)
    Path(a.output).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'measurements':len(result['measurements']), 'drawing_hypotheses':2,
                      'output':a.output, 'accepted_controls':0, 'accepted_checkpoints':0, 'world_geometry_additions':0}))


if __name__ == '__main__': main()
