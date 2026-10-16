"""Retain proposed level annotations without treating their text as surveyed grading."""
import math
import re

from pyproj import CRS
from shapely.geometry import Point, shape

from .horizontal_grid import OSTN15Transform
from .wicker_registration import apply_candidate


def extract(pdf, sha, placement, operation, local_crs, terrain, footprints, review_floor):
    """Locate literal +/FFL claims; polygon containment is only a candidate link."""
    import pymupdf
    with pymupdf.open(pdf) as document:
        if len(document) != 1 or document[0].rotation:
            raise ValueError('One unrotated page required for proposed level review')
        blocks = document[0].get_text('rawdict')['blocks']
    lines = [line for block in blocks for line in block.get('lines', [])]
    if len(lines) > 10_000 or sum(len(s['chars']) for line in lines for s in line['spans']) > 500_000:
        raise ValueError('Planning level annotation budget exceeded')
    polygons = {f['id']: shape(f['geometry']) for f in footprints}
    coordinate = OSTN15Transform(CRS.from_user_input(local_crs), 27700, operation)
    claims = []
    for line in lines:
        chars = [c for span in line['spans'] for c in span['chars']]
        text = ''.join(c['c'] for c in chars).strip()
        match = re.fullmatch(r'(\+|FFL\s+)\s*(\d{3}\.\d{1,2})', text)
        if not match:
            continue
        if len(claims) >= 128:
            raise ValueError('Planning level claim budget exceeded')
        floor = match[1] != '+'
        rectangle = line['bbox'] if floor else next(c['bbox'] for c in chars if c['c'] == '+')
        x, y = (rectangle[0]+rectangle[2])/2, (rectangle[1]+rectangle[3])/2
        east, north = apply_candidate([[x,y]], placement['candidate'])[0]
        lx, lz = coordinate.inverse(east,north)
        links = sorted(identifier for identifier, polygon in polygons.items() if polygon.covers(Point(x,y))) if not floor else []
        ground = terrain.get((math.floor(lx),math.floor(lz)))
        value = float(match[2])
        claims.append({'id': f'proposed-level/{len(claims):03d}', 'text': text, 'printed_value_m': value,
            'claim_kind': 'finished_floor_text' if floor else 'proposed_plus_level_text',
            'bbox_pdf_points': list(line['bbox']), 'annotation_point_pdf_points': [x,y],
            'position_basis': 'text-box centre; not a building anchor' if floor else 'literal plus glyph centre; not a surveyed marker',
            'annotation_point_local_xz_m': [float(lx),float(lz)],
            'source_paving_candidates': links,
            'association_status': 'floor_role_unverified' if floor else 'one_containing_source_polygon' if len(links)==1
                else 'overlapping_source_polygons' if links else 'no_containing_source_polygon',
            'terrain_surface_block_y': ground,
            'printed_minus_terrain_walking_top_m': value-ground-1 if ground is not None else None,
            'printed_minus_review_floor_m': value-review_floor if floor else None,
            'physical_surface_identity_verified': False, 'vertical_datum_verified': False,
            'visibility_independently_verified': False, 'applied_to_world': False})
    return {'version':'proposed-paving-level-evidence-v1', 'source_document_sha256':sha, 'source_page':1,
        'status':'retained_unverified_annotations', 'claims':claims,
        'proposed_plus_claims':sum(c['claim_kind']=='proposed_plus_level_text' for c in claims),
        'floor_claims':sum(c['claim_kind']=='finished_floor_text' for c in claims),
        'review_floor_m':review_floor, 'review_floor_datum_verified':False,
        'absolute_finished_levels_applied':0, 'world_geometry_additions':0,
        'accepted_physical_geometry':False, 'training_labels_generated':0,
        'limitations':['Text positions and containing polygons are candidate associations, not leader/spot-marker or physical identity verification.',
                       'Proposed drawing levels and the retained review floor do not establish a common verified datum or present-day finished levels.',
                       'No offset, interpolation, terrain regrade or floor change is inferred from these claims.']}
