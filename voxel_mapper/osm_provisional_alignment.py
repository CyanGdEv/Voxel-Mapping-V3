"""Pinned OSM map-consistency proposals, kept separate from surveyed frames."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from pyproj import CRS
from pyproj.transformer import TransformerGroup
from shapely.geometry import shape,mapping
from shapely.ops import transform
from .cli import parse_osm
from .generation_cycles import file_hash,atomic_json
from .evidence_memory import EvidenceMemory,identity
from .mapped_sheet_placement import propose,placed,VERSION as MATCH_VERSION
from .mapped_alignment_checks import printed_scale_review,check,VERSION as CHECK_VERSION
from .linework_boundaries import recover_page,VERSION as RECOVERY_VERSION

VERSION='osm-provisional-alignment-v2'


def recover_outlines(data):
    recovered,report=recover_page(data['candidates'])
    if report['status']!='network_budget_withheld' or not data['report'].get('regions'):
        return recovered,report
    regions=[];faces=[]
    # Restrict recovery to complete original primitives already retained in
    # each window. Never clip lines or close gaps at a window boundary.
    for region in data['report']['regions']:
        parents=[c for c in data['candidates'] if any(w['row']==region['row'] and w['column']==region['column']
            for w in c.get('regional_window_references',[]))]
        if not parents:continue
        rows,review=recover_page(parents)
        faces.extend(c for c in rows if c.get('extraction_kind')=='linework_boundaries')
        regions.append({'row':region['row'],'column':region['column'],**review})
    return faces,{'status':'regional_outline_recovery_only','whole_page_recovery':report,'regions':regions,
        'recovered_faces':len(faces),'completeness_verified':False}


def osm_collection(path):
    raw=Path(path).read_bytes()
    if len(raw)>32000000:raise ValueError('OSM snapshot byte budget exceeded')
    if raw.lstrip().startswith(b'<'):
        root=ET.fromstring(raw)
        if root.tag!='osm' or len(root)>100000:raise ValueError('Bounded OSM API snapshot required')
        nodes={int(n.attrib['id']):{'lon':float(n.attrib['lon']),'lat':float(n.attrib['lat'])} for n in root.findall('node')}
        ways={int(w.attrib['id']):[nodes[int(n.attrib['ref'])] for n in w.findall('nd')] for w in root.findall('way')}
        elements=[]
        for kind in ('way','relation'):
            for item in root.findall(kind):
                row={'type':kind,'id':int(item.attrib['id']),'tags':{t.attrib['k']:t.attrib['v'] for t in item.findall('tag')}}
                if kind=='way':row['geometry']=ways[row['id']]
                else:row['members']=[{'type':m.attrib['type'],'ref':int(m.attrib['ref']),'role':m.attrib.get('role',''),
                    'geometry':ways.get(int(m.attrib['ref']),[])} for m in item.findall('member')]
                elements.append(row)
        data={'elements':elements}
    else:data=json.loads(raw)
    if data.get('remark') or not isinstance(data.get('elements'),list) or len(data['elements'])>100000:
        raise ValueError('Complete bounded OSM element snapshot required')
    collection,skipped=parse_osm(data)
    return collection,hashlib.sha256(raw).hexdigest(),skipped


def map_references(path,target_crs):
    collection,digest,skipped=osm_collection(path);target=CRS.from_user_input(target_crs)
    if not target.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in target.axis_info[:2]):
        raise ValueError('Projected metre OSM target frame required')
    group=TransformerGroup('EPSG:4326',target,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers:raise ValueError('Preferred OSM coordinate transformation unavailable')
    converter=group.transformers[0]
    if not 0<=converter.accuracy<=1:raise ValueError('OSM projection operation accuracy is unknown or exceeds one metre')
    rows=[]
    for feature in collection['features']:
        if feature['geometry']['type']!='Polygon' or feature['properties']['kind'] not in ('building','water','plaza','parking','path'):continue
        geometry=transform(converter.transform,shape(feature['geometry']))
        if geometry.is_empty or not geometry.is_valid or geometry.has_z:continue
        if len(rows)>=5000:raise ValueError('OSM reference polygon budget exceeded')
        rows.append({'id':feature['id'],'geometry':geometry,'name':feature['properties'].get('name','')})
    return rows,digest,{'reference_polygons':len(rows),'skipped_osm_elements':len(skipped),
        'operation':converter.description,'operation_accuracy_m':converter.accuracy,
        'absolute_osm_accuracy_m':None,'registration_verified':False}


def run(corpus,geometry_directory,osm_file,store,output,*,target_crs,max_pages=1000,max_seed_fits=512):
    if type(max_pages) is not int or not 1<=max_pages<=1000:raise ValueError('OSM alignment page budget must be 1..1000')
    propose([],[],max_seed_fits=max_seed_fits)
    geometry_directory=Path(geometry_directory);extraction=json.loads((geometry_directory/'geometry-report.json').read_text())
    feed=geometry_directory/'geometry-candidates.jsonl'
    if file_hash(feed)!=extraction['file_sha256']['geometry']:raise ValueError('Retained native geometry feed changed')
    refs,osm_sha,projection=map_references(osm_file,target_crs)
    pages=corpus.db.execute('SELECT sha,page,result FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',
        (extraction['version'],extraction['contract'])).fetchall()
    if len(pages)!=extraction['pages'] or len(pages)>max_pages:raise ValueError('OSM alignment page inventory budget/change')
    contract={'version':VERSION,'match_version':MATCH_VERSION,'check_version':CHECK_VERSION,'recovery_version':RECOVERY_VERSION,
        'geometry_sha256':file_hash(feed),'osm_sha256':osm_sha,'target_crs':target_crs,
        'projection':projection,'max_pages':max_pages,'max_seed_fits':max_seed_fits}
    root=Path(output)/identity(contract);root.mkdir(parents=True,exist_ok=True)
    computed=reused=0;records=[];facts=[];overlays=[]
    with EvidenceMemory(store) as memory:
        parent=memory.put('osm_snapshot',{'sha256':osm_sha,'target_crs':target_crs,'projection':projection},
            {'sha256':osm_sha,'source_kind':'osm','projection':projection,'physical_identity_verified':False,'registration_verified':False})
        for sha,page,raw in pages:
            pdf=corpus.root/'files'/(sha+'.pdf')
            if file_hash(pdf)!=sha:raise ValueError('Original alignment PDF changed')
            data=json.loads(raw)
            inputs={**contract,'document_sha256':sha,'page':page,'native_page_sha256':identity(data)}
            cached=memory.get('osm_provisional_alignment',inputs,[parent])
            if cached:record=cached['payload'];reused+=1
            else:
                scale=printed_scale_review(pdf,page);recovered,recovery=recover_outlines(data)
                by_geometry={}
                for candidate in data['candidates']+recovered:
                    if candidate['geometry']['type']!='Polygon' or candidate.get('paint_reference_truncated'):continue
                    g=shape(candidate['geometry']);by_geometry.setdefault(g.normalize().wkb_hex,{'candidate_id':candidate['id'],'geometry':g})
                objects=list(by_geometry.values())
                record={'document_sha256':sha,'page':page,'status':'awaiting_visible_printed_scale','printed_scale_review':scale,
                    'objects':len(objects),'recovery':recovery,'projection':projection,'proposal':None,'alignment_checks':None,
                    'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0,
                    'absolute_accuracy_verified':False,'absolute_error_bound_m':None,'provisional_geometry':[]}
                if scale['status']=='one_visible_printed_scale':
                    proposal=propose(objects,refs,max_seed_fits=max_seed_fits,expected_scale=scale['expected_metres_per_pdf_point'])
                    review=check(objects,refs,proposal['hypotheses'],expected_scale=scale['expected_metres_per_pdf_point'],search_flags=proposal['review_flags'])
                    record.update(proposal=proposal,alignment_checks=review,status='map_consistent_provisional_alignment' if review['status']=='map_consistent_candidate' else 'unvalidated_map_proposals' if proposal['hypotheses'] else 'no_map_correspondence_found')
                    if review['status']=='map_consistent_candidate':
                        fit=proposal['hypotheses'][0];domain=shape(fit['mapped_support_envelope'])
                        residual=max(r['boundary_error_m'] for r in review['hypotheses'][0]['held_out_checks'])
                        record['uncertainty']={'held_out_map_disagreement_m':residual,'absolute_position_error_m':None,
                            'reason':'OSM and discovered correspondences are not independent survey evidence'}
                        for candidate in data['candidates']:
                            g=placed(shape(candidate['geometry']),fit)
                            if not domain.covers(g):continue
                            record['provisional_geometry'].append({'type':'Feature','id':candidate['id'],'geometry':mapping(g),
                                'properties':{'document_sha256':sha,'page':page,'geometry_crs':target_crs,
                                    'osm_sha256':osm_sha,'status':'osm_provisional_unclassified_geometry','registration_verified':False,
                                    'physical_identity_verified':False,'absolute_error_bound_m':None,'world_geometry_additions':0}})
                computed+=1
            if file_hash(pdf)!=sha:raise ValueError('Original PDF changed during OSM alignment')
            fact=memory.put('osm_provisional_alignment',inputs,record,[parent]);facts.append(fact);records.append(record)
            overlays.extend(record['provisional_geometry'])
    if file_hash(osm_file)!=osm_sha or file_hash(feed)!=contract['geometry_sha256']:raise ValueError('OSM alignment inputs changed during run')
    # The proposal kind is never collected as a surveyed landmark or recipe.
    page_file=root/'page-alignments.jsonl';page_file.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in records))
    atomic_json(root/'provisional-overlay.geojson',{'type':'FeatureCollection','features':overlays,'geometry_crs':target_crs,
        'registration_verified':False,'absolute_error_bound_m':None})
    report={'contract':contract,'pages':len(records),'page_statuses':dict(Counter(r['status'] for r in records)),
        'page_facts':facts,'run_pages':computed,'reused_pages':reused,'provisional_overlay_records':len(overlays),
        'output_sha256':{'page-alignments.jsonl':file_hash(page_file),'provisional-overlay.geojson':file_hash(root/'provisional-overlay.geojson')},
        'output_directory':str(root),'world_geometry_additions':0,'registration_verified':False,'absolute_accuracy_verified':False}
    atomic_json(root/'osm-alignment-report.json',report);return report


def main():
    from .planning_bulk import Corpus
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','geometry','osm','store','output','target-crs'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--max-seed-fits',type=int,default=512);args=parser.parse_args();corpus=Corpus(args.corpus)
    try:print(json.dumps(run(corpus,args.geometry,args.osm,args.store,args.output,target_crs=args.target_crs,max_seed_fits=args.max_seed_fits),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
