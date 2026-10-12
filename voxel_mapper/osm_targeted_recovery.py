"""Complete original paint recovery around failed provisional map outlines."""
from collections import Counter
import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import box,shape
from .drawing_geometry import extract_page
from .drawing_page_tools import native_inverse
from .linework_boundaries import recover_page

VERSION='osm-targeted-source-recovery-v2'


def recover(page,sha,page_number,objects,refs,checks,*,max_windows=8):
    if type(max_windows) is not int or not 1<=max_windows<=8:raise ValueError('Targeted window budget must be 1..8')
    by_id={o['candidate_id']:o for o in objects};by_ref={r['id']:r for r in refs}
    failures=[r for h in checks['hypotheses'] for r in h['held_out_checks'] if not r['passed']]
    inverse=native_inverse(page);rotation=page.rotation
    try:page.set_rotation(0);frame=box(*(page.rect*inverse))
    finally:page.set_rotation(rotation)
    windows={}
    for row in failures:
        fit=row['held_out_fit'];matrix=np.asarray(fit['matrix']);inv=np.linalg.inv(matrix);offset=-inv@fit['translation_m']
        mapped=affine_transform(by_ref[row['reference_id']]['geometry'],[inv[0,0],inv[0,1],inv[1,0],inv[1,1],*offset])
        bounds=by_id[row['candidate_id']]['geometry'].union(mapped).bounds
        scale=float(np.linalg.norm(matrix[:,0]));padding=min(100.,20/scale)
        region=box(bounds[0]-padding,bounds[1]-padding,bounds[2]+padding,bounds[3]+padding).intersection(frame)
        if region.is_empty:continue
        key=tuple(region.bounds)
        windows.setdefault(key,[]).append({'candidate_id':row['candidate_id'],'reference_id':row['reference_id']})
    report={'version':VERSION,'status':'targeted_source_geometry_only','requested_windows':len(windows),
        'deferred_windows':max(0,len(windows)-max_windows),'windows':[], 'unique_candidates':0,
        'world_geometry_additions':0,'registration_verified':False,'physical_identity_verified':False}
    if not windows:return [],report
    paths=page.get_cdrawings(extended=True)
    retained={};points=0
    for bounds,links in sorted(windows.items())[:max_windows]:
        candidates,extraction=extract_page(page,sha,page_number,_paths=paths,region_native_points=list(bounds),
            min_line_length_points=.25,isolate_open_stroked_subpaths=True,max_candidates=4000,max_total_points=200000)
        entry={'region_native_points':list(bounds),'failed_matches':links,'extraction':extraction,'recovery':None}
        report['windows'].append(entry)
        if extraction['status']!='unplaced_geometry_candidates':entry['status']='extraction_budget_withheld';continue
        recovered,recovery=recover_page(candidates);entry['recovery']=recovery;entry['status']='complete_primitives_retained'
        for candidate in candidates+[c for c in recovered if c.get('extraction_kind')=='linework_boundaries']:
            window_ref={'region_native_points':list(bounds),'extraction_contract':candidate['extraction_contract'],
                'paint_ordinals':[p['ordinal'] for p in candidate.get('paint_references',[])]}
            if candidate['id'] in retained:
                if window_ref not in retained[candidate['id']]['targeted_window_references']:
                    retained[candidate['id']]['targeted_window_references'].append(window_ref)
                continue
            g=shape(candidate['geometry'])
            n=len(g.coords) if g.geom_type=='LineString' else sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
                for p in ([g] if g.geom_type=='Polygon' else g.geoms))
            if len(retained)>=10000 or points+n>1000000:
                report.update(status='combined_targeted_budget_withheld',unique_candidates=0)
                return [],report
            # Original paint ordinals/coordinates and each recovery contract
            # survive. The region never clips or repairs source primitives.
            candidate={**candidate,'targeted_window_references':[window_ref],
                'selection_reason':'failed_osm_match_investigation; placement_and_identity_unverified'}
            retained[candidate['id']]=candidate;points+=n
    report.update(unique_candidates=len(retained),retained_points=points,
        geometry_types=dict(Counter(c['geometry']['type'] for c in retained.values())),
        limitations=['Only complete original primitives are retained; no map boundary is copied into source geometry.',
            'Short source segments may be symbols; recovered faces remain unclassified.',
            'Window/recovery rejections and deferred windows prevent a source completeness claim.'])
    return list(retained.values()),report
