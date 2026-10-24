"""Bounded, source-pinned Bedrock downloads for conditional planning massing."""
from concurrent.futures import CancelledError
from html import escape
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from . import building_spec, planning_design_dimensions, planning_design_massing as massing
from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'planning-world-preview-v1'
MAX_WORLDS = 8
MAX_REVIEW_BYTES = 8_000_000
MAX_PLATFORM_CELLS = 25_000
MAX_WORLD_BLOCKS = 150_000
MAX_ARCHIVE_BYTES = 128_000_000
DIMENSION = 'minecraft:overworld'


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate(config):
    if (not isinstance(config, dict)
            or set(config)-{'version', 'review_path', 'review_sha256', 'alternative_ids'}
            or config.get('version') != VERSION
            or not isinstance(config.get('review_path'), str) or not config['review_path']
            or not re.fullmatch('[0-9a-f]{64}', str(config.get('review_sha256')))):
        raise ValueError('Versioned pinned planning massing review required')
    if 'alternative_ids' in config:
        ids = config['alternative_ids']
        if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_WORLDS
                or any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in ids)
                or len(ids) != len(set(ids))):
            raise ValueError('Choose at most eight unique alternative IDs, retaining both spacing rivals')
    return config


def _read_review(config):
    path = Path(config['review_path'])
    if not path.is_file() or path.stat().st_size > MAX_REVIEW_BYTES:
        raise ValueError('Bounded existing design massing review required')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != config['review_sha256']:
        raise ValueError('Planning design massing review changed')
    def invalid(value):
        raise ValueError('Nonfinite review value: '+value)
    review = json.loads(data.decode('utf-8'), parse_constant=invalid)
    if (not isinstance(review, dict) or review.get('version') != massing.VERSION
            or review.get('id') != digest({k: v for k, v in review.items() if k != 'id'})
            or review.get('analysis_complete') is not True
            or review.get('world_placement_eligible') is not False
            or review.get('physical_height_verified') is not False
            or review.get('ground_datum_verified') is not False
            or review.get('world_geometry_additions') != 0
            or review.get('training_labels_generated') != 0
            or review.get('model_weights_updated') is not False
            or not isinstance(review.get('alternatives'), list)
            or not 1 <= len(review['alternatives']) <= massing.LIMITS['max_alternatives']):
        raise ValueError('Exact current complete conditional design massing review required')
    inventory = {}
    for row in review['alternatives']:
        if not isinstance(row, dict) or not re.fullmatch('[0-9a-f]{64}', str(row.get('id'))) or row['id'] in inventory:
            raise ValueError('Unique current massing alternatives required')
        inventory[row['id']] = row
    ids = config.get('alternative_ids', list(inventory))
    if len(ids) > MAX_WORLDS:
        raise ValueError('At most eight preview worlds per job; choose complete spacing pairs with alternative_ids')
    if any(identifier not in inventory for identifier in ids):
        raise ValueError('Requested alternative is absent from the pinned review')
    selected = [row for row in review['alternatives'] if row['id'] in ids]
    groups = {}
    for row in selected:
        # Reconstruct the current canonical specification from the retained claim.
        # A re-signed review cannot substitute arbitrary mesh geometry for a row.
        claim = row.get('source_claim')
        if (not isinstance(claim, dict) or row.get('source_claim_id') != claim.get('id')
                or row.get('source_claim_sha256') != digest(claim)
                or not re.fullmatch('[0-9a-f]{64}', str(row.get('source_page_sha256')))):
            raise ValueError('Exact pinned source dimension claim required')
        page = {'version': planning_design_dimensions.VERSION,
            'document_sha256': row.get('document_sha256'), 'page': row.get('page'),
            'analysis_complete': True, 'claims': [claim]}
        page['id'] = digest(page)
        expected = massing.review_pages([page])
        matches = [r for r in expected['alternatives'] if r['id'] == row['id']]
        if len(matches) != 1:
            raise ValueError('Current source dimension interpretation required')
        canonical = matches[0]
        key = row['document_sha256']+':'+str(row['page'])
        pin = review.get('source_pages', {}).get(key, {})
        if pin.get('sha256') != row['source_page_sha256'] or pin.get('analysis_complete') is not True:
            raise ValueError('Complete source page evidence pin required')
        canonical['spec']['sources'][0]['source_evidence_sha256'] = row['source_page_sha256']
        if (row.get('spec') != canonical['spec'] or row.get('spec_sha256') != digest(canonical['spec'])
                or any(row.get(k) != canonical[k] for k in ('spacing_interpretation',
                    'overall_nominal_extents_m', 'clear_row_gap_m', 'physical_height_verified',
                    'ground_datum_verified', 'local_ground_zero_assumed', 'ridge_geometry_generated',
                    'individual_cabins_generated', 'world_placement_eligible'))):
            raise ValueError('Exact current source-derived massing specification required')
        group = (row['document_sha256'], row['page'], row['source_claim_id'])
        groups.setdefault(group, []).append(row)
    for rows in groups.values():
        if (len(rows) != 2 or {r['spacing_interpretation'] for r in rows}
                != {'clear_gap', 'row_centre_separation'}):
            raise ValueError('Retain both spacing rivals for each selected source claim')
    return review, selected


