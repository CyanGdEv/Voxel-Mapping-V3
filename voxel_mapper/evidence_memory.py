"""Persistent, content-addressed evidence with dependency-aware rejection.

Memory reuses exact observations. It does not turn proximity or a successful
voxel export into verified physical correspondence or a training label.
"""
import hashlib
import json
from pathlib import Path
import sqlite3

VERSION='persistent-evidence-memory-v1'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EvidenceMemory:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=30)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS facts(
            id TEXT PRIMARY KEY,kind TEXT NOT NULL,input TEXT NOT NULL,
            payload TEXT NOT NULL,payload_sha TEXT NOT NULL,status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS dependencies(
            child TEXT NOT NULL REFERENCES facts(id),parent TEXT NOT NULL REFERENCES facts(id),
            PRIMARY KEY(child,parent));
          CREATE TABLE IF NOT EXISTS feedback(
            id TEXT PRIMARY KEY,fact TEXT NOT NULL REFERENCES facts(id),record TEXT NOT NULL);
        ''')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('version',VERSION))
        if self.db.execute('SELECT value FROM metadata WHERE key=?',('version',)).fetchone()[0]!=VERSION:
            self.db.close();raise ValueError('Evidence memory version mismatch')

    def close(self):self.db.close()

    def __enter__(self):return self

    def __exit__(self,*args):self.close()

    def key(self,kind,inputs,parents=()):
        return identity([VERSION,kind,inputs,sorted(parents)])

    def get(self,kind,inputs,parents=()):
        identifier=self.key(kind,inputs,parents)
        row=self.db.execute('SELECT input,payload,payload_sha,status FROM facts WHERE id=?',(identifier,)).fetchone()
        if row is None:return None
        if row[0]!=canonical(inputs) or identity(json.loads(row[1]))!=row[2]:
            raise ValueError('Evidence memory content checksum mismatch')
        if row[3]!='retained':raise ValueError('Evidence memory fact rejected or invalidated: '+identifier)
        actual=sorted(r[0] for r in self.db.execute('SELECT parent FROM dependencies WHERE child=?',(identifier,)))
        if actual!=sorted(parents):raise ValueError('Evidence memory dependency checksum mismatch')
        ancestors=self.db.execute('''WITH RECURSIVE ancestry(id) AS (
            SELECT parent FROM dependencies WHERE child=?
            UNION SELECT d.parent FROM dependencies d JOIN ancestry a ON d.child=a.id)
            SELECT payload,payload_sha,status FROM facts JOIN ancestry USING(id) LIMIT 10001''',(identifier,))
        ancestor_bytes=0
        for count,(payload,pin,status) in enumerate(ancestors,1):
            ancestor_bytes+=len(payload.encode())
            if count>10000 or ancestor_bytes>128000000:raise ValueError('Evidence ancestry budget exceeded')
            if status!='retained':raise ValueError('Evidence memory parent rejected or invalidated')
            if identity(json.loads(payload))!=pin:raise ValueError('Evidence memory parent content checksum mismatch')
        return {'id':identifier,'payload':json.loads(row[1])}

    def put(self,kind,inputs,payload,parents=()):
        if not isinstance(kind,str) or not kind or len(kind)>128:raise ValueError('Bounded evidence kind required')
        parents=sorted(parents)
        if len(parents)>10000 or len(set(parents))!=len(parents):raise ValueError('Unique bounded evidence parents required')
        encoded=canonical(payload)
        if len(encoded.encode())>64000000:raise ValueError('Evidence payload byte budget exceeded')
        identifier=self.key(kind,inputs,parents)
        with self.db:
            # Serialize parent validation and insertion against feedback writers.
            self.db.execute('BEGIN IMMEDIATE')
            for parent in parents:
                row=self.db.execute('SELECT status FROM facts WHERE id=?',(parent,)).fetchone()
                if row is None or row[0]!='retained':raise ValueError('Retained evidence parent required')
            previous=self.get(kind,inputs,parents)
            if previous is not None:
                if canonical(previous['payload'])!=encoded:raise ValueError('Conflicting evidence for unchanged inputs')
                return identifier
            self.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?)',
                (identifier,kind,canonical(inputs),encoded,identity(payload),'retained'))
            self.db.executemany('INSERT INTO dependencies VALUES(?,?)',[(identifier,p) for p in parents])
        return identifier

    def reject(self,identifier,*,reviewer,reason,review_reference):
        if any(not isinstance(s,str) or not s.strip() or len(s)>4096 for s in (reviewer,reason,review_reference)):
            raise ValueError('Identified review and reason required')
        record={'fact_id':identifier,'outcome':'rejected','reviewer':reviewer,'reason':reason,'review_reference':review_reference}
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not self.db.execute('SELECT 1 FROM facts WHERE id=?',(identifier,)).fetchone():
                raise ValueError('Known evidence fact required')
            self.db.execute('INSERT OR IGNORE INTO feedback VALUES(?,?,?)',(identity(record),identifier,canonical(record)))
            # Every dependent placement becomes unavailable for future reuse.
            self.db.execute('''WITH RECURSIVE affected(id) AS (
                SELECT ? UNION SELECT d.child FROM dependencies d JOIN affected a ON d.parent=a.id)
                UPDATE facts SET status=CASE WHEN id=? THEN 'rejected' ELSE 'invalidated' END
                WHERE id IN (SELECT id FROM affected)''',(identifier,identifier))
        return record

    def report(self):
        return {'version':VERSION,'facts':dict(self.db.execute('SELECT status,COUNT(*) FROM facts GROUP BY status')),
            'dependency_edges':self.db.execute('SELECT COUNT(*) FROM dependencies').fetchone()[0],
            'reviewed_rejections':self.db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],
            'training_labels_generated':0}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('report')
    rejection=commands.add_parser('reject')
    for name in ('fact-id','reviewer','reason','review-reference'):
        rejection.add_argument('--'+name,required=True)
    args=parser.parse_args()
    with EvidenceMemory(args.store) as memory:
        if args.command=='reject':
            memory.reject(args.fact_id,reviewer=args.reviewer,reason=args.reason,review_reference=args.review_reference)
        print(json.dumps(memory.report(),sort_keys=True))


if __name__=='__main__':main()
