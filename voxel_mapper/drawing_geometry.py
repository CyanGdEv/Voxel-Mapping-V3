"""Bounded native curved polygons and open stroked-line candidates; never inferred objects."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import LineString,Polygon,box,shape,mapping
from shapely.strtree import STRtree
from .drawing_page_tools import native_inverse
from .drawing_footprints import fill_geometry

VERSION='drawing-geometry-v2'
DEFAULTS={'curve_tolerance_points':.25,'max_paths':100000,'max_candidates':4000,'max_points':10000,'max_total_points':200000}


def contract(options):return hashlib.sha256(json.dumps({'version':VERSION,**options},sort_keys=True).encode()).hexdigest()


def point_segment_distance(p,a,b):
    length=sum((b[i]-a[i])**2 for i in (0,1))
    t=max(0,min(1,sum((p[i]-a[i])*(b[i]-a[i]) for i in (0,1))/length)) if length else 0
    return math.dist(p,tuple(a[i]+t*(b[i]-a[i]) for i in (0,1)))


def flatten_cubic(points,tolerance=.25,max_points=10000,max_depth=16):
    """Control-hull distance to chord bounds each retained Bezier segment."""
    if not math.isfinite(tolerance) or not .01<=tolerance<=2:raise ValueError('Curve tolerance must be .01..2 PDF points')
    if len(points)!=4 or any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in points):raise ValueError('Finite cubic control points required')
    result=[tuple(points[0])];stack=[(list(map(tuple,points)),0)];maximum=0
    while stack:
        p,depth=stack.pop();error=max(point_segment_distance(q,p[0],p[3]) for q in p[1:3])
        if error<=tolerance:
            result.append(p[3]);maximum=max(maximum,error)
            if len(result)>max_points:raise ValueError('Flattened curve point budget exceeded')
            continue
        if depth>=max_depth:raise ValueError('Curve subdivision depth budget exceeded')
        def midpoint(a,b):return tuple((a[i]+b[i])/2 for i in (0,1))
        a,b,c=[midpoint(p[i],p[i+1]) for i in range(3)];d,e=midpoint(a,b),midpoint(b,c);f=midpoint(d,e)
        stack.append(([f,e,c,p[3]],depth+1));stack.append(([p[0],a,d,f],depth+1))
    return result,maximum


def subpaths(path,matrix,options):
    import pymupdf
    paths=[];current=[];curves=0;error=0;count=0
    def point(p):
        p=pymupdf.Point(p)*matrix
        if not math.isfinite(p.x) or not math.isfinite(p.y):raise ValueError('Nonfinite native path point')
        return (p.x,p.y)
    def append(points):
        nonlocal current,count
        if current and math.dist(current[-1],points[0])>1e-5:flush()
        if not current:current=[points[0]];count+=1
        current.extend(points[1:]);count+=len(points)-1
        if count>options['max_points']:raise ValueError('Paint-group flattened point budget exceeded')
    def flush():
        nonlocal current
        if current:paths.append(current);current=[]
        if len(paths)>100:raise ValueError('Compound subpath budget exceeded')
    for item in path['items']:
        if item[0]=='l':append([point(p) for p in item[1:3]])
        elif item[0]=='c':
            points,bound=flatten_cubic([point(p) for p in item[1:5]],options['curve_tolerance_points'],options['max_points'])
            append(points);curves+=1;error=max(error,bound)
        elif item[0]=='re':
            flush();rect=pymupdf.Rect(item[1]);points=[point(p) for p in (rect.tl,rect.tr,rect.br,rect.bl)]
            if item[2]<0:points.reverse()
            append(points+[points[0]]);flush()
        elif item[0]=='qu':
            flush();quad=pymupdf.Quad(item[1]);points=[point(p) for p in (quad.ul,quad.ur,quad.lr,quad.ll)];append(points+[points[0]]);flush()
        else:raise ValueError('Unsupported native path operator')
    flush()
    if path.get('closePath') and paths and paths[-1][0]!=paths[-1][-1]:paths[-1].append(paths[-1][0])
    if sum(len(p) for p in paths)>options['max_points']:raise ValueError('Paint-group flattened point budget exceeded')
    return paths,{'cubic_segments':curves,'chord_error_bound_pdf_points':error,'requested_tolerance_pdf_points':options['curve_tolerance_points'],'method':'adaptive_de_casteljau_control_hull_to_chord','points':sum(map(len,paths))}


def validated_options(overrides):
    if set(overrides)-set(DEFAULTS):raise ValueError('Unknown geometry extraction option')
    options={**DEFAULTS,**overrides}
    tolerance=options['curve_tolerance_points']
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not .01<=tolerance<=2:raise ValueError('Invalid curve tolerance')
    for key,upper in [('max_paths',200000),('max_candidates',10000),('max_points',20000),('max_total_points',1000000)]:
        if type(options[key])!=int or not 1<=options[key]<=upper:raise ValueError('Invalid extraction budget '+key)
    return options


def extract_page(page,sha,page_number,**overrides):
    import pymupdf
    options=validated_options(overrides);identity=contract(options)
    matrix=native_inverse(page);angle=page.rotation
    try:
        page.set_rotation(0);frame=box(*(page.rect*matrix))
    finally:page.set_rotation(angle)
    paths=page.get_cdrawings(extended=True);rejections=Counter();candidates=[];seen={};clips=[];groups=[];total_points=0
    if len(paths)>options['max_paths']:return [],{'status':'path_budget_withheld','raw_paths':len(paths),'world_geometry_additions':0}
    masks=[]
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:masks.append(box(*(pymupdf.Rect(span['bbox'])*matrix)).buffer(.5))
    mask_index=STRtree(masks) if masks else None
    for ordinal,path in enumerate(paths):
        level=path.get('level',0);clips=[c for c in clips if c[0]<level];groups=[g for g in groups if g<level]
        if path['type']=='group':groups.append(level);continue
        if path['type']=='clip':
            try:
                rings,_=subpaths(path,matrix,options);rings=[r+[r[0]] if r[0]!=r[-1] else r for r in rings]
                clip=fill_geometry(rings,path.get('even_odd',False),True)
                if clip.is_empty or not clip.is_valid or not all(math.isfinite(v) for v in clip.bounds):raise ValueError('Empty/invalid clip')
                if not clip.equals(box(*clip.bounds)):raise ValueError('Nonrectangular clip')
            except (ValueError,KeyError,TypeError):clip=None
            clips.append((level,clip));continue
        if groups or any(c[1] is None for c in clips):rejections['unsupported_clipping_or_compositing_scope']+=1;continue
        if path.get('layer'):rejections['optional_layer_state_unknown']+=1;continue
        if path.get('fill_opacity',1)!=1 or path.get('stroke_opacity',1)!=1:rejections['nonopaque_paint']+=1;continue
        try:
            parts,approximation=subpaths(path,matrix,options)
            if not parts:raise ValueError('Empty paint group')
            closed=['f' in path['type'] or p[0]==p[-1] for p in parts]
            geometries=[]
            if 'f' in path['type']:
                rings=[p+[p[0]] if p[0]!=p[-1] else p for p in parts]
                if any(len(r)<4 or not Polygon(r).is_valid or Polygon(r).area<=0 for r in rings):raise ValueError('Invalid filled ring topology')
                geometry=fill_geometry(rings,path.get('even_odd',False),True)
                if not geometry.is_empty:geometries.append((geometry,None))
            elif path['type']=='s':
                for index,p in enumerate(parts):
                    if closed[index]:
                        if len(parts)>1:raise ValueError('Compound stroked closed rings require topology review')
                        geometries.append((Polygon(p),index))
                    else:geometries.append((LineString(p),index))
            else:raise ValueError('Unsupported paint type')
            for geometry,subpath_index in geometries:
                if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon','LineString'):raise ValueError('Invalid candidate topology')
                if not frame.covers(geometry) or geometry.distance(frame.boundary)<.25:raise ValueError('Crop boundary/frame candidate')
                if any(not c[1].covers(geometry) for c in clips):raise ValueError('Paint group crosses clipping boundary')
                if geometry.geom_type=='LineString':
                    if geometry.length<12:raise ValueError('Short line/symbol candidate')
                    if not geometry.is_simple:raise ValueError('Self-crossing line needs review')
                elif geometry.area<16 or geometry.area>frame.area*.7:raise ValueError('Small symbol or sheet enclosure candidate')
                if mask_index is not None and any(masks[int(i)].covers(geometry) for i in mask_index.query(geometry)):raise ValueError('Text glyph/annotation mask')
                digest=hashlib.sha256((sha+'/'+str(page_number)+'/'+geometry.normalize().wkb_hex).encode()).hexdigest()
                style={'width_pdf_points':path.get('width'),'dashes_pdf':str(path.get('dashes',''))[:1024]}
                if style['width_pdf_points'] is not None and (not math.isfinite(style['width_pdf_points']) or style['width_pdf_points']<0):raise ValueError('Invalid native stroke width')
                paint={'ordinal':ordinal,'subpath':subpath_index,'stroke_style':style,'curve_approximation':approximation}
                if digest in seen:
                    retained=seen[digest]
                    if len(retained['paint_references'])>=256:
                        retained['paint_reference_truncated']=True;rejections['paint_reference_budget_deferred']+=1;continue
                    retained['paint_references'].append(paint)
                    retained['curve_approximation']={**retained['curve_approximation'],'cubic_segments':max(retained['curve_approximation']['cubic_segments'],approximation['cubic_segments']),'chord_error_bound_pdf_points':max(retained['curve_approximation']['chord_error_bound_pdf_points'],approximation['chord_error_bound_pdf_points'])}
                    if approximation['cubic_segments']:retained['rendering_status']=retained['rendering_status'].replace('supported_straight','supported_curved')
                    continue
                if len(candidates)>=options['max_candidates']:rejections['candidate_budget_deferred']+=1;break
                points=len(geometry.coords) if geometry.geom_type=='LineString' else sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors) for p in ([geometry] if geometry.geom_type=='Polygon' else geometry.geoms))
                if total_points+points>options['max_total_points']:rejections['page_point_budget_deferred']+=1;break
                total_points+=points
                curved=bool(approximation['cubic_segments']);kind='polyline' if geometry.geom_type=='LineString' else 'polygon'
                candidate={'id':digest,'document_sha256':sha,'page':page_number,'geometry':mapping(geometry),'coordinate_frame':'pdf_native_points_y_up','paint_references':[paint],
                    'extraction_kind':'drawing_geometry','extraction_version':VERSION,'extraction_contract':identity,'rendering_status':'supported_'+('curved' if curved else 'straight')+'_unclipped_'+kind,
                    'curve_approximation':approximation,'stroke_style':style,'semantic_status':'unclassified','line_role':'unclassified_stroked_path' if kind=='polyline' else None,'physical_identity_verified':False,'world_geometry_additions':0}
                candidates.append(candidate);seen[digest]=candidate
            if rejections['candidate_budget_deferred'] or rejections['page_point_budget_deferred']:break
        except (ValueError,TypeError,KeyError,OverflowError) as exc:rejections[str(exc)]+=1
    counts=Counter(c['geometry']['type'] for c in candidates)
    return candidates,{'status':'partial_candidate_budget' if rejections['candidate_budget_deferred'] or rejections['page_point_budget_deferred'] else 'unplaced_geometry_candidates','raw_paths':len(paths),'candidates':len(candidates),'geometry_types':dict(counts),'retained_points':total_points,'curved_candidates':sum(c['curve_approximation']['cubic_segments']>0 for c in candidates),'rejections':dict(rejections),'world_geometry_additions':0}


def run(corpus,output,*,max_pages=10000,**overrides):
    import pymupdf
    if type(max_pages)!=int or not 1<=max_pages<=100000:raise ValueError('Positive bounded page budget required')
    if set(overrides)-set(DEFAULTS):raise ValueError('Unknown geometry extraction option')
    options=validated_options(overrides);identity=contract(options);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    corpus.db.execute('CREATE TABLE IF NOT EXISTS geometry_pages(sha TEXT,page INTEGER,version TEXT,contract TEXT,result TEXT,PRIMARY KEY(sha,page,version,contract))')
    valid=set();processed=resumed=0;errors=[]
    for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall():
        try:
            path=corpus.root/'files'/f'{sha}.pdf'
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('PDF checksum mismatch')
            with pymupdf.open(path) as pdf:
                valid.add(sha)
                for i in range(len(pdf)):
                    cached=corpus.db.execute('SELECT result FROM geometry_pages WHERE sha=? AND page=? AND version=? AND contract=?',(sha,i+1,VERSION,identity)).fetchone()
                    if cached and json.loads(cached[0])['report']['status']!='withheld':resumed+=1;continue
                    if processed>=max_pages:break
                    try:candidates,report=extract_page(pdf[i],sha,i+1,**options)
                    except Exception as exc:candidates=[];report={'status':'withheld','reason':str(exc)}
                    with corpus.db:corpus.db.execute('INSERT OR REPLACE INTO geometry_pages VALUES(?,?,?,?,?)',(sha,i+1,VERSION,identity,json.dumps({'candidates':candidates,'report':report})))
                    processed+=1
        except Exception as exc:errors.append({'document_sha256':sha,'error':str(exc)})
    counts=Counter();statuses=Counter();total=curved=pages=0;digests={k:hashlib.sha256() for k in ('geometry','polygon','line')};files={k:(output/(k+'-candidates.jsonl.partial')).open('wb') for k in digests}
    try:
        for sha,page,raw in corpus.db.execute('SELECT sha,page,result FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',(VERSION,identity)):
            if sha not in valid:continue
            data=json.loads(raw);pages+=1;statuses[data['report']['status']]+=1
            for candidate in data['candidates']:
                encoded=(json.dumps(candidate,sort_keys=True)+'\n').encode();kind='line' if candidate['geometry']['type']=='LineString' else 'polygon'
                for key in ('geometry',kind):files[key].write(encoded);digests[key].update(encoded)
                counts[kind]+=1;total+=1;curved+=int(candidate['curve_approximation']['cubic_segments']>0)
    finally:
        for stream in files.values():stream.close()
    for key in files:(output/(key+'-candidates.jsonl.partial')).replace(output/(key+'-candidates.jsonl'))
    report={'version':VERSION,'contract':identity,'options':options,'status':'unplaced_geometry_only','pages':pages,'run_pages':processed,'resumed_pages':resumed,'candidates':total,'candidate_types':dict(counts),'curved_candidates':curved,'page_statuses':dict(statuses),'errors':errors,'file_sha256':{k:d.hexdigest() for k,d in digests.items()},'world_geometry_additions':0}
    (output/'geometry-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',required=True);p.add_argument('--output',required=True);p.add_argument('--max-pages',type=int,default=10000);p.add_argument('--curve-tolerance',type=float,default=.25);a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.output,max_pages=a.max_pages,curve_tolerance_points=a.curve_tolerance),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
