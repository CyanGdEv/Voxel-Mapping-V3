"""Original material anchors -> independent local elevation studies and review evidence."""
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image
from shapely.affinity import affine_transform
from shapely.geometry import shape, mapping, Polygon, box

from . import drawing_faces, plan_elevation_edges
from .building_cross_view import _surface
from .building_spec import build, digest, FRAME
from .building_raster_views import render, VERSION as RENDER_VERSION
from .drawing_geometry import native_inverse
from .generation_cycles import atomic_json
from .raster_opening_scan import scan, VERSION as OPENING_VERSION
from .study_mesh_export import write_glb

VERSION='building-facade-feed-v1'
MAX_OUTPUT_BYTES=128000000


def _affine(matrix):return [matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f]


def normalize_region(record,page):
    """Retain source raster boundaries exactly; no union, clipping or role promotion."""
    review=record.get('raster_contrast_boundary_review',{})
    view=record.get('drawing_view_candidate',{})
    if review.get('status')!='unverified_contrast_boundary_candidate' or not view.get('view_key_candidate'):
        return None
    polygon=shape(review['geometry'])
    if (polygon.geom_type!='Polygon' or not polygon.is_valid or polygon.is_empty
            or sum(len(r.coords) for r in [polygon.exterior,*polygon.interiors])>4096):
        raise ValueError('Bounded valid raster contrast region required')
    inverse=native_inverse(page);native=affine_transform(polygon,_affine(inverse))
    display=affine_transform(polygon,_affine(page.rotation_matrix))
    factor=view.get('nominal_metres_per_pdf_point_candidate')
    if type(factor) not in (float,int) or not .0001<=factor<=4:
        raise ValueError('Bounded nominal printed scale candidate required')
    return {'id':digest(record),'document_sha256':record['document_sha256'],'page':record['page'],
        'view_key_candidate':view['view_key_candidate'],'bearing_label_candidate':view['bearing_label_candidate'],
        'material_number':record['number'],'component_class_candidate':record.get('component_class_candidate'),
        'coordinate_frame':'pdf_native_points_y_up','geometry':mapping(native),
        'unrotated_mupdf_to_pdf_native_matrix':list(inverse),
        'unrotated_mupdf_to_display_matrix':list(page.rotation_matrix),
        'display_geometry':mapping(display),'nominal_metres_per_pdf_point_candidate':factor,
        'source_record_sha256':digest(record),'interior_ring_candidates':len(polygon.interiors),
        'physical_opening_count':None,'view_scope_verified':False,'physical_identity_verified':False,
        'scale_application_verified':False,'per_view_state':'unknown','world_placement_eligible':False}


def scope_restoration_widths(receipt,records,page):
    """Exact original anchor links only; no nearest view or complete-facade claim."""
    reviews=receipt.get('raster_review',{}).get('material_boundary_restoration_reviews',[])
    if len(reviews)>32:raise ValueError('Restoration review inventory budget exceeded')
    output=[]
    for review in reviews:
        item={'document_sha256':receipt['document_sha256'],'page':receipt['page'],
            'source_review_sha256':digest(review),'status':'withheld_restoration_view_scope',
            'region_widths':[],'physical_view_identity_verified':False}
        output.append(item);linked=[]
        for anchor in review['anchors']:
            matches=[r for r in records if r.get('document_sha256')==receipt['document_sha256']
                and r.get('page')==receipt['page'] and r.get('number')==anchor['number']
                and list(r.get('target_page_point',[]))==list(anchor['target_page_point'])
                and r.get('glyph_screen_status')=='raster_consistent_candidate']
            if len(matches)!=1:break
            linked.append(matches[0].get('drawing_view_candidate',{}))
        if len(linked)!=len(review['anchors']) or not linked:continue
        keys={tuple(v['view_key_candidate']) for v in linked if v.get('view_key_candidate')}
        factors={v.get('nominal_metres_per_pdf_point_candidate') for v in linked}
        if len(keys)!=1 or any(not v.get('view_key_candidate') for v in linked) or len(factors)!=1:continue
        factor=next(iter(factors))
        if type(factor) not in (int,float) or not math.isfinite(factor) or not .0001<=factor<=4:continue
        if len(review['alternatives'])>128:raise ValueError('Restoration alternative inventory budget exceeded')
        for alternative in review['alternatives']:
            if len(alternative['regions'])>32:raise ValueError('Restoration region inventory budget exceeded')
            for region in alternative['regions']:
                polygon=shape(region['boundary_review']['geometry'])
                if polygon.geom_type!='Polygon' or not polygon.is_valid or sum(len(r.coords) for r in [polygon.exterior,*polygon.interiors])>4096:
                    raise ValueError('Bounded valid restoration region required')
                display=affine_transform(polygon,_affine(page.rotation_matrix))
                item['region_widths'].append({'alternative_id':alternative['id'],'number':region['number'],
                    'source_region_geometry_sha256':digest(region['boundary_review']['geometry']),
                    'region_width_m':(display.bounds[2]-display.bounds[0])*factor,
                    'periodic_source_witnesses':alternative.get('periodic_source_witnesses',[]),
                    'complete_facade_identity_verified':False})
        item.update(status='unverified_exact_anchor_view_scope',view_key_candidate=list(next(iter(keys))),
            nominal_metres_per_pdf_point_candidate=factor,source_scale_application_verified=False)
    return output


