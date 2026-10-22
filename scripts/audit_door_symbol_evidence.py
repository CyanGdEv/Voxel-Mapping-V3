"""Independent original path/leaf/arc checks in addition to exhaustive replay."""
import math

import pymupdf
from shapely.geometry import LineString, Point, Polygon, box, shape

from voxel_mapper import automatic_door_symbols
from voxel_mapper.drawing_footprints import fill_geometry
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.ordinary_surfaces import label_runs
from voxel_mapper.reconstruction_evidence_queue import digest


def verify(corpus, source_pages, inventories, returns, evidence, checked, max_checks):
    fresh=automatic_door_symbols.run(corpus,source_pages,inventories,returns,max_checks=max_checks)
    assert digest(fresh)==digest(evidence)
    assert not evidence['physical_opening_verified'] and not evidence['artwork_scale_verified']
    assert evidence['world_geometry_additions']==evidence['training_labels_generated']==0
    if evidence['status']!='original_door_symbol_evidence_only':return
    by_view={v['view_id']:v for v in inventories}; edge_lookup={}; symbols={}
    for source in evidence['pages']:
        with pymupdf.open(corpus.root/'files'/(source['document_sha256']+'.pdf')) as document:
            page=document[source['page']-1]; paths=page.get_drawings(extended=True)
            matrix=pymupdf.Matrix(source['unrotated_mupdf_to_pdf_native_matrix'])
            assert list(matrix)==list(native_inverse(page))
            for edge in source['edges']:
                path=paths[edge['path_ordinal']]; item=path['items'][edge['item_index']]
                assert item[0]=='l' and path['type']=='s' and path['seqno']==edge['paint_seqno']
                assert edge['points_pdf_native']==[list(p*matrix) for p in item[1:]]
                assert list(path['color'])==edge['stroke_color'] and path['width']==edge['stroke_width_pdf_points']
                assert path['stroke_opacity']==1 and not path.get('layer')
                native_line=LineString([item[1],item[2]]).buffer(path['width']/2)
                for clip in edge['clip_references']:
                    original=paths[clip['path_ordinal']]
                    assert original['type']=='clip' and original['level']==clip['level']
                    assert all(original['items'][i][0] in ('l','re') for i in range(len(original['items'])))
                    # Decode original line/rectangle rings independently of the recovery helper.
                    rings=[];current=[]
                    for item in original['items']:
                        if item[0]=='re':
                            if current:rings.append(current);current=[]
                            rect=item[1];points=[rect.tl,rect.tr,rect.br,rect.bl]
                            if item[2]<0:points.reverse()
                            ring=[list(p) for p in points];rings.append([*ring,ring[0]])
                        else:
                            a,b=map(list,item[1:])
                            if current and math.dist(current[-1],a)>1e-5:rings.append(current);current=[]
                            if not current:current=[a]
                            current.append(b)
                    if current:rings.append(current)
                    rings=[r if r[0]==r[-1] else [*r,r[0]] for r in rings]
                    assert digest(rings)==digest(clip['source_rings'])
                    geometry=fill_geometry(clip['source_rings'],clip['even_odd'],True)
                    assert geometry.covers(native_line)
                assert edge['whole_original_stroke_within_clip'] and not edge['later_overpaint_visibility_verified']
                edge_lookup[edge['id']]=edge
                checked['original_door_source_line_items']+=1
            runs={(tuple(r['trace_indices']),tuple(r['character_indices'])):r for r in label_runs(page.get_texttrace())}
            for note in source['illustrative_wording']:
                run=runs[(tuple(note['trace_indices']),tuple(note['character_indices']))]
                assert note['text']==''.join(chr(c[0]) for c in run['chars']).strip()
                rect=pymupdf.Rect(run['bbox']);expected=Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
                assert expected.equals_exact(shape(note['geometry_pdf_native']),0)
                checked['original_illustrative_wording_records']+=1
    for view in evidence['views']:
        gaps={g['id']:g for g in by_view[view['view_id']]['plan_gap_review']['gaps']}
        for review in view['gaps']:
            gap=gaps[review['source_gap_id']]
            assert digest(gap)==review['source_gap_sha256']
            for symbol in review['symbols']:
                leaf=edge_lookup[symbol['leaf_edge_id']];i=symbol['hinge_endpoint_index']
                hinge=leaf['points_pdf_native'][i];tip=leaf['points_pdf_native'][1-i]
                assert symbol['hinge_pdf_native']==hinge and symbol['leaf_tip_pdf_native']==tip
                radius=math.dist(hinge,tip);assert symbol['radius_pdf_points']==radius
                vertices=[tip];sweep=0.;sign=0
                for identity in symbol['arc_edge_ids']:
                    edge=edge_lookup[identity];a,b=edge['points_pdf_native']
                    assert vertices[-1] in (a,b)
                    end=b if a==vertices[-1] else a
                    assert all(edge[k]==leaf[k] for k in ('stroke_width_pdf_points','stroke_color','clip_references'))
                    assert abs(math.dist(hinge,end)-radius)<=max(.25,.015*radius)
                    u=[vertices[-1][k]-hinge[k] for k in (0,1)];v=[end[k]-hinge[k] for k in (0,1)]
                    angle=math.degrees(math.atan2(u[0]*v[1]-u[1]*v[0],sum(u[k]*v[k] for k in (0,1))))
                    assert 1<=abs(angle)<=25 and (not sign or (angle>0)==(sign>0))
                    sign=angle;sweep+=angle;vertices.append(end)
                    checked['original_door_symbol_edges']+=1
                checked['original_door_symbol_edges']+=1
                assert vertices==symbol['arc_vertices_pdf_native'] and 4<=len(vertices)-1<=64
                assert abs(sweep-symbol['sweep_degrees'])<1e-9 and 80<=abs(sweep)<=100
                for edge in edge_lookup.values():
                    if edge['id'] in [symbol['leaf_edge_id'],*symbol['arc_edge_ids']]:continue
                    a,b=edge['points_pdf_native']
                    if vertices[-1] not in (a,b) or any(edge[k]!=leaf[k] for k in ('stroke_color','stroke_width_pdf_points','clip_references')):continue
                    end=b if a==vertices[-1] else a
                    if abs(math.dist(hinge,end)-radius)>max(.25,.015*radius):continue
                    u=[vertices[-1][k]-hinge[k] for k in (0,1)];v=[end[k]-hinge[k] for k in (0,1)]
                    angle=math.degrees(math.atan2(u[0]*v[1]-u[1]*v[0],sum(u[k]*v[k] for k in (0,1))))
                    assert not (1<=abs(angle)<=25 and (angle>0)==(sign>0)), 'A continuing source arc was truncated'
                ends=gap['gap_endpoints_pdf_native'];end=symbol['hinge_gap_end_index'];width=math.dist(*ends)
                axis=[(ends[1][i]-ends[0][i])/width for i in (0,1)];normal=[-axis[1],axis[0]]
                coordinates=list(shape(gap['geometry_pdf_native']).exterior.coords)
                values=[sum(p[i]*normal[i] for i in (0,1)) for p in coordinates]
                tolerance=(max(values)-min(values))/2+1.5
                assert tolerance==symbol['gap_end_tolerance_pdf_points'] and tolerance<=.3*width
                assert math.dist(hinge,ends[end])<=tolerance and math.dist(vertices[-1],ends[1-end])<=tolerance
                assert .65*width<=radius<=1.2*width
                assert abs(sum((tip[i]-hinge[i])*axis[i]/radius for i in (0,1)))<=math.sin(math.radians(15))
                assert not any(symbol[k] for k in ('hinge_fitted','source_points_moved','joints_snapped','physical_opening_verified','symbol_semantics_verified'))
                symbols[(view['view_id'],symbol['id'])]=symbol
                checked['independent_leaf_anchored_swings']+=1
    positions={p['id']:p for d in returns['diagnostics'] for p in d['position_comparisons'] if p['status']=='all_witness_positions_compatible'}
    assert {l['source_position_comparison_id'] for l in evidence['conditional_position_links']}==set(positions)
    for link in evidence['conditional_position_links']:
        position=positions[link['source_position_comparison_id']]
        assert digest(position)==link['source_position_comparison_sha256']
        expected={(v,i) for (v,i),s in symbols.items() if s['source_gap_sha256']==link['source_gap_sha256']}
        assert {(s['plan_view_id'],s['symbol_id']) for s in link['symbol_candidates']}==expected
        assert not link['physical_opening_verified'] and not link['artwork_scale_verified']
        checked['independent_symbol_position_links']+=1
