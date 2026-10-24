"""Portable source-crop/trace pairs from retained, explicitly scoped study reviews."""
from collections import Counter
from concurrent.futures import CancelledError
from html import escape
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'retained-study-dataset-v1'
MAX_RECORDS = 2048
MAX_PDF_BYTES = 32_000_000
MAX_OUTPUT_BYTES = 128_000_000
MAX_RENDER_PIXELS = 8_000_000
IMAGE_SIZE = 128
LEVELS = {'reviewed_source_trace', 'source_extracted_profile'}


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def connected_groups(records):
    """Same physical identity and every shared input PDF stay together."""
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError('Bounded component records required')
    parent = list(range(len(records)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, row in enumerate(records):
        for key in (('building', row['building_id']), ('source', row['source']['document_sha256'])):
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    components = {}
    for i, row in enumerate(records):
        components.setdefault(find(i), []).append(row)
    result = []
    for rows in components.values():
        buildings = sorted({r['building_id'] for r in rows})
        sources = sorted({r['source']['document_sha256'] for r in rows})
        group_id = digest({'building_ids': buildings, 'source_sha256': sources})
        result.append({'group_id': group_id, 'building_ids': buildings,
            'source_sha256': sources, 'record_ids': sorted(r['id'] for r in rows)})
    return sorted(result, key=lambda r: r['group_id'])


def _geometry(value):
    from shapely.geometry import shape
    if not isinstance(value, dict) or value.get('type') not in ('Polygon', 'LineString', 'Point', 'MultiPoint'):
        raise ValueError('Source-local polygon, trace or point target required')
    def coords(value):
        if not isinstance(value, (list, tuple)):
            raise ValueError('Finite bounded target coordinates required')
        if len(value) == 2 and all(type(v) in (int, float) for v in value):
            if any(not math.isfinite(v) or abs(v) > 100000 for v in value):
                raise ValueError('Finite bounded target coordinates required')
            return 1
        return sum(coords(v) for v in value)
    if coords(value.get('coordinates')) > 16384:
        raise ValueError('Source target vertex budget exceeded')
    geometry = shape(value)
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError('Valid nonempty source target required')
    return geometry


def _validate_catalogue(catalogue):
    rows = catalogue.get('records') if isinstance(catalogue, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RECORDS:
        raise ValueError('Bounded retained study catalogue required')
    if len(json.dumps(catalogue, allow_nan=False).encode()) > 8_000_000:
        raise ValueError('Study catalogue byte budget exceeded')
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not row['id'] or len(row['id']) > 200 or row['id'] in ids
                or not isinstance(row.get('building_id'), str) or not row['building_id']
                or not isinstance(row.get('kind'), str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}', row['kind'])
                or not isinstance(row.get('assumptions'), list)
                or any(not isinstance(v, str) for v in row['assumptions'])):
            raise ValueError('Unique bounded study record, class and assumptions required')
        ids.add(row['id'])
        source = row.get('source', {})
        if (not re.fullmatch('[0-9a-f]{64}', str(source.get('document_sha256')))
                or type(source.get('page')) is not int or not 1 <= source['page'] <= 10000
                or source.get('coordinate_frame') not in ('render_pixels', 'page_points', 'native_y_up')):
            raise ValueError('Pinned source page and explicit coordinate frame required')
        if not row.get('review_refs'):
            raise ValueError('Retained source review references required')
        for ref in row['review_refs']:
            if (not isinstance(ref, dict) or not isinstance(ref.get('path'), str)
                    or not re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256')))
                    or not isinstance(ref.get('pointer'), str)):
                raise ValueError('Pinned review document and exact JSON pointer required')
        _geometry(row.get('target_geometry'))
    return rows


def _render(page, source):
    import pymupdf
    from PIL import Image
    width = source.get('render_width_pixels', 1800)
    if type(width) is not int or not 200 <= width <= 4000 or page.rect.width <= 0:
        raise ValueError('Bounded full-page raster required')
    scale = width/page.rect.width
    if page.rect.height*scale*width > MAX_RENDER_PIXELS:
        raise ValueError('Source raster exceeds pixel budget')
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
    if pix.width*pix.height > MAX_RENDER_PIXELS:
        raise ValueError('Source raster exceeds pixel budget')
    if source.get('render_size_pixels') is not None and source['render_size_pixels'] != [pix.width, pix.height]:
        raise ValueError('Retained source raster dimensions changed')
    raw_sha = hashlib.sha256(pix.samples).hexdigest()
    if source.get('render_samples_sha256') and source['render_samples_sha256'] != raw_sha:
        raise ValueError('Retained source raster pixels changed')
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L'), raw_sha, scale


def _to_pixels(geometry, page, source, scale):
    import pymupdf
    from shapely.ops import transform
    frame = source['coordinate_frame']
    if frame == 'render_pixels':
        return geometry
    if frame == 'page_points':
        matrix = page.rotation_matrix*pymupdf.Matrix(scale, scale)
    else:
        from .drawing_page_tools import native_to_render_pixels
        matrix = pymupdf.Matrix(native_to_render_pixels(page, source.get('render_width_pixels', 1800)))
    def apply(x, y, z=None):
        try:
            points = [pymupdf.Point(a, b)*matrix for a, b in zip(x, y)]
            return [p.x for p in points], [p.y for p in points]
        except TypeError:
            p = pymupdf.Point(x, y)*matrix
            return p.x, p.y
    return transform(apply, geometry)


def _pair(image, geometry):
    from PIL import Image, ImageDraw
    bounds = geometry.bounds
    if any(not math.isfinite(v) for v in bounds):
        raise ValueError('Finite source crop required')
    if bounds[0] < -.01 or bounds[1] < -.01 or bounds[2] > image.width+.01 or bounds[3] > image.height+.01:
        raise ValueError('Source target extends outside original page')
    padding = max(4., .12*max(bounds[2]-bounds[0], bounds[3]-bounds[1]))
    box = [max(0, math.floor(bounds[0]-padding)), max(0, math.floor(bounds[1]-padding)),
        min(image.width, math.ceil(bounds[2]+padding)), min(image.height, math.ceil(bounds[3]+padding))]
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError('Nonempty source crop required')
    crop = image.crop(box)
    ratio = min(IMAGE_SIZE/crop.width, IMAGE_SIZE/crop.height)
    w, h = max(1, round(crop.width*ratio)), max(1, round(crop.height*ratio))
    x, y = (IMAGE_SIZE-w)//2, (IMAGE_SIZE-h)//2
    result = Image.new('L', (IMAGE_SIZE, IMAGE_SIZE), 255)
    result.paste(crop.resize((w, h), Image.Resampling.LANCZOS), (x, y))
    mask = Image.new('L', (IMAGE_SIZE, IMAGE_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    sx, sy = w/crop.width, h/crop.height
    def points(values):
        return [(x+(a-box[0])*sx, y+(b-box[1])*sy) for a, b in values]
    if geometry.geom_type == 'Polygon':
        draw.polygon(points(geometry.exterior.coords), fill=255)
        for ring in geometry.interiors:
            draw.polygon(points(ring.coords), fill=0)
    elif geometry.geom_type == 'LineString':
        draw.line(points(geometry.coords), fill=255, width=1)
    else:
        pts = list(geometry.geoms) if geometry.geom_type == 'MultiPoint' else [geometry]
        for point in pts:
            px, py = points(point.coords)[0]
            draw.ellipse((px-1, py-1, px+1, py+1), fill=255)
    return result, mask, {'full_render_crop_pixels': box,
        'crop_to_input_matrix': [sx, 0., 0., sy, x-box[0]*sx, y-box[1]*sy],
        'input_size_pixels': [IMAGE_SIZE, IMAGE_SIZE],
        'input_source': 'unchanged original page crop, grayscale and aspect-preserving resize; no target overlay'}



def _retain_reviews(catalogue, repo_root, root):
    import shutil
    pins = catalogue.get('input_sha256')
    if not isinstance(pins, dict) or not 1 <= len(pins) <= 128:
        raise ValueError('Pinned retained review asset inventory required')
    total = 0
    values = {}
    for relative, expected in pins.items():
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or '..' in Path(relative).parts or '\\' in relative
                or not re.fullmatch('[0-9a-f]{64}', str(expected))):
            raise ValueError('Safe pinned retained review asset path required')
        path = (repo_root/relative).resolve()
        if not path.is_relative_to(repo_root) or not path.is_file() or path.stat().st_size > 8_000_000:
            raise ValueError('Bounded existing retained review asset required')
        raw = path.read_bytes();total += len(raw)
        if total > 32_000_000 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Retained review asset checksum changed or byte budget exceeded')
        if path.suffix.lower() in ('.json', '.geojson'):
            values[relative] = json.loads(raw)
        target = root/'reviews'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if file_hash(target) != expected or file_hash(path) != expected:
            raise ValueError('Retained review asset changed while copying')
    for row in catalogue['records']:
        for ref in row['review_refs']:
            relative = ref['path']
            if pins.get(relative) != ref['sha256']:
                raise ValueError('Source review reference pin is absent or inconsistent')
            if relative not in values:
                if ref['pointer']:
                    raise ValueError('JSON pointer requires a JSON review asset')
                continue
            value = values[relative]
            pointer = ref['pointer']
            if pointer and not pointer.startswith('/'):
                raise ValueError('Exact source review JSON pointer required')
            try:
                for token in pointer.split('/')[1:] if pointer else []:
                    key = token.replace('~1', '/').replace('~0', '~')
                    value = value[int(key)] if isinstance(value, list) else value[key]
            except (KeyError, IndexError, ValueError, TypeError) as error:
                raise ValueError('Source review JSON pointer is absent') from error
    return pins


def build(catalogue, source_directory, output, *, repo_root=None, cancelled=lambda: False, progress=lambda value: None):
    """Missing/stale source pairs stay explicit; no guessed positive decisions."""
    import pymupdf
    rows = _validate_catalogue(catalogue)
    repo_root = Path(repo_root if repo_root is not None else Path(__file__).resolve().parents[1]).resolve()
    source_directory, output = Path(source_directory), Path(output)
    if output.exists():
        raise ValueError('Fresh study dataset output required')
    def check():
        if cancelled():
            raise CancelledError('Study dataset export cancelled')
    check()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-dataset-', dir=output.parent) as temporary:
        root = Path(temporary)/'output';root.mkdir()
        _retain_reviews(catalogue, repo_root, root)
        exported, withheld = [], []
        batches = {}
        for row in rows:
            source = row['source']
            key = (source['document_sha256'], source['page'], source.get('render_width_pixels', 1800),
                source.get('render_samples_sha256'), tuple(source.get('render_size_pixels') or []))
            batches.setdefault(key, []).append(row)
        for number, (key, batch) in enumerate(batches.items()):
            check()
            sha, page_number, _, _, _ = key
            progress({'progress': .05+.85*number/len(batches), 'message': 'Pairing source page '+str(number+1)+' of '+str(len(batches))})
            path = source_directory/(sha+'.pdf')
            try:
                if not path.is_file():
                    raise ValueError('Original source PDF is missing')
                if path.stat().st_size > MAX_PDF_BYTES or file_hash(path) != sha:
                    raise ValueError('Original source PDF checksum changed or byte budget exceeded')
                with pymupdf.open(path) as document:
                    if not 1 <= page_number <= len(document):
                        raise ValueError('Original source page missing')
                    page = document[page_number-1]
                    # Original PDF bytes are never rewritten. Unsupported units
                    # cannot be silently treated as standard PDF point units.
                    unit = document.xref_get_key(page.xref, 'UserUnit')
                    if unit[0] not in ('null', 'int', 'real') or (unit[0] != 'null' and float(unit[1]) != 1.):
                        raise ValueError('Non-default source UserUnit unsupported')
                    image, render_sha, scale = _render(page, batch[0]['source'])
                    for row in batch:
                        check()
                        if row['evidence_level'] not in LEVELS:
                            withheld.append({'id': row['id'], 'reason': 'conditional_or_illustrative_target_excluded'})
                            continue
                        try:
                            geometry = _to_pixels(_geometry(row['target_geometry']), page, row['source'], scale)
                            crop, mask, transform = _pair(image, geometry)
                        except ValueError as error:
                            withheld.append({'id': row['id'], 'reason': str(error)})
                            continue
                        directory = root/'examples'/digest(row['id'])[:24];directory.mkdir(parents=True)
                        crop.save(directory/'input.png');mask.save(directory/'target-mask.png')
                        target = {'source_geometry': row['target_geometry'], 'source_coordinate_frame': row['source']['coordinate_frame'],
                            'render_geometry': geometry.__geo_interface__, 'crop_transform': transform,
                            'supervision_scope': 'reviewed drawing geometry/class only; not surveyed or complete physical reconstruction'}
                        atomic_json(directory/'target.json', target)
                        record = {**copy.deepcopy(row), **transform,
                            'input_file': (directory/'input.png').relative_to(root).as_posix(),
                            'input_sha256': file_hash(directory/'input.png'),
                            'target_mask_file': (directory/'target-mask.png').relative_to(root).as_posix(),
                            'target_mask_sha256': file_hash(directory/'target-mask.png'),
                            'target_file': (directory/'target.json').relative_to(root).as_posix(),
                            'target_sha256': file_hash(directory/'target.json'),
                            'source_render_samples_sha256': render_sha, 'original_pdf_verified': True,
                            'learning_eligible': True, 'physical_geometry_verified': False, 'world_placement_eligible': False}
                        record['record_sha256'] = digest(record)
                        exported.append(record)
                    image.close()
                if file_hash(path) != sha:
                    raise ValueError('Original source changed during dataset export')
            except (ValueError, OSError, RuntimeError) as error:
                # Discard all pairs from a source batch if its original changes.
                batch_ids = {row['id'] for row in batch}
                exported = [row for row in exported if row['id'] not in batch_ids]
                for row in batch:
                    directory = root/'examples'/digest(row['id'])[:24]
                    if directory.exists():
                        import shutil
                        shutil.rmtree(directory)
                    withheld.append({'id': row['id'], 'reason': str(error)})
            if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) > MAX_OUTPUT_BYTES:
                raise ValueError('Study dataset output byte budget exceeded')
        groups = connected_groups(exported)
        group_map = {rid: group['group_id'] for group in groups for rid in group['record_ids']}
        for row in exported:
            row['group_id'] = group_map[row['id']]
            row['record_sha256'] = digest({k: v for k, v in row.items() if k != 'record_sha256'})
        result = {'version': VERSION, 'dataset_kind': 'previously_inspected_retained_sources',
            'status': 'source_paired_dataset_ready' if not withheld else 'source_paired_dataset_with_gaps',
            'records': exported, 'groups': groups, 'withheld': withheld,
            'excluded': copy.deepcopy(catalogue.get('excluded', [])),
            'input_sha256': catalogue.get('input_sha256', {}), 'documents': catalogue.get('documents', []),
            'summary': {'source_paired_examples': len(exported), 'source_groups': len(groups),
                'building_or_object_identities': len({r['building_id'] for r in exported}),
                'original_pdfs_verified': len({r['source']['document_sha256'] for r in exported}),
                'kinds': dict(sorted(Counter(r['kind'] for r in exported).items())),
                'withheld_examples': len(withheld)},
            'physical_geometry_verified': False, 'world_placement_eligible': False,
            'whole_building_feedback_records_generated': 0, 'model_weights_updated': False,
            'limitations': ['Targets describe reviewed source drawing geometry, not measured complete physical buildings.',
                'Input crops use reference bounding boxes; a crop classifier still needs independently proposed regions at inference.',
                'All variants of a building and every shared source PDF stay in the same evaluation group.',
                'Metric dimensions, 3D joins, hidden faces, heights and geographic alignment retain their original assumptions.',
                'No whole-building acceptance decision or current-ranker feedback is inferred from successful export.']}
        atomic_json(root/'catalogue.json', catalogue)
        _write_index(root, result)
        result['output_sha256'] = {p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob('*')) if p.is_file()}
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) + len(json.dumps(result, allow_nan=False).encode()) > MAX_OUTPUT_BYTES:
            raise ValueError('Study dataset final output byte budget exceeded')
        result['id'] = digest(result)
        atomic_json(root/'dataset.json', result)
        check()
        if output.exists():
            raise ValueError('Fresh study dataset output required')
        root.rename(output)
    progress({'progress': 1., 'message': 'Retained source-paired dataset ready'})
    return result