def region_study(building_id,regions):
    """Display one independent view at nominal scale; never assemble facade slots."""
    if not regions or len(regions)>128:raise ValueError('Bounded nonempty region study required')
    keys={tuple(r['view_key_candidate']) for r in regions}
    factors={r['nominal_metres_per_pdf_point_candidate'] for r in regions}
    hashes={r['document_sha256'] for r in regions}
    if len(keys)!=1 or len(factors)!=1 or len(hashes)!=1:
        raise ValueError('One original view and agreeing nominal scale required')
    polygons=[shape(r['display_geometry']) for r in regions];factor=next(iter(factors))
    xmin=min(p.bounds[0] for p in polygons);bottom=max(p.bounds[3] for p in polygons)
    components=[]
    for row,polygon in zip(regions,polygons):
        components.append({'id':row['id'],'role':'detail','colour':'859caf',
            'geometry':_surface(polygon,lambda x,y:[(x-xmin)*factor,0,(bottom-y)*factor],flip=True),
            'evidence':{'class':'inferred','source_ids':['original_pdf'],
                'description':'Original material-anchor contrast region; physical role and extent unverified.',
                'source_region_id':row['id'],'source_record_sha256':row['source_record_sha256']}})
    spec={'version':'building-spec-v1','coordinate_frame':FRAME,'building_id':building_id,
        'sources':[{'id':'original_pdf','sha256':next(iter(hashes)),'state':'unknown'}],
        'components':components,'preview_scope':'independent_elevation_regions_not_complete_building',
        'source_regions':regions,'local_display_origin':{'display_pdf_points':[xmin,bottom],
            'basis':'region_bounds_for_display_only','floor_or_vertical_datum_verified':False},
        'assumptions':['Separate source regions are nominal-scale zero-thickness display surfaces; they are not assembled building walls or roofs.',
            'Material anchors, extent, raster clipping, per-view state, revision identity and printed scale application are unverified.',
            'Interior rings are unclassified raster regions, not accepted doors or windows; absent rings do not prove absent openings.',
            'Local zero is an arbitrary display origin, not the printed shop level or a surveyed datum.'],
        'acceptance':{'physical_identity_verified':False,'source_state_verified':False,
            'dimensions_verified':False,'topology_verified':False,'world_placement_eligible':False}}
    model=build(spec);model['preview_scope']=spec['preview_scope']
    return spec,model


def _validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{'version','buildings'}:
        raise ValueError('Versioned facade source feed required')
    buildings=config.get('buildings')
    if not isinstance(buildings,list) or not 1<=len(buildings)<=8:raise ValueError('Bounded facade building list required')
    ids=set()
    for building in buildings:
        if not isinstance(building,dict) or set(building)-{'building_id','revision_scope','sources'}:
            raise ValueError('Declared source scope and original PDFs required')
        identifier=building.get('building_id');scope=building.get('revision_scope')
        if not isinstance(identifier,str) or not 1<=len(identifier)<=256 or identifier in ids:
            raise ValueError('Unique bounded building ID required')
        if not isinstance(scope,str) or not scope.strip() or len(scope)>1024:
            raise ValueError('Declared drawing revision scope required')
        ids.add(identifier);sources=building.get('sources');hashes=set();sheets=set();projects=set()
        if not isinstance(sources,list) or not 1<=len(sources)<=8:raise ValueError('Bounded original source list required')
        for source in sources:
            if not isinstance(source,dict) or set(source)-{'path','sha256','drawing_number'}:
                raise ValueError('Original path, hash and drawing-number claim required')
            sha=source.get('sha256');path=source.get('path');number=source.get('drawing_number')
            if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha) or sha in hashes:
                raise ValueError('Distinct original PDF hashes required')
            if not isinstance(path,str) or not path:raise ValueError('Original PDF path required')
            match=re.fullmatch(r'(\d{3,5})-(\d{1,3})',number) if isinstance(number,str) else None
            if not match or number in sheets:raise ValueError('Distinct printed drawing-number claims required')
            hashes.add(sha);sheets.add(number);projects.add(match[1])
        if len(projects)!=1:raise ValueError('Cross-project source claims cannot be linked')
    return buildings


