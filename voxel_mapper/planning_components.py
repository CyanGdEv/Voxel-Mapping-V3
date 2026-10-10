"""Source text mentions and nearby drawing candidates for component binding."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from shapely.geometry import box, shape
from shapely.strtree import STRtree
from .drawing_geometry import native_inverse
from .generation_cycles import atomic_json, file_hash

VERSION='planning-component-mentions-v1'


def claims(text):
    """Printed claims only; a mention never establishes an object's geometry."""
    value=' '.join(text.lower().split())
    roles=[]
    for role,pattern in [('queue',r'\bqueue\b'),('stairs',r'\b(?:stairs?|staircase|steps)\b'),
                         ('fence',r'\bfenc(?:e|ing)\b'),('preshow',r'\bpre[ -]?show\b')]:
        if re.search(pattern,value):roles.append(role)
    if not roles:return None
    result={'roles':roles}
    if 'fence' in roles:
        for material in ('timber','steel','closeboard','rustic'):
            if re.search(r'\b'+material+r'\b',value):result['fence_description']=material;break
        match=re.search(r'\b(?:ht\s*(\d+(?:\.\d+)?)|height\s*(\d+(?:\.\d+)?)\s*m?|(\d+(?:\.\d+)?)\s*(?:m\s*)?ht)\b',value)
        if match:result['printed_height_value']=float(next(v for v in match.groups() if v is not None));result['height_units']='m' if re.search(r'\d\s*m\b',match.group()) else 'unspecified'
    if 'inspection' in value:result['level_role']='inspection; not passenger platform'
    return result


def page_mentions(page,sha,page_number,candidates,limit=2000):
    import pymupdf
    matrix=native_inverse(page)
    geometries=[shape(c['geometry']) for c in candidates]
    distances=[g.boundary if g.geom_type in ('Polygon','MultiPolygon') else g for g in geometries]
    index=STRtree(distances) if distances else None
    rows=[];withheld=0
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            text=' '.join(s['text'] for s in line['spans']).strip();printed=claims(text)
            if printed is None:continue
            if len(rows)>=limit:withheld+=1;continue
            bounds=list(pymupdf.Rect(line['bbox'])*matrix);label=box(*bounds)
            nearby=[]
            if index is not None:
                neighbors=[int(i) for i in index.query(label.buffer(96))]
                neighbors.sort(key=lambda i:(distances[i].distance(label),candidates[i]['id']))
                nearby=[{'candidate_id':candidates[i]['id'],'distance_pdf_points':round(distances[i].distance(label),6)} for i in neighbors[:8]]
            identity=hashlib.sha256(json.dumps([VERSION,sha,page_number,bounds,text],sort_keys=True).encode()).hexdigest()
            rows.append({'id':identity,'document_sha256':sha,'page':page_number,'text':text,
                         'label_bounds':bounds,'coordinate_frame':'pdf_native_points_y_up',
                         'printed_claims':printed,'nearby_candidate_suggestions':nearby,
                         'physical_identity_verified':False,'geometry_binding_status':'unbound',
                         'world_geometry_additions':0})
    return rows,withheld


def run(corpus,drawing_directory,output):
    import pymupdf
    drawing_directory=Path(drawing_directory);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report=json.loads((drawing_directory/'geometry-report.json').read_text());records=[];errors=[];pages=withheld=0
    role_counts=Counter()
    for sha,number,raw in corpus.db.execute('SELECT sha,page,result FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',(report['version'],report['contract'])):
        path=corpus.root/'files'/f'{sha}.pdf'
        try:
            if file_hash(path)!=sha:raise ValueError('PDF checksum mismatch')
            with pymupdf.open(path) as pdf:
                rows,deferred=page_mentions(pdf[number-1],sha,number,json.loads(raw)['candidates'])
            records.extend(rows);withheld+=deferred;pages+=1
            for row in rows:role_counts.update(row['printed_claims']['roles'])
        except Exception as exc:errors.append({'document_sha256':sha,'page':number,'error':str(exc)})
    payload=''.join(json.dumps(r,sort_keys=True)+'\n' for r in records)
    target=output/'component-mentions.jsonl';partial=target.with_suffix('.jsonl.partial');partial.write_text(payload);partial.replace(target)
    result={'version':VERSION,'status':'unbound_component_mentions','pages':pages,'mentions':len(records),
            'roles':dict(role_counts),'withheld_mentions':withheld,'errors':errors,'file_sha256':file_hash(target),
            'drawing_contract':report['contract'],'world_geometry_additions':0,
            'limitations':['Proximity does not bind a label to geometry.','Printed dimensions apply only after component identity review.',
                           'Existing/proposed sheet state and physical placement require independent source binding.',
                           'Unlabelled stairs and queue structures are not ruled out by absence of a text mention.']}
    atomic_json(output/'component-report.json',result);return result
