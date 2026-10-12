"""Bounded disk graph of exact source vertices and original edges."""
import json
import math
import sqlite3
import tempfile
from pathlib import Path

VERSION='osm-disk-network-graph-v1'
LIMITS={'max_scan_vertices':1000000,'max_nodes':500000,'max_edges':1000000,'max_junctions':2000}


def disk_junctions(lines,*,limits=None):
    options={**LIMITS,**(limits or {})}
    if set(options)!=set(LIMITS) or any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in options.items()):
        raise ValueError('Bounded disk network limits required')
    scanned=nodes=edges=0
    with tempfile.TemporaryDirectory(prefix='osm-network-') as directory:
        db=sqlite3.connect(Path(directory)/'graph.sqlite')
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA temp_store=FILE; PRAGMA cache_size=-2048; '
                'CREATE TABLE nodes(id TEXT PRIMARY KEY,x REAL NOT NULL,y REAL NOT NULL); '
                'CREATE TABLE edges(a TEXT NOT NULL,b TEXT NOT NULL,PRIMARY KEY(a,b));')
            for item in lines:
                line=item['geometry'] if isinstance(item,dict) else item
                if line.geom_type!='LineString' or line.is_empty or not line.is_valid:continue
                coordinates=list(line.coords);scanned+=len(coordinates)
                if scanned>options['max_scan_vertices']:raise ValueError('Network scan vertex budget exceeded')
                ids=item.get('node_ids') if isinstance(item,dict) else None
                if ids is not None and len(ids)!=len(coordinates):raise ValueError('OSM node/geometry inventory mismatch')
                layer=item.get('layer','0') if isinstance(item,dict) else 'native'
                previous=None
                for i,p in enumerate(coordinates):
                    if len(p)!=2 or any(not math.isfinite(v) for v in p):raise ValueError('Finite 2D network vertices required')
                    p=tuple(0. if v==0 else float(v) for v in p)
                    key=json.dumps(['osm_node',ids[i]] if ids is not None else ['coordinate',layer,*p],separators=(',',':'))
                    cursor=db.execute('INSERT OR IGNORE INTO nodes VALUES(?,?,?)',(key,*p))
                    if cursor.rowcount:
                        nodes+=1
                        if nodes>options['max_nodes']:raise ValueError('Network disk node budget exceeded')
                    elif db.execute('SELECT x,y FROM nodes WHERE id=?',(key,)).fetchone()!=p:
                        raise ValueError('Conflicting shared OSM node coordinates')
                    if previous is not None and previous[1]!=p:
                        a,b=sorted((previous[0],key))
                        if a==b:raise ValueError('Shared node has inconsistent edge endpoints')
                        cursor=db.execute('INSERT OR IGNORE INTO edges VALUES(?,?)',(a,b))
                        if cursor.rowcount:
                            edges+=1
                            if edges>options['max_edges']:raise ValueError('Network disk edge budget exceeded')
                    previous=(key,p)
                db.commit()
            rows=db.execute('SELECT nodes.x,nodes.y,degree FROM nodes JOIN '
                '(SELECT id,count(*) AS degree FROM (SELECT a AS id FROM edges UNION ALL SELECT b AS id FROM edges) '
                'GROUP BY id HAVING count(*)>=3) AS degrees ON nodes.id=degrees.id ORDER BY nodes.id LIMIT ?',
                (options['max_junctions']+1,)).fetchall()
            if len(rows)>options['max_junctions']:raise ValueError('Network disk junction budget exceeded')
            result=[{'point':[x,y],'degree':degree} for x,y,degree in rows]
            return result,{'version':VERSION,'mode':'bounded_disk_graph','scanned_vertices':scanned,
                'unique_nodes':nodes,'unique_edges':edges,'junctions':len(result),'limits':options,
                'registration_verified':False,'physical_identity_verified':False}
        finally:db.close()