def prepare(config,resolve,output):
    buildings=_validate(config);root=Path(output)
    if root.exists():raise ValueError('Fresh facade evidence directory required')
    root.mkdir(parents=True);results=[]
    atomic_json(root/'contract.json',{'version':VERSION,'config_sha256':digest(config),
        'opening_scan_version':OPENING_VERSION,'preview_policy':'independent_elevation_regions_only'})
    for index,building in enumerate(buildings):
        directory=root/f'building-{index:04d}';partial=directory.with_name(directory.name+'.partial');partial.mkdir()
        result={'building_id':building['building_id'],'revision_scope_claim':building['revision_scope'],
            'revision_scope_verified':False,'region_preview_specs_generated':0,
            'complete_building_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0}
        try:
            documents=[];paths={}
            for source in building['sources']:
                path=Path(resolve(source['path']));sha=source['sha256']
                if path.stat().st_size>20000000 or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
                    raise ValueError('Original PDF checksum or byte budget failed')
                with pymupdf.open(path) as doc:
                    if not 1<=len(doc)<=4:raise ValueError('Select source documents of at most four pages')
                paths[sha]=path;documents.append({'file':str(path.resolve()),'sha256':sha,
                    'drawing_number':source['drawing_number']})
            atomic_json(partial/'documents.json',documents)
            face_report=drawing_faces.run(partial/'documents.json',partial/'faces',max_pages=32)
            # Exact source-reference and dimensional discovery checks; do not
            # normalize plan scales or select the nearest compatible edge.
            edges=plan_elevation_edges.run(partial/'documents.json',partial/'faces',
                max_results=256,max_correspondence_candidates=100000)
            atomic_json(partial/'plan-correspondence.json',edges)
            with (partial/'faces/face-associations.jsonl').open() as stream:
                records=[]
                for line in stream:
                    if len(line)>8000000 or len(records)>=4000:
                        raise ValueError('Material anchor record budget exceeded')
                    records.append(json.loads(line))
            if len(records)>4000:raise ValueError('Material anchor record budget exceeded')
            regions=[];opening_reports=[];seen_windows=set();restoration_widths=[]
            for sha,path in paths.items():
                with pymupdf.open(path) as document:
                    for record in records:
                        if record['document_sha256']!=sha:continue
                        page=document[record['page']-1];region=normalize_region(record,page)
                        if region is not None:regions.append(region)
                    for receipt in face_report['pages']:
                        if receipt.get('document_sha256')!=sha:continue
                        page=document[receipt['page']-1];inverse=native_inverse(page)
                        restoration_widths.extend(scope_restoration_widths(receipt,records,page))
                        windows=receipt.get('raster_review',{}).get('atlas',{}).get('artwork_review_windows',[])
                        for window in windows:
                            view_records=[r for r in records if r['document_sha256']==sha and r['page']==receipt['page']
                                and r.get('raster_region_review',{}).get('artwork_review_window_ids')==[window['id']]
                                and r.get('drawing_view_candidate',{}).get('view_key_candidate')]
                            keys={tuple(r['drawing_view_candidate']['view_key_candidate']) for r in view_records}
                            key=(sha,receipt['page'],window['id'])
                            if len(keys)!=1 or key in seen_windows:continue
                            seen_windows.add(key)
                            scope=affine_transform(box(*window['bbox_page_points']),_affine(inverse))
                            crop_dir=partial/f'opening-view-{len(opening_reports):04d}'
                            rendered=render({'version':RENDER_VERSION,'path':str(path.resolve()),'sha256':sha,
                                'page':receipt['page'],'bounds_pdf_native':list(scope.bounds),'width_pixels':1600},lambda p:p,crop_dir)
                            with Image.open(crop_dir/'view.png') as image:
                                rgb=np.asarray(image.convert('RGB'))
                                gray=np.rint(rgb.astype(float)@np.array([.299,.587,.114])).astype('uint8')
                            detected=scan(gray);adjacent=scan(gray,pair_scope='adjacent_compatible_jambs')
                            indexed=scan(gray,representation='indexed');matrix=pymupdf.Matrix(rendered['pixel_edge_to_pdf_native_matrix'])
                            factors={r['drawing_view_candidate']['nominal_metres_per_pdf_point_candidate'] for r in view_records}
                            factor=next(iter(factors)) if len(factors)==1 else None
                            for candidate in [*detected['candidates'],*adjacent['candidates']]:
                                x0,y0,x1,y1=candidate['bounds_pixels']
                                points=[pymupdf.Point(x,y)*matrix for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]]
                                candidate.update(geometry=mapping(Polygon([(p.x,p.y) for p in points])),
                                    coordinate_frame='pdf_native_points_y_up',source_png_sha256=rendered['png_sha256'])
                                if factor is not None:
                                    unit=(matrix.a**2+matrix.b**2)**.5*factor
                                    candidate['nominal_measurements_candidate']={
                                        'jamb_inner_span_m':(x1-x0)*unit,'jamb_run_height_m':(y1-y0)*unit,
                                        'jamb_span_sampling_interval_m':[max(0,x1-x0-4)*unit,(x1-x0+4)*unit],
                                        'scale_verified':False,'physical_accuracy_bound_verified':False,
                                        'height_or_floor_datum_verified':False}
                                candidate['id']=digest([sha,receipt['page'],next(iter(keys)),candidate])
                            opening_report={'document_sha256':sha,'page':receipt['page'],
                                'view_key_candidate':list(next(iter(keys))),
                                'view_scope_verified':False,'render_receipt_sha256':digest(rendered),'scan':detected,
                                'adjacent_bay_review_scan':adjacent,'indexed_opening_scan':indexed,
                                'indexed_scan_sha256':digest(indexed),'source_png_sha256':rendered['png_sha256'],
                                'pixel_edge_to_pdf_native_matrix':rendered['pixel_edge_to_pdf_native_matrix'],
                                'adjacent_bay_candidates_are_complete_openings':False}
                            atomic_json(crop_dir/'opening-scan.json',opening_report);opening_reports.append(opening_report)
            groups={}
            for region in regions:groups.setdefault((region['document_sha256'],tuple(region['view_key_candidate'])),[]).append(region)
            previews=[]
            for group_index,(source_sha,key) in enumerate(sorted(groups)):
                group=groups[(source_sha,key)];view_dir=partial/f'region-view-{group_index:04d}';view_dir.mkdir()
                spec,model=region_study(building['building_id']+':view:'+':'.join(map(str,key)),group)
                atomic_json(view_dir/'spec.json',spec);atomic_json(view_dir/'model.json',model)
                exported=write_glb(model,view_dir/'model.glb')
                previews.append({'view_key_candidate':list(key),'source_region_ids':[r['id'] for r in group],
                    'spec_sha256':digest(spec),'export':exported,'preview_scope':spec['preview_scope']})
            atomic_json(partial/'regions.json',{'version':VERSION,'regions':regions})
            atomic_json(partial/'opening-candidates.json',{'version':OPENING_VERSION,'views':opening_reports})
            atomic_json(partial/'material-boundary-alternatives.json',{'version':'source-stroke-restoration-v2',
                'view_scoped_reviews':restoration_widths,
                'pages':[{'document_sha256':p['document_sha256'],'page':p['page'],
                    'reviews':p.get('raster_review',{}).get('material_boundary_restoration_reviews',[])}
                    for p in face_report['pages']],
                'selected_physical_boundary_id':None,'complete_building_specs_generated':0})
            for sha,path in paths.items():
                if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Original PDF changed before facade publication')
            if sum(p.stat().st_size for p in partial.rglob('*') if p.is_file())>MAX_OUTPUT_BYTES:
                raise ValueError('Facade evidence output byte budget exceeded')
            result.update(status='awaiting_facade_interpretation',material_anchor_records=len(records),
                raster_region_candidates=len(regions),region_preview_specs_generated=len(previews),region_previews=previews,
                numbered_reference_statuses=face_report['view_link_statuses'],
                raster_contrast_statuses=face_report['raster_contrast_statuses'],
                opening_candidates=sum(len(r['scan']['candidates']) for r in opening_reports),
                opening_scan_statuses=[r['scan']['status'] for r in opening_reports],
                plan_region_reference_pairs=len(edges['results']),source_sha256=sorted(paths),
                requirements=['physical_facade_and_opening_interpretation','per_view_state_and_scale',
                    'verified_revision_correspondence','closed_non_rectangular_footprint','cross_view_dimensions_and_depth',
                    'vertical_datum','geographic_registration'])
            partial.replace(directory)
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
            # Failed staged outputs remain diagnostic and are never published
            # as reviewable previews or accepted geometry.
            result.update(status='invalid_facade_source_input',reason=str(error))
        atomic_json(root/f'building-{index:04d}-result.json',result);results.append(result)
    report={'version':VERSION,'buildings':results,
        'region_preview_specs_generated':sum(r['region_preview_specs_generated'] for r in results),
        'complete_building_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0}
    atomic_json(root/'report.json',report)
    atomic_json(root/'source-review-queue.json',{'version':VERSION,'records':results,
        'review_outcomes_generated':0,'feedback_policy':'Source hypotheses and previews are not correctness labels.'})
    return report
