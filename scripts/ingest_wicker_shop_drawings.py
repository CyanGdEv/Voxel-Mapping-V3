"""Ingest pinned revised shop sheets, keeping elevations separate from XY plans."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.roof_plan_review import page_scale


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('sources','pdf-directory','output'):p.add_argument('--'+k,required=True)
    a=p.parse_args();sources=json.loads(Path(a.sources).read_text());out=Path(a.output)
    docs=[r for r in sources['documents'] if r['version_scope']=='revised_separate_building']
    if len(docs)!=3 or {r['drawing_number'] for r in docs}!={'2967-21','2967-26','2967-48'}:raise ValueError('Three exact revised shop sheets required')
    for r in docs:
        path=Path(a.pdf_directory)/(r['sha256']+'.pdf')
        if file_hash(path)!=r['sha256']:raise ValueError('Retained planning PDF checksum mismatch')
    if out.exists():raise ValueError('Use a fresh ingestion output directory')
    out.mkdir(parents=True);report=[]
    try:
        with (out/'plan-candidates.jsonl').open('w') as plans,(out/'elevation-candidates.jsonl').open('w') as elevations:
            for r in docs:
                with pymupdf.open(Path(a.pdf_directory)/(r['sha256']+'.pdf')) as d:
                    if len(d)!=1:raise ValueError('Pinned single-sheet source expected')
                    page=d[0];text=page.get_text()
                    import re
                    if not re.search(r'2967\s*-\s*'+r['drawing_number'].split('-')[1]+r'\b',text):raise ValueError('Native drawing number mismatch')
                    raw,extraction=extract_page(page,r['sha256'],1);candidates,recovery=recover_page(raw)
                    stream=elevations if r['role']=='shop-elevations' else plans
                    for candidate in candidates:
                        candidate['sheet_role']=r['role'];candidate['source_state']='proposed'
                        stream.write(json.dumps(candidate)+'\n')
                    report.append({'document_sha256':r['sha256'],'drawing_number':r['drawing_number'],
                        'role':r['role'],'native_page_rotation':page.rotation,'native_media_box_points':list(page.mediabox),
                        'scale_review':page_scale(text,page.mediabox.width,page.mediabox.height),
                        'raster_image_placements':len(page.get_image_info()),'extraction':extraction,
                        'linework_recovery':recovery,'candidate_count':len(candidates),
                        'horizontal_plan_eligible':r['role']!='shop-elevations',
                        'native_metadata_checks':{'drawing_number_reproduced':True,
                            'planning_status_printed':'PLANNING' in text.upper(),
                            'revision_P1_printed':bool(re.search(r'\bP1\b',text)),
                            'shop_floor_182_50_printed':bool(re.search(r'Shop[\s\S]{0,25}\+\s*182\.50',text)),
                            'shop_internal_area_170m2_printed':bool(re.search(r'GIA\s*:\s*170m2',text))},
                        'physical_identity_verified':False,'world_geometry_additions':0})
        result={'status':'revised_source_review_candidates_only','source_catalogue_sha256':file_hash(a.sources),
            'documents':report,'historical_documents_excluded':[r['sha256'] for r in sources['documents'] if r['version_scope']=='earlier_combined_building'],
            'stream_sha256':{name:file_hash(out/name) for name in ('plan-candidates.jsonl','elevation-candidates.jsonl')},
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
            'limitations':['Elevation geometry is quarantined from horizontal plan matching',
                'Proposed materials and levels are not accepted as-built attributes',
                'Image/clipped paint is not silently converted into complete vector outlines',
                'Printed scale alone does not establish physical edge dimensions or independent registration']}
        (out/'ingestion-report.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps([{'drawing':r['drawing_number'],'candidates':r['candidate_count'],'rejected_scopes':r['extraction'].get('rejections',{}).get('unsupported_clipping_or_compositing_scope',0)} for r in report]))
    except Exception:
        for name in ('plan-candidates.jsonl','elevation-candidates.jsonl','ingestion-report.json'):(out/name).unlink(missing_ok=True)
        raise


if __name__=='__main__':main()
