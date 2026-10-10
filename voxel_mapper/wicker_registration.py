"""Automatic, explicitly provisional SW8 shop/track alignment.

One named shop supplies orientation/translation candidates. Mapped ride geometry
checks the candidates without fitting to track labels. This is not surveyed
control, a vertical datum, as-built verification, or permission to render.
"""
import gzip
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, Polygon, LineString, mapping, box
from shapely.ops import unary_union


def straight_ring(drawing):
    items = drawing.get('items', [])
    if len(items) < 3 or any(item[0] != 'l' for item in items):
        return None
    if any(items[i][2] != items[i+1][1] for i in range(len(items)-1)):
        return None  # Do not connect unrelated subpaths or label glyphs.
    coordinates = [item[1] for item in items]+[items[-1][2]]
    if coordinates[0] != coordinates[-1]:
        return None
    polygon = Polygon(coordinates)
    return polygon if polygon.is_valid and not polygon.is_empty else None


def similarity_candidates(pdf_corners, mapped_corners):
    """Fit all cyclic corner identities; no shear or anisotropic stretching."""
    a = np.asarray(pdf_corners, dtype=float).copy()
    b = np.asarray(mapped_corners, dtype=float)
    if a.shape != (4, 2) or b.shape != (4, 2) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Expected two finite four-corner footprints')
    a[:, 1] *= -1  # PDF y down to Cartesian y up.
    centred = a-a.mean(axis=0)
    denominator = (centred*centred).sum()
    if denominator <= 0 or Polygon(a).area <= 0 or Polygon(b).area <= 0:
        raise ValueError('Degenerate registration footprint')
    candidates = []
    for direction in (b, b[::-1]):
        for shift in range(4):
            target = np.roll(direction, shift, axis=0)
            u, singular, vt = np.linalg.svd(centred.T@(target-target.mean(axis=0)))
            rotation = u@vt
            if np.linalg.det(rotation) < 0:
                continue
            scale = singular.sum()/denominator
            translation = target.mean(axis=0)-scale*a.mean(axis=0)@rotation
            residual = scale*a@rotation+translation-target
            candidates.append({'scale_m_per_pdf_point': float(scale), 'rotation': rotation.tolist(),
                               'translation_epsg27700_m': translation.tolist(),
                               'shop_corner_rms_m': float(np.sqrt((residual*residual).sum(axis=1).mean()))})
    return candidates


def apply_candidate(points, candidate):
    coordinates = np.asarray(points, dtype=float).copy()
    coordinates[:, 1] *= -1
    return (candidate['scale_m_per_pdf_point']*coordinates@np.asarray(candidate['rotation'])
            +np.asarray(candidate['translation_epsg27700_m']))


def printed_scale(annotations):
    # The 0..40 marks are numeric only; using the centre of "50 m" would
    # displace the last tick by the unit suffix. Require one horizontal row.
    rows = {}
    for annotation in annotations:
        if annotation['text'] not in ('0', '10', '20', '30', '40'):
            continue
        x0, y0, x1, y1 = annotation['bbox']
        rows.setdefault(round((y0+y1)/2), {}).setdefault(annotation['text'], []).append((x0+x1)/2)
    fits = []
    for row in rows.values():
        if len(row) != 5 or any(len(values) != 1 for values in row.values()):
            continue
        positions = [row[str(value)][0] for value in (0, 10, 20, 30, 40)]
        slope, intercept = np.polyfit([0, 10, 20, 30, 40], positions, 1)
        error = max(abs(x-(slope*value+intercept)) for value, x in zip((0, 10, 20, 30, 40), positions))
        if slope > 0 and error < 1:
            fits.append(float(1/slope))
    if len(fits) != 1:
        raise ValueError('No unique consistent printed scale bar')
    return fits[0]


