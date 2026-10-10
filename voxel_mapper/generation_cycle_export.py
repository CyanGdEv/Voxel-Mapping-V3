"""Disjoint payload workers and a single resumable cumulative Bedrock writer."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from pathlib import Path
from .generation_cycles import atomic_json, file_hash
from .reconstruction.batch import GeometryStore


class ScopedGeometryStore(GeometryStore):
    """Connection-local views retain the immutable plan hash across all cycles."""
    def __init__(self, path, chunks):
        self.path = Path(path); self.db = sqlite3.connect(path)
        self.scheduled_chunks = set(chunks)
        self.db.execute('CREATE TEMP TABLE selected(cx INTEGER,cz INTEGER,PRIMARY KEY(cx,cz))')
        self.db.executemany('INSERT INTO selected VALUES(?,?)', sorted(self.scheduled_chunks))
        self.db.executescript('''
        CREATE TEMP VIEW voxels AS SELECT v.* FROM main.voxels v JOIN selected s USING(cx,cz);
        CREATE TEMP VIEW evidence AS SELECT e.* FROM main.evidence e JOIN voxels v USING(x,y,z);
        CREATE TEMP TABLE selected_features(id TEXT PRIMARY KEY);
        INSERT INTO selected_features SELECT DISTINCT feature FROM evidence;
        CREATE TEMP VIEW features AS SELECT f.* FROM main.features f JOIN selected_features s USING(id);
        CREATE TEMP VIEW feature_records AS SELECT f.* FROM main.feature_records f JOIN selected_features s USING(id);
        ''')
        self.db.commit()


def tile_hash(store, cx, cz):
    digest = hashlib.sha256(); count = 0
    for row in store.tile_rows(cx, cz):
        digest.update((json.dumps(row, sort_keys=True)+'\n').encode()); count += 1
    return digest.hexdigest(), count


def safe_file(directory, name):
    if not isinstance(name, str): raise ValueError('Artifact filename required')
    path = Path(directory)/name
    if path.is_symlink() or not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError('Unsafe worker artifact path')
    return path


def verify_worker(plan, geometry, cycle, number, directory):
    directory = Path(directory)
    receipt = json.loads((directory/'worker-receipt.json').read_text())
    core = plan.chunks(cycle, number)
    expected = {'plan_identity':plan.identity, 'cycle':cycle, 'worker':number,
                'owned_chunks':[list(c) for c in core], 'geometry_sha256':plan.contract['geometry_sha256']}
    if any(receipt.get(k) != v for k,v in expected.items()): raise ValueError('Worker receipt ownership/input mismatch')
    required = {'tiles.jsonl','feature-records.jsonl','cell-provenance.jsonl','decisions.jsonl','batch-report.json','context-chunks.json'}
    tiles = [json.loads(line) for line in (directory/'tiles.jsonl').read_text().splitlines() if line.strip()]
    store = ScopedGeometryStore(geometry, core)
    try:
        expected_nonempty = set(tuple(c) for c in store.db.execute('SELECT DISTINCT cx,cz FROM voxels'))
        found = set()
        for tile in tiles:
            chunk = tuple(tile['native_chunk']); name = tile['file']
            if chunk not in expected_nonempty or chunk in found or name != f'chunk_{chunk[0]}_{chunk[1]}.jsonl':
                raise ValueError('Missing, duplicate or foreign worker chunk')
            found.add(chunk); required.add(name)
            sha, count = tile_hash(store, *chunk)
            if tile['sha256'] != sha or tile['records'] != count or file_hash(safe_file(directory,name)) != sha:
                raise ValueError('Worker payload differs from accepted canonical geometry')
        if found != expected_nonempty: raise ValueError('Worker omitted accepted geometry chunks')
        if set(receipt['files']) != required: raise ValueError('Incomplete worker artifact manifest')
        for name, sha in receipt['files'].items():
            if file_hash(safe_file(directory, name)) != sha: raise ValueError('Worker artifact checksum mismatch')
        context = json.loads((directory/'context-chunks.json').read_text())
        if context != {'native_chunks':[list(c) for c in plan.context_chunks(cycle,number)],
                       'context_only_not_write_ownership':True}:
            raise ValueError('Worker halo contract mismatch')
    finally: store.close()
    return receipt


def worker(plan, geometry, cycle, number, output):
    plan.validate_inputs(geometry)
    core = plan.chunks(cycle, number); output = Path(output)
    if output.exists(): return verify_worker(plan, geometry, cycle, number, output)
    temporary = output.with_name(output.name+'.partial')
    if temporary.exists(): shutil.rmtree(temporary)
    output.parent.mkdir(parents=True, exist_ok=True)
    store = ScopedGeometryStore(geometry, core)
    try: store.export_tiles(temporary)
    finally: store.close()
    atomic_json(temporary/'context-chunks.json', {'native_chunks':[list(c) for c in plan.context_chunks(cycle,number)],
                                               'context_only_not_write_ownership':True})
    receipt = {'plan_identity':plan.identity, 'geometry_sha256':plan.contract['geometry_sha256'],
               'cycle':cycle, 'worker':number, 'owned_chunks':[list(c) for c in core],
               'files':{p.name:file_hash(p) for p in sorted(temporary.iterdir()) if p.is_file()},
               'status':'canonical_chunk_payloads_verified_at_assembly'}
    atomic_json(temporary/'worker-receipt.json', receipt)
    temporary.replace(output)
    return verify_worker(plan, geometry, cycle, number, output)


def worker_directory(root, cycle, number):
    return Path(root)/'workers'/f'cycle_{cycle:04d}'/f'worker_{number:02d}'


def preview(plan, geometry, base, cycle, output, terrain_config=None):
    plan.validate_inputs(geometry, base); output = Path(output)
    if (file_hash(terrain_config) if terrain_config else None) != plan.contract.get('terrain_config_sha256'):
        raise ValueError('Cycle terrain sampling configuration changed or missing')
    completed = plan.db.execute('SELECT status,preview FROM cycles WHERE id=?',(cycle,)).fetchone()
    if completed is None: raise ValueError('Unknown cycle')
    if completed[0] == 'complete':
        retained = json.loads(completed[1])
        if file_hash(safe_file(output, retained['file'])) != retained['sha256']: raise ValueError('Completed preview changed')
        atomic_json(output/'progress.json', plan.report())
        return retained
    if plan.next_cycle() != cycle: raise ValueError('Cannot publish cycles out of order')
    for number in range(plan.contract['workers']):
        verify_worker(plan, geometry, cycle, number, worker_directory(output,cycle,number))
    cumulative = plan.chunks(cycle, cumulative=True)
    store = ScopedGeometryStore(geometry, cumulative); terrain = None
    try:
        report = store.report()
        if report['unique_voxel_cells']:
            ground = None
            if terrain_config:
                from .terrain import Terrain
                config = json.loads(Path(terrain_config).read_text())
                manifest = plan.contract['compiled_contract']['manifest']
                raster = Path(config['terrain']['path'])
                if not raster.is_absolute(): config['terrain']['path'] = str((Path(terrain_config).parent/raster).resolve())
                if manifest.get('vertical_datum') and config['terrain'].get('vertical_datum') != manifest['vertical_datum']:
                    raise ValueError('Cycle terrain vertical datum mismatch')
                terrain = Terrain(config['terrain'], manifest['crs'], {s['id']:s for s in config['sources']})
                if terrain.checksum != manifest.get('terrain_sha256'): raise ValueError('Cycle terrain checksum mismatch')
                ground = terrain.sample
            from .reconstruction.batch_export import export_world
            report = export_world(store, base, output/'native', ground)
            package = output/'native/park.mcworld'; quality = output/'native/quality-report.json'
        else:
            # Early empty batches can publish terrain context, explicitly without claiming new geometry.
            import amulet
            world = amulet.load_level(str(Path(base)/'bedrock-world'))
            try:
                if not set(cumulative) <= set(world.all_chunk_coords('minecraft:overworld')):
                    raise ValueError('Scheduled chunks exceed retained terrain coverage')
            finally: world.close()
            report = {**report, 'status':'base_terrain_preview_only', 'touched_chunks':0}
            package = Path(base)/'park.mcworld'; quality = Path(base)/'quality-report.json'
        with zipfile.ZipFile(package) as archive:
            if archive.testzip() is not None: raise ValueError('Preview package CRC failed')
        target = output/'previews'/f'cycle_{cycle:04d}'
        target.mkdir(parents=True, exist_ok=True)
        partial = target/'park.mcworld.partial'; shutil.copyfile(package, partial); partial.replace(target/'park.mcworld')
        shutil.copyfile(quality, target/'quality-report.json')
        receipt = {'status':report['status'], 'plan_identity':plan.identity, 'cycle':cycle,
                   'section':plan.db.execute('SELECT section FROM cycles WHERE id=?',(cycle,)).fetchone()[0],
                   'new_scheduled_chunks':len(plan.chunks(cycle)), 'cumulative_scheduled_chunks':len(cumulative),
                   'cumulative_geometry_chunks':report['touched_chunks'], 'cumulative_voxel_cells':report['unique_voxel_cells'],
                   'file':(target/'park.mcworld').relative_to(output).as_posix(), 'sha256':file_hash(target/'park.mcworld'),
                   'base_terrain_includes_ungenerated_context':True,
                   'workflow_run_id':os.environ.get('GITHUB_RUN_ID'),
                   'download_artifact':f'park-preview-cycle-{cycle:04d}',
                   'detail_scope':'Only scheduled chunks have cycle-compiled details; unchanged base terrain may cover the whole park.'}
        atomic_json(target/'cycle-report.json', receipt)
        plan.complete(cycle, receipt)
        atomic_json(output/'progress.json', plan.report())
        return receipt
    finally:
        store.close()
        if terrain: terrain.close()


def run(plan, geometry, base, output, terrain_config=None, max_cycles=1):
    if type(max_cycles) is not int or not 1 <= max_cycles <= 10_000: raise ValueError('Bounded positive cycle count required')
    previews = []
    def one_worker(cycle, number):
        from .generation_cycles import CyclePlan
        local = CyclePlan(plan.path)
        try: return worker(local, geometry, cycle, number, worker_directory(output,cycle,number))
        finally: local.close()
    for _ in range(max_cycles):
        cycle = plan.next_cycle()
        if cycle is None: break
        with ThreadPoolExecutor(max_workers=plan.contract['workers']) as pool:
            futures = [pool.submit(one_worker, cycle, number)
                       for number in range(plan.contract['workers'])]
            for future in futures: future.result()
        previews.append(preview(plan,geometry,base,cycle,output,terrain_config))
    return {'previews':previews, 'progress':plan.report()}
