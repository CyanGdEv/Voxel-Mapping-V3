"""Source-bound image placements and composited review crops, never object geometry."""
import hashlib
import math
from pathlib import Path

import pymupdf
from shapely.geometry import Polygon, box, mapping

from .building_spec import digest
from .drawing_geometry import native_inverse
from .generation_cycles import atomic_json

VERSION = 'building-raster-view-v1'


def placements(page, sha, number, *, max_images=512):
    """Keep occurrences, including inline images; do not decode embedded pixels."""
    if type(max_images) is not int or not 1 <= max_images <= 512:
        raise ValueError('Bounded image placement inventory required')
    images = page.get_image_info(hashes=False, xrefs=False)
    if len(images) > max_images:
        return {'version': VERSION, 'status': 'image_placement_budget_withheld',
                'placements': [], 'raw_placements': len(images), 'geometry_verified': False}
    inverse = native_inverse(page); rows = []
    for occurrence, image in enumerate(images):
        width, height = image['width'], image['height']
        if width <= 0 or height <= 0: raise ValueError('Positive source image dimensions required')
        transform = pymupdf.Matrix(image['transform'])
        # PDF image placement maps the unit square, not pixel coordinates.
        matrix = pymupdf.Matrix(1/width, 1/height)*transform*inverse
        if (width <= 0 or height <= 0 or not all(math.isfinite(v) for v in matrix)
                or abs(matrix.a*matrix.d-matrix.b*matrix.c) < 1e-15):
            raise ValueError('Nondegenerate image placement required')
        points = [pymupdf.Point(x, y)*matrix for x, y in
                  [(0, 0), (width, 0), (width, height), (0, height)]]
        row = {'document_sha256': sha, 'page': number, 'occurrence_index': occurrence,
               'source_image_number': image['number'], 'size_pixels': [width, height],
               'pixel_edge_to_pdf_native_matrix': list(matrix),
               'geometry': mapping(Polygon([(p.x, p.y) for p in points])),
               'coordinate_frame': 'pdf_native_points_y_up',
               'visibility_verified': False, 'view_assignment_verified': False,
               'physical_geometry_verified': False}
        row['id'] = digest({'version': VERSION, **row}); rows.append(row)
    return {'version': VERSION, 'status': 'source_image_placements_only',
            'placements': rows, 'raw_placements': len(images), 'geometry_verified': False,
            'limitations': ['Placements may be clipped, masked, hidden or overpainted.',
                           'Photographs, textures and neighbouring buildings are not facade geometry.',
                           'Occurrence identity is bound to the original PDF hash, not a decoded image hash.']}


def render(config, resolve, output):
    """Render a declared native review region with a reversible pixel transform."""
    if not isinstance(config, dict) or config.get('version') != VERSION:
        raise ValueError('Versioned raster review request required')
    if set(config)-{'version', 'path', 'sha256', 'page', 'bounds_pdf_native', 'width_pixels','rotation_degrees'}:
        raise ValueError('Unknown raster review field')
    sha = config.get('sha256'); path = Path(resolve(config['path']))
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('Pinned original PDF hash required')
    number = config.get('page'); width = config.get('width_pixels', 1600)
    if type(number) is not int or not 1 <= number <= 10000:
        raise ValueError('Bounded original page required')
    if type(width) is not int or not 200 <= width <= 3000:
        raise ValueError('Bounded raster width required')
    bounds = config.get('bounds_pdf_native')
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError('Finite ordered source review bounds required')
    root = Path(output)
    if root.exists(): raise ValueError('Fresh raster review output required')
    if path.stat().st_size > 32000000: raise ValueError('Original PDF byte budget exceeded')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha: raise ValueError('Original PDF checksum mismatch')
    with pymupdf.open(stream=data, filetype='pdf') as document:
        if number > len(document): raise ValueError('Original source page absent')
        page = document[number-1]
        rotation=config.get('rotation_degrees',page.rotation)
        if type(rotation) is not int or rotation not in (0,90,180,270):
            raise ValueError('Right-angle raster review rotation required')
        page.set_rotation(rotation)
        inverse = native_inverse(page); scope = box(*bounds)
        if not box(*(page.rect*page.derotation_matrix*inverse)).covers(scope): raise ValueError('Review bounds outside original page')
        clip = pymupdf.Rect(bounds)*(~inverse)*page.rotation_matrix; scale = width/clip.width
        if math.ceil(clip.height*scale+2)*math.ceil(clip.width*scale+2) > 9000000:
            raise ValueError('Rendered review pixel budget exceeded')
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                              colorspace=pymupdf.csRGB, alpha=False)
        # Pixmap origins are integer device coordinates after outward rounding.
        pixel_native = pymupdf.Matrix(1, 0, 0, 1, pix.x, pix.y)*pymupdf.Matrix(1/scale, 1/scale)*page.derotation_matrix*inverse
        inventory = placements(page, sha, number)
        png = pix.tobytes('png')
        receipt = {'version': VERSION, 'config_sha256': digest(config),
                   'document_sha256': sha, 'page': number, 'bounds_pdf_native': bounds,
                   'render_rotation_degrees': rotation, 'size_pixels': [pix.width, pix.height],
                   'pixel_edge_to_pdf_native_matrix': list(pixel_native),
                   'png_sha256': hashlib.sha256(png).hexdigest(),
                   'scope_basis': 'declared_review_region_not_verified_view',
                   'source_image_placements': inventory,
                   'geometry_verified': False, 'drawing_state_verified': False,
                   'scale_application_verified': False, 'world_placement_eligible': False,
                   'shared_specs_generated': 0, 'training_labels_generated': 0,
                   'park_world_blocks_added': 0}
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError('Original PDF changed during raster review')
    root.mkdir(parents=True); (root/'view.png').write_bytes(png)
    atomic_json(root/'receipt.json', receipt)
    return receipt