def _spawn_check(path, expected_spawn):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    wrapper = LevelDBFormat(str(path))
    wrapper.open()
    try:
        tag = wrapper.root_tag.compound
        spawn = [int(tag[k]) for k in ('SpawnX', 'SpawnY', 'SpawnZ')]
        if spawn != list(expected_spawn):
            raise ValueError('Saved preview spawn metadata changed')
        x, y, z = spawn
        chunk = wrapper.load_chunk(x//16, z//16, DIMENSION)
        blocks = [chunk.block_palette[int(chunk.blocks[x%16, h, z%16])] for h in (y-1, y, y+1)]
        if blocks[0].namespaced_name != 'universal_minecraft:grass_block' or any(b.base_name != 'air' for b in blocks[1:]):
            raise ValueError('Saved preview spawn lacks supporting ground or two empty headroom blocks')
        return {'verified': True, 'spawn': spawn, 'support': 'grass_block',
            'headroom_air_blocks': 2, 'metadata_verified': True,
            'player_movement_verified': False}
    finally:
        wrapper.close()


def _verify_archive(package, world_path, world, cancelled):
    # Compare every packaged byte with the fully read-back writer output, then
    # independently open the extracted database and recheck spawn and coverage.
    from amulet.level.formats.leveldb_world import LevelDBFormat
    with zipfile.ZipFile(package) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        expected = {p.relative_to(world_path).as_posix(): p
            for p in world_path.rglob('*') if p.is_file() and p.name != 'LOCK'}
        if (len(names) != len(set(names)) or set(names) != set(expected)
                or 'level.dat' not in names or not any(n.startswith('db/') for n in names)
                or len(names) > 2048 or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES
                or archive.testzip() is not None):
            raise ValueError('Preview world archive integrity failed')
        if any(Path(n).is_absolute() or '..' in Path(n).parts or '\\' in n for n in names):
            raise ValueError('Unexpected preview archive path')
        for name, path in expected.items():
            if cancelled():
                raise CancelledError('Planning world preview cancelled')
            if hashlib.sha256(archive.read(name)).hexdigest() != _sha(path):
                raise ValueError('Packaged world differs from verified saved world')
        with tempfile.TemporaryDirectory(prefix='voxel-preview-readback-') as directory:
            archive.extractall(directory)
            spawn = _spawn_check(directory, world['spawn'])
            wrapper = LevelDBFormat(directory)
            wrapper.open()
            try:
                coordinates = sorted(wrapper.all_chunk_coords(DIMENSION))
                if len(coordinates) != world['chunks']:
                    raise ValueError('Packaged saved world lost chunk coverage')
                for cx, cz in coordinates:
                    if cancelled():
                        raise CancelledError('Planning world preview cancelled')
                    wrapper.load_chunk(cx, cz, DIMENSION)
            finally:
                wrapper.close()
    return {'crc_verified': True, 'saved_world_reopened': True,
        'packaged_files_match_verified_world': True, 'verified_files': len(names),
        'chunks_reopened': len(coordinates), 'spawn_rechecked': spawn['verified']}


def run(config, output, *, cancelled=lambda: False, progress=lambda value: None):
    validate(config)
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh planning world preview output required')
    def check():
        if cancelled():
            raise CancelledError('Planning world preview cancelled')
    check()
    review, selected = _read_review(config)
    from . import building_native, bedrock
    check()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='planning-world-preview-', dir=output.parent) as temporary:
        root = Path(temporary)/'output'
        root.mkdir()
        worlds = []
        for index, alternative in enumerate(selected):
            check()
            progress({'progress': .05+.85*index/len(selected),
                'message': 'Exporting conditional spacing preview '+str(index+1)+' of '+str(len(selected))})
            cells, audit = building_native.compile_spec(alternative['spec'])
            check()
            low = [min(p[i] for p in cells) for i in range(3)]
            high = [max(p[i] for p in cells) for i in range(3)]
            ground = low[1]-1
            minx, maxx, minz, maxz = low[0]-8, high[0]+9, low[2]-8, high[2]+9
            if (maxx-minx)*(maxz-minz) > MAX_PLATFORM_CELLS:
                raise ValueError('Preview flat platform exceeds bounded area budget')
            stem = 'preview-'+str(index).zfill(3)+'-'+alternative['spacing_interpretation'].replace('_', '-')
            directory = root/stem
            directory.mkdir()
            spec = alternative['spec']
            atomic_json(directory/'spec.json', spec)
            rows = [{'x': x, 'y': y, 'z': z, 'kind': 'structure', 'material': material,
                'feature': spec['building_id']} for (x, y, z), material in sorted(cells.items())]
            rows.extend({'x': x, 'y': ground, 'z': z, 'kind': 'terrain', 'material': 'grass_block'}
                for x in range(minx, maxx) for z in range(minz, maxz))
            voxel = directory/'voxels.jsonl'
            with voxel.open('w', encoding='utf-8', newline='\n') as stream:
                for row in rows:
                    stream.write(json.dumps(row, sort_keys=True)+'\n')
            spawn_local = [low[0]-4, ground+1, math.floor((low[2]+high[2])/2)]
            report = {'version': VERSION, 'status': 'conditional_local_surface_world_preview',
                'voxel_size_m': 1, 'model_blocks_per_source_metre': 1, 'crs': None,
                'vertical_datum': 'STUDY_ZERO', 'geographic_registration': None,
                'spawn_local_xyz_m': spawn_local, 'alternative_id': alternative['id'],
                'spacing_interpretation': alternative['spacing_interpretation'],
                'source_review_sha256': config['review_sha256'], 'source_review_id': review['id'],
                'source_spec_sha256': alternative['spec_sha256'], 'spec_sha256': alternative['spec_sha256'], 'source_claim': alternative['source_claim'],
                'planning_sources': spec['sources'], 'source_nominal_extents_m': alternative['overall_nominal_extents_m'],
                'native_bounds_xyz': [low, high], 'native_audit': audit,
                'horizontal_transform': {'minecraft_x': 'local model X',
                    'minecraft_z': 'negative local model Y (depth); not surveyed north'},
                'coordinate_transform': {'minecraft_x': 'local model X',
                    'minecraft_z': 'negative local model Y (depth); not surveyed north',
                    'minecraft_y': 'local model Z (height) plus display offset'},
                'physical_height_verified': False, 'ground_datum_verified': False,
                'world_placement_eligible': False, 'park_world_blocks_added': 0,
                'training_labels_generated': 0, 'model_weights_updated': False,
                'ridge_geometry_generated': False, 'individual_cabins_generated': False,
                'limitations': [*review['limitations'], *audit['limitations'],
                    'The source 3D solids become sampled block surfaces, not exact solid-volume voxel filling.',
                    'One block per source metre is scale, not exact sub-metre boundary precision; native bounds are reported separately.',
                    'Flat grass and its artificial foundation are display terrain; spawn is outside the row surfaces.',
                    'The top of each row envelope is a display boundary, not a reconstructed canopy or supported roof.',
                    'Minecraft import, gameplay and physical fidelity have not been tested.']}
            def saved_check(path, offset, spawn):
                check()
                report['spawn_validation'] = _spawn_check(path, spawn)
                if low[0] <= spawn[0] <= high[0]:
                    raise ValueError('Preview spawn must be outside the row geometry')
                atomic_json(path/'preview-source-spec.json', spec)
                atomic_json(path/'preview-source-claim.json', alternative['source_claim'])
                (path/'PREVIEW-README.txt').write_text(
                    'Conditional planning row-group surface preview. '+alternative['spacing_interpretation']+'.\n'
                    'Local flat display terrain, 1 block per source metre; no surveyed park placement.\n'
                    'Surface block rounding changes fine dimensions. No canopy, openings or paths reconstructed.\n'
                    'Both spacing alternatives are provided separately; neither is selected as physical truth.\n', encoding='utf-8')
            world = bedrock.export_world(voxel, directory, report,
                name='Conditional rows: '+alternative['spacing_interpretation'].replace('_', ' '),
                max_blocks=MAX_WORLD_BLOCKS, ground_depth=4, post_export_check=saved_check)
            check()
            archive = _verify_archive(directory/world['file'], directory/'bedrock-world', world, cancelled)
            filename = stem+'.mcworld'
            shutil.move(directory/world['file'], root/filename)
            world = {**world, 'file': filename,
                'horizontal_transform': report['horizontal_transform']}
            entry = {**report, 'file': filename, 'audit_file': stem+'/quality-report.json',
                'world': world, 'archive_validation': archive}
            atomic_json(directory/'quality-report.json', entry)
            # Keep only the portable download, source spec, voxel intent and audit.
            shutil.rmtree(directory/'bedrock-world')
            worlds.append(entry)
        check()
        result = {'version': VERSION, 'status': 'conditional_world_previews_exported',
            'source_review_sha256': config['review_sha256'], 'source_review_id': review['id'],
            'worlds': worlds, 'preview_worlds_exported': len(worlds),
            'selected_spacing_interpretation': None, 'physical_height_verified': False,
            'ground_datum_verified': False, 'world_placement_eligible': False,
            'park_world_blocks_added': 0, 'training_labels_generated': 0, 'model_weights_updated': False,
            'limits': {'max_worlds': MAX_WORLDS, 'max_platform_cells': MAX_PLATFORM_CELLS,
                'max_world_blocks_each': MAX_WORLD_BLOCKS}, 'limitations': review['limitations']}
        atomic_json(root/'source-design-massing.json', review)
        _write_index(root, result)
        result['output_sha256'] = {p.relative_to(root).as_posix(): _sha(p)
            for p in sorted(root.rglob('*')) if p.is_file()}
        atomic_json(root/'quality-report.json', result)
        check()
        if output.exists():
            raise ValueError('Fresh planning world preview output required')
        root.rename(output)
    progress({'progress': 1., 'message': 'Conditional Bedrock world downloads ready'})
    return result