def inspect_alignment(evidence, raw_osm, output, bounds):
    output = Path(output)
    report = {'status': 'unavailable', 'registration_verified': False, 'as_built_verified': False,
              'world_geometry_additions': 0, 'vertical_datum_verified': False,
              'limitations': ['Four shop corners belong to one mapped object, not four independent survey controls',
                             'Track checks use annotation centres, not surveyed track height-point coordinates',
                             'OSM may share the drawing source; these checks do not establish independent accuracy']}
    features = []
    try:
        drawings = [d for d in evidence['documents'] if d.get('status') == 'inspected'
                    and '7B Site Plan Proposed' in d['title']]
        shops = [element for element in raw_osm['elements'] if element.get('tags', {}).get('name') == 'Wicker Man Shop']
        if len(drawings) != 1 or len(shops) != 1:
            raise ValueError('Need one proposed SW8 site plan and one named mapped shop')
        document = drawings[0]
        page = document['pages'][0]
        if page['rotation'] != 0 or page.get('vector_status') != 'drawing_space_only':
            raise ValueError('Unrotated complete drawing vectors required')
        labels = [a for a in page['annotations'] if a['text'] == 'Shop']
        if len(labels) != 1:
            raise ValueError('Shop drawing label is ambiguous')
        x0, y0, x1, y1 = labels[0]['bbox']
        centre = Point((x0+x1)/2, (y0+y1)/2)
        scale = printed_scale(page['annotations'])
        with gzip.open(output/page['vector_file'], 'rt') as stream:
            vectors = json.load(stream)
        rings = {}
        for drawing in vectors:
            if drawing.get('fill') != [1., 1., 1.] or len(drawing.get('items', [])) != 4:
                continue
            polygon = straight_ring(drawing)
            if polygon is not None and 25 <= polygon.area*scale**2 <= 2500 and polygon.contains(centre):
                rings[polygon.normalize().wkb] = polygon
        if len(rings) != 1:
            raise ValueError('No unique closed shop footprint; label masks are excluded')
        shop_ring = next(iter(rings.values()))
        mapped_ring = [(p['lon'], p['lat']) for p in shops[0].get('geometry', [])]
        if len(mapped_ring) != 5 or mapped_ring[0] != mapped_ring[-1] or not box(*bounds).covers(Polygon(mapped_ring)):
            raise ValueError('Expected a closed four-corner shop inside the test area')
        project = Transformer.from_crs(4326, 27700, always_xy=True)
        inverse = Transformer.from_crs(27700, 4326, always_xy=True)
        mapped = [project.transform(*point) for point in mapped_ring[:-1]]
        track_parts = [LineString([project.transform(p['lon'], p['lat']) for p in element['geometry']])
                       for element in raw_osm['elements'] if element.get('tags', {}).get('name') == 'Wicker Man'
                       and element['tags'].get('roller_coaster') == 'track' and len(element.get('geometry', [])) >= 2]
        if not track_parts:
            raise ValueError('Mapped track unavailable for candidate checks')
        track = unary_union(track_parts)
        annotations = page['ride_level_candidates']
        points = [[(a['bbox'][0]+a['bbox'][2])/2, (a['bbox'][1]+a['bbox'][3])/2] for a in annotations]
        if not points:
            raise ValueError('No ride high/low annotations')
        candidates = similarity_candidates(list(shop_ring.exterior.coords)[:-1], mapped)
        passing = []
        for candidate in candidates:
            xy = apply_candidate(points, candidate)
            distances = [float(track.distance(Point(point))) for point in xy]
            groups = {}
            for i, annotation in enumerate(annotations):
                groups.setdefault(annotation['point_label'], []).append(i)
            selected, excluded = [], []
            for label, indices in groups.items():
                close = [i for i in indices if distances[i] <= 5]
                if len(close) == 1 and all(distances[i] >= 10 for i in indices if i != close[0]):
                    selected.extend(close)
                    excluded.extend(i for i in indices if i != close[0])
            candidate.update(unique_near_track_labels=len(selected),
                             matched_annotation_indices=selected, excluded_duplicate_indices=excluded,
                             annotation_distances_m=distances,
                             scale_difference_fraction=abs(candidate['scale_m_per_pdf_point']/scale-1))
            if selected:
                candidate['median_annotation_track_distance_m'] = float(np.median([distances[i] for i in selected]))
            if (candidate['shop_corner_rms_m'] <= 1 and candidate['scale_difference_fraction'] <= .02
                    and len(selected) >= 12 and candidate['median_annotation_track_distance_m'] <= 3):
                passing.append(candidate)
        report.update(candidates=candidates, printed_scale_m_per_pdf_point=scale,
                      document_id=document['sha256'], application_reference=document['applicationReference'],
                      shop_osm_id=shops[0]['id'], horizontal_crs='EPSG:27700',
                      horizontal_transform_accuracy_m=project.accuracy)
        if len(passing) != 1:
            raise ValueError('Candidate orientation is not uniquely supported by shop, scale and track checks')
        chosen = passing[0]
        report.update(status='shop_track_alignment_hypothesis', candidate=chosen)
        corners = apply_candidate(list(shop_ring.exterior.coords), chosen)
        features.append({'type': 'Feature', 'geometry': mapping(Polygon([inverse.transform(*point) for point in corners])),
                         'properties': {'kind': 'alignment_control_footprint', 'document_id': document['sha256'],
                                        'mapped_object_id': shops[0]['id'], 'registration_verified': False,
                                        'independent_control_objects': 1, 'world_geometry_additions': 0}})
        for index in chosen['matched_annotation_indices']:
            annotation = annotations[index]
            xy = apply_candidate([points[index]], chosen)[0]
            features.append({'type': 'Feature', 'geometry': mapping(Point(inverse.transform(*xy))),
                             'properties': {'kind': 'unregistered_ride_level_annotation',
                                            'point_label': annotation['point_label'], 'printed_level': annotation['printed_level'],
                                            'document_id': document['sha256'], 'vertical_datum': None,
                                            'registration_verified': False, 'world_geometry_additions': 0}})
    except (KeyError, OSError, ValueError, TypeError, IndexError) as error:
        report.update(status='unavailable', reason=str(error))
    (output/'wicker-man-registration.json').write_text(json.dumps(report, indent=2))
    (output/'wicker-man-registration-candidates.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2))
    return report
