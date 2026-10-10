"""Persistent spatial cycles and disjoint worker ownership for park previews."""
import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path

VERSION = 'park-cycles-v1'
MAX_CHUNKS = 262_144


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.partial')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
    temporary.replace(path)


def partition_sections(chunks, count):
    """Balanced recursive spatial splits; every native chunk has exactly one owner."""
    chunks = sorted(set(chunks)); count = min(count, len(chunks))
    if not chunks: return []
    def split(points, n):
        if n == 1: return [points]
        spans = [max(p[a] for p in points)-min(p[a] for p in points) for a in (0, 1)]
        axis = 0 if spans[0] >= spans[1] else 1
        points = sorted(points, key=lambda p: (p[axis], p[1-axis]))
        left = n//2
        cut = max(left, min(len(points)-(n-left), round(len(points)*left/n)))
        return split(points[:cut], left)+split(points[cut:], n-left)
    return split(chunks, count)


class CyclePlan:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file(): raise ValueError('Initialize a cycle plan first')
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.contract = json.loads(self.db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
        if self.contract['version'] != VERSION: self.close(); raise ValueError('Unsupported cycle contract')

    @classmethod
    def create(cls, path, geometry, base, chunks, *, sections=15, batch_chunks=150, workers=10, halo_chunks=1, terrain_config=None, allow_draft=False, focus_chunks=None):
        if any(type(v) is not int for v in (sections, batch_chunks, workers, halo_chunks)):
            raise ValueError('Integer scheduling settings required')
        if not 1 <= sections <= 64 or not 1 <= batch_chunks <= 200 or not 1 <= workers <= 10 or not 0 <= halo_chunks <= 4:
            raise ValueError('Scheduling settings exceed bounds')
        owned = set()
        for chunk in chunks:
            if len(chunk) != 2 or any(type(v) is not int or abs(v) > 1_000_000 for v in chunk):
                raise ValueError('Bounded integer native chunk coordinates required')
            owned.add(tuple(chunk))
            if len(owned) > MAX_CHUNKS: raise ValueError('Chunk scheduling budget exceeded')
        if not owned: raise ValueError('No chunks to schedule')
        geometry, base, path = Path(geometry), Path(base), Path(path)
        connection = sqlite3.connect(geometry)
        try:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            compiled = json.loads(connection.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()[0])
            draft=compiled.get('snapshot_mode')=='review_draft'
            if draft and not allow_draft:raise ValueError('Review snapshot requires explicit allow_draft; it is not accepted geometry')
            if not connection.execute('SELECT COUNT(*) FROM voxels').fetchone()[0]:
                raise ValueError('No accepted geometry; cycle generation withheld')
            present = set(connection.execute('SELECT DISTINCT cx,cz FROM voxels'))
            if not present <= owned: raise ValueError('Schedule excludes compiled geometry chunks')
        finally: connection.close()
        quality = json.loads((base/'quality-report.json').read_text())
        from pyproj import CRS
        crs = CRS.from_user_input(compiled['manifest']['crs'])
        if not crs.is_projected or any(abs(axis.unit_conversion_factor-1)>1e-9 for axis in crs.axis_info[:2]):
            raise ValueError('Projected metre CRS required for 1:1 cycles')
        if crs != CRS.from_user_input(quality['crs']):
            raise ValueError('Cycle base and compiled geometry CRS mismatch')
        if quality.get('voxel_size_m') != 1: raise ValueError('Cycles require a 1:1 base world')
        base_sha = file_hash(base/'park.mcworld')
        if compiled.get('base_package_sha256') and compiled['base_package_sha256'] != base_sha:
            raise ValueError('Compiled base package changed')
        terrain_sha = file_hash(terrain_config) if terrain_config else None
        if compiled.get('terrain_config_sha256') and compiled['terrain_config_sha256'] != terrain_sha:
            raise ValueError('Supply the exact terrain configuration used for compilation')
        contract = {'version':VERSION, 'geometry_sha256':file_hash(geometry), 'base_package_sha256':base_sha,
                    'base_quality_sha256':file_hash(base/'quality-report.json'), 'compiled_contract':compiled,
                    'terrain_config_sha256':terrain_sha,
                    'sections':sections, 'batch_chunks':batch_chunks, 'workers':workers, 'halo_chunks':halo_chunks,
                    'chunk_set_sha256':hashlib.sha256(json.dumps(sorted(owned)).encode()).hexdigest()}
        focus=set(tuple(c) for c in (focus_chunks or []))
        if focus and (not focus<=owned or len(focus)>200 or sections<2):
            raise ValueError('Focus section requires at most 200 owned chunks and two or more sections')
        if draft:contract['review_draft']=True
        if focus:contract['focus_chunks']=sorted(focus)
        if path.exists():
            result = cls(path)
            if result.contract != contract: result.close(); raise ValueError('Changed cycle inputs; use a fresh plan')
            return result
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.partial')
        if temporary.exists(): temporary.unlink()
        db = sqlite3.connect(temporary)
        try:
            db.executescript('''
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE cycles(id INTEGER PRIMARY KEY,section INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',preview TEXT);
            CREATE TABLE chunks(cx INTEGER,cz INTEGER,section INTEGER,cycle INTEGER,worker INTEGER,ordinal INTEGER,PRIMARY KEY(cx,cz));
            CREATE INDEX cycle_worker ON chunks(cycle,worker,ordinal);
            ''')
            with db:
                db.execute('INSERT INTO metadata VALUES(?,?)', ('contract', json.dumps(contract, sort_keys=True)))
                cycle = 0
                groups=([sorted(focus)]+partition_sections(owned-focus,sections-1)) if focus else partition_sections(owned,sections)
                for section, group in enumerate(groups, 1):
                    group = sorted(group, key=lambda p: (p[1], p[0] if p[1]%2 == 0 else -p[0]))
                    # Balance cycles around the target rather than producing a tiny tail after every section.
                    batches = max(1, round(len(group)/batch_chunks), math.ceil(len(group)/200))
                    for batch in range(batches):
                        start, end = len(group)*batch//batches, len(group)*(batch+1)//batches
                        cycle += 1; db.execute('INSERT INTO cycles(id,section) VALUES(?,?)', (cycle, section))
                        for ordinal, (cx, cz) in enumerate(group[start:end]):
                            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)', (cx, cz, section, cycle, ordinal%workers, ordinal))
        finally: db.close()
        temporary.replace(path)
        return cls(path)

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.contract, sort_keys=True).encode()).hexdigest()

    def validate_inputs(self, geometry, base=None):
        if file_hash(geometry) != self.contract['geometry_sha256']:
            raise ValueError('Compiled geometry snapshot changed')
        if base is not None and (file_hash(Path(base)/'park.mcworld') != self.contract['base_package_sha256']
                or file_hash(Path(base)/'quality-report.json') != self.contract['base_quality_sha256']):
            raise ValueError('Base package/quality contract changed')

    def next_cycle(self):
        row = self.db.execute("SELECT id FROM cycles WHERE status!='complete' ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else None

    def chunks(self, cycle, worker=None, cumulative=False):
        if not self.db.execute('SELECT 1 FROM cycles WHERE id=?', (cycle,)).fetchone(): raise ValueError('Unknown cycle')
        query = 'SELECT cx,cz FROM chunks WHERE cycle'+('<=?' if cumulative else '=?')
        args = [cycle]
        if worker is not None:
            if type(worker) is not int or not 0 <= worker < self.contract['workers']: raise ValueError('Unknown worker')
            query += ' AND worker=?'; args.append(worker)
        return [tuple(r) for r in self.db.execute(query+' ORDER BY cx,cz', args)]

    def context_chunks(self, cycle, worker):
        core = self.chunks(cycle, worker); halo = self.contract['halo_chunks']
        candidates = {(x+dx,z+dz) for x,z in core for dx in range(-halo,halo+1) for dz in range(-halo,halo+1)}
        return sorted(candidates & set(tuple(r) for r in self.db.execute('SELECT cx,cz FROM chunks')))

    def complete(self, cycle, preview):
        if self.next_cycle() != cycle: raise ValueError('Only the next cycle may complete')
        with self.db:
            self.db.execute("UPDATE cycles SET status='complete',preview=? WHERE id=?", (json.dumps(preview,sort_keys=True),cycle))

    def report(self):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM cycles ORDER BY id')]
        for row in rows:
            row['preview'] = json.loads(row['preview']) if row['preview'] else None
            row['chunks'] = self.db.execute('SELECT COUNT(*) FROM chunks WHERE cycle=?',(row['id'],)).fetchone()[0]
        return {'status':'complete' if self.next_cycle() is None else 'in_progress', 'plan_identity':self.identity,
                'contract':self.contract, 'next_cycle':self.next_cycle(), 'cycles':rows,
                'total_chunks':self.db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
                'completed_chunks':self.db.execute("SELECT COUNT(*) FROM chunks JOIN cycles ON cycle=id WHERE status='complete'").fetchone()[0]}

    def close(self): self.db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['init','next','worker','preview','run','report'])
    p.add_argument('--plan', required=True); p.add_argument('--geometry'); p.add_argument('--base-world')
    p.add_argument('--output'); p.add_argument('--chunks'); p.add_argument('--worker', type=int)
    p.add_argument('--cycle', type=int); p.add_argument('--sections', type=int, default=15)
    p.add_argument('--batch-chunks', type=int, default=150); p.add_argument('--workers', type=int, default=10)
    p.add_argument('--terrain-config'); p.add_argument('--max-cycles', type=int, default=1)
    p.add_argument('--allow-draft',action='store_true');p.add_argument('--focus-chunks')
    a = p.parse_args()
    if a.stage == 'init':
        if not a.geometry or not a.base_world: p.error('init requires --geometry and --base-world')
        if a.chunks: chunks = json.loads(Path(a.chunks).read_text())
        else:
            import amulet
            world = amulet.load_level(str(Path(a.base_world)/'bedrock-world'))
            try: chunks = [list(c) for c in world.all_chunk_coords('minecraft:overworld')]
            finally: world.close()
        focus=json.loads(Path(a.focus_chunks).read_text()) if a.focus_chunks else None
        plan = CyclePlan.create(a.plan, a.geometry, a.base_world, chunks, sections=a.sections, batch_chunks=a.batch_chunks, workers=a.workers, terrain_config=a.terrain_config,allow_draft=a.allow_draft,focus_chunks=focus)
    else: plan = CyclePlan(a.plan)
    try:
        cycle = a.cycle or plan.next_cycle()
        if a.stage in ('worker','preview','run'):
            if not a.geometry or not a.output: p.error('processing requires --geometry and --output')
            from .generation_cycle_export import worker, preview, run
            if cycle is None: result = plan.report()
            elif a.stage == 'worker':
                if a.worker is None: p.error('worker requires --worker')
                result = worker(plan, a.geometry, cycle, a.worker, a.output)
            else:
                if not a.base_world: p.error('preview/run requires --base-world')
                if a.stage == 'preview': result = preview(plan, a.geometry, a.base_world, cycle, a.output, a.terrain_config)
                else: result = run(plan, a.geometry, a.base_world, a.output, a.terrain_config, a.max_cycles)
        elif a.stage == 'next': result = {'cycle':cycle, 'workers':list(range(plan.contract['workers'])) if cycle else []}
        else: result = plan.report()
        print(json.dumps(result, indent=2))
    finally: plan.close()


if __name__ == '__main__': main()