def _write_index(root, result):
    body = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Planning preview worlds</title>',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<style>body{font:17px system-ui;max-width:950px;margin:2rem auto;padding:0 1rem;line-height:1.5}li{margin:1rem 0}a{color:#17549b}</style>',
        '<h1>Download conditional preview worlds</h1>',
        '<p>These Bedrock worlds show two source-derived row envelopes on flat display terrain. '
        'Both spacing interpretations are retained. No surveyed park placement, individual cabins, canopy, openings or paths are established.</p>',
        '<p>Save a .mcworld file and open it with Minecraft Bedrock. Windows users can double-click it with Bedrock installed. '
        'The world uses Creative mode, with a supported spawn beside the models. '
        'The target format is Bedrock 1.21.130; import and gameplay have not been tested.</p><ul>']
    for row in result['worlds']:
        dimensions = ' × '.join(f'{v:g}' for v in row['source_nominal_extents_m'])
        body.append('<li><a download href="'+escape(row['file'], quote=True)+'">'+
            escape(row['spacing_interpretation'].replace('_', ' '))+'.mcworld</a> — source dimensions '+
            dimensions+' m; 1 block per metre, with boundary rounding. '+
            '<a href="'+escape(row['audit_file'], quote=True)+'">Saved-world checks and source pins</a></li>')
    body.extend(['</ul><p>Each download passed saved block readback, archive checks and a second spawn/coverage check '
        'after extraction. These checks do not certify physical building accuracy or player movement.</p>',
        '<p><a href="source-design-massing.json">Source design review</a> · <a href="quality-report.json">Export report</a></p></html>'])
    (root/'index.html').write_text(''.join(body), encoding='utf-8')
