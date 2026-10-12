"""Build area recipes from independently registered, explicit drawing semantics.

No per-object recipe or binding is required. Unsupported/ambiguous ordinary
annotations stay in the bridge decision ledger; discovery is not a complete
inventory of every physical element in an area.
"""
import json
import math
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform
from .generation_cycles import atomic_json, file_hash

VERSION = 'automatic-drawing-recipes-v4'


def input_contract(config, resolve):
    settings = config.get('automatic_reconstruction', {})
    if not settings.get('enabled'):
        return None
    return {'version': VERSION, 'inputs': {
        key: file_hash(resolve(settings[key]))
        for key in ('manifest', 'references', 'terrain_config')}}


def prepare(config, area, resolve, work, available):
    """Select only this area's acquired PDFs and create a compiler-ready recipe."""
    from .drawing_registration_bridge import run_batch
    settings = config['automatic_reconstruction']
    root = Path(work) / 'automatic-reconstruction'
    root.mkdir(parents=True, exist_ok=True)
    report = {'version': VERSION, 'status': 'awaiting_area_boundary',
              'feature_count': 0, 'world_geometry_additions': 0,
              'inventory_scope': 'supported discovered elements; not complete area inventory'}
    def finish():
        atomic_json(root / 'automatic-report.json', report)
        return None, report
    if not area.get('bounds') or not area.get('bounds_crs'):
        return finish()
    manifest_path = resolve(settings['manifest'])
    manifest = json.loads(manifest_path.read_text())
    sources = {s['id']: s for s in manifest['sources']}
    # Bind by acquired content hash, not a title, nearest label or shared filename.
    documents = [{'source_id': s['id'], 'file': str((Path(work) / 'corpus/files' / (s['sha256'] + '.pdf')).resolve())}
                 for s in sources.values() if s.get('sha256') in available and s['kind'] in ('planning', 'cad')]
    if not documents:
        report['status'] = 'awaiting_source_policy'
        return finish()
    documents_file = root / 'documents.json'
    atomic_json(documents_file, documents)
    bridge = run_batch(documents_file, manifest_path, resolve(settings['references']), root / 'bridge',
                       max_pages=settings.get('max_pages', 10000), max_features=settings.get('max_features', 2500000),
                       knowledge_store=resolve(settings['knowledge_store']) if settings.get('knowledge_store') else
                           Path(work).parent/'evidence-memory.sqlite')
    report['bridge'] = bridge
    bounds = area['bounds']
    if (len(bounds) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError('Nonempty automatic area bounds required')
    boundary = transform(Transformer.from_crs(area['bounds_crs'], manifest['crs'], always_xy=True).transform, box(*bounds))
    features = []; outside = []
    for line in (root / 'bridge/features.jsonl').read_text().splitlines():
        feature = json.loads(line)
        if boundary.buffer(1e-7).covers(shape(feature['geometry'])):
            features.append(feature)
        else:
            outside.append(feature['id'])
    report.update(feature_count=len(features), outside_area_feature_ids=outside,
                  status='recipe_ready' if features else 'awaiting_registered_semantics')
    if not features:
        return finish()
    feature_path = root / 'features.jsonl'
    payload = ''.join(json.dumps(f, sort_keys=True) + '\n' for f in features)
    recipe = {'manifest': str((root / 'bridge/manifest.json').resolve()),
              'feature_records': str(feature_path.resolve()),
              'terrain_config': str(resolve(settings['terrain_config'])),
              'work_directory': 'compiled', 'allow_estimates': False}
    recipe_path = root / 'recipe.json'
    # Resume must not silently repair edited derived inputs already dispatched.
    if feature_path.exists() and feature_path.read_text() != payload:
        raise ValueError('Automatic feature output changed')
    if recipe_path.exists() and json.loads(recipe_path.read_text()) != recipe:
        raise ValueError('Automatic recipe output changed')
    feature_path.write_text(payload)
    atomic_json(recipe_path, recipe)
    report.update(recipe_sha256=file_hash(recipe_path), features_sha256=file_hash(feature_path),
                  discovered_component_ids=[f['id'] for f in features])
    atomic_json(root / 'automatic-report.json', report)
    return recipe_path, report