def _write_index(root, result):
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Retained study learning examples</title>',
        '<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}article{border:1px solid #bcc8d1;padding:1rem}img{width:128px;height:128px;image-rendering:pixelated}small{overflow-wrap:anywhere}</style>',
        '<h1>Retained study learning examples</h1><p>Original source crops beside reviewed target masks. '
        'These are drawing-level labels; metric and 3D assumptions remain separate. Crops are provided reference regions, not automatic detections.</p>',
        '<p>'+str(len(result['records']))+' examples; '+str(len(result['groups']))+' independent source-connected groups. '
        '<a href="dataset.json">Dataset, source pins and exclusions</a></p><div class="grid">']
    for row in result['records']:
        body.append('<article><strong>'+escape(row['kind'])+'</strong><p>'+escape(row['building_id'])+'</p><img alt="Original source crop" src="'+escape(row['input_file'], quote=True)+'"> <img alt="Reviewed drawing target mask" src="'+escape(row['target_mask_file'], quote=True)+'"><p><a href="'+escape(row['target_file'], quote=True)+'">Exact source geometry</a></p><small>'+escape(row['id'])+'</small></article>')
    body.append('</div><h2>Explicit gaps</h2><ul>')
    for row in result['withheld']:
        body.append('<li>'+escape(row['id'])+': '+escape(row['reason'])+'</li>')
    body.append('</ul><p>No whole-building decisions or model weights are generated by preparing these pairs.</p></html>')
    (root/'index.html').write_text(''.join(body), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from .retained_study_examples import catalogue
    report = build(catalogue(args.repo), args.sources, args.output, repo_root=args.repo)
    print(json.dumps({'status': report['status'], **report['summary']}))


if __name__ == '__main__':
    main()
