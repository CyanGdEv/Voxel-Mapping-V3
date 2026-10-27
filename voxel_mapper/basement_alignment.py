"""Align source basement/queue evidence and refuse conflicting world replacement."""
import argparse
from concurrent.futures import CancelledError
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, LineString, Point, mapping, shape
from shapely.ops import unary_union

from .generation_cycles import atomic_json, file_hash
from .station_access import basement_review, UNIT
from .planning_station_preshow_world import grid_cells

PROFILE = Path(__file__).with_name('data')/'wicker-basement-alignment.json'


def rigid_correspondence(source, target, *, holdout=2, tolerance_m=.1):
    """Three fit corners, one untouched test corner; no scale/shear/reflection."""
    source=np.asarray(source,dtype=float);target=np.asarray(target,dtype=float)
    if source.shape!=(4,2) or target.shape!=(4,2) or not np.isfinite([source,target]).all():
        raise ValueError('Four finite, corresponding source corners required')
    if type(holdout) is not int or holdout not in range(4) or not 0<tolerance_m<=.25:
        raise ValueError('Bounded held-out corner check required')
    ids=[i for i in range(4) if i!=holdout]
    if any(np.linalg.matrix_rank(a[ids]-a[ids].mean(0))!=2 for a in [source,target]):
        raise ValueError('Non-collinear drawing controls required')
    ac=source[ids].mean(0);bc=target[ids].mean(0)
    u,_,vt=np.linalg.svd((source[ids]-ac).T@(target[ids]-bc));rotation=u@vt
    if np.linalg.det(rotation)<0:
        raise ValueError('Reflected source correspondence rejected')
    translation=bc-ac@rotation
    residual=np.linalg.norm(source@rotation+translation-target,axis=1)*UNIT
    if max(residual)>tolerance_m:
        raise ValueError('Drawing controls or held-out corner disagree')
    return rotation,translation,{
        'method':'rigid native-page view correspondence; building-above shop outline to normalized upper-floor shop wall outline',
        'fit_corner_indices':ids,'heldout_corner_index':holdout,
        'rotation_row_convention':rotation.tolist(),'translation_pdf_points':translation.tolist(),
        'residuals_m':residual.tolist(),'heldout_residual_m':float(residual[holdout]),
        'source_corners_pdf_native_y_up':source.tolist(),'target_corners_roof_normalized_pdf_native_y_up':target.tolist(),
        'scale':1.,'shear':False,'reflection':False,'geographic_registration_verified':False,
        'independent_survey_check':False,
    }


def replay_strokes(page, expected):
    paths=page.get_drawings();result={}
    for text,points in expected.items():
        i=int(text)
        if not 0<=i<len(paths):raise ValueError('Missing source stroke')
        path=paths[i]
        if path['type']!='s' or len(path['items'])!=1 or path['items'][0][0]!='l':
            raise ValueError('Source single-line stroke changed')
        observed=np.asarray([list(p) for p in path['items'][0][1:]])
        if observed.shape!=(2,2) or not np.allclose(observed,points,atol=.02,rtol=0):
            raise ValueError('Source stroke endpoints changed')
        result[i]=observed
    return result


def conflict_review(report, rows, outer, inner, queue_edge):
    """Review exact current columns; never interpret a collision as permission."""
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'}
    cells=grid_cells(outer);old=grid_cells(shape(report['undercroft_geometry_nominal_local']))
    if not cells<=terrain.keys():raise ValueError('Aligned basement leaves current world')
    entry={tuple(r['source_cell_xy']) for r in report['entry_flight']['surfaces']}
    markers=[{'source_cell_xy':list(k),'material':terrain[k]['material'],'ground_block_m':terrain[k]['y']}
             for k in sorted(cells) if terrain[k]['material'].endswith('_wool')]
    current=unary_union([shape(p['wall_geometry_nominal_local']) for p in report['parts'] if p['id'].startswith('preshow')])
    below=[r for r in rows if r['kind']=='structure' and (r['x'],r['z']-1) in cells and 178<=r['y']<183]
    return {
        'status':'blocked_requires_upper_floor_and_access_reconciliation',
        'world_replacement_allowed':False,'world_geometry_added':0,
        'new_outer_centre_cells':len(cells),'previous_inner_centre_cells':len(old),
        'new_cells_outside_previous_inner':len(cells-old),'previous_inner_cells_outside_new_outer':len(old-cells),
        'previous_footprint_role':'previous upper-preshow-derived interior, not a traced basement outer wall',
        'existing_entry_columns_inside_aligned_basement':[list(k) for k in sorted(entry&cells)],
        'retained_plan_marker_columns_inside_aligned_basement':markers,
        'retained_structure_records_below_upper_floor_in_new_envelope':len(below),
        'new_inner_area_outside_current_upper_walls_m2':inner.difference(current).area,
        'maximum_current_ground_cut_to_178_floor_blocks':max(terrain[k]['y']-177 for k in cells),
        'queue_edge_to_current_main_entry_opening_m':queue_edge.distance(shape(next(p for p in report['parts'] if p['id']=='preshow_low')['openings'][-1]['geometry_nominal_local'])),
        'reasons':['The newly aligned basement occupies columns used by the retained entrance approach.',
            'Its wider source envelope differs from the current roof-derived upper-wall model.',
            'Existing ride/support plan markers and below-floor structures need explicit reconciliation.',
            'The drawn queue edge is not a measured centreline or a complete route to the current estimated main door.'],
    }


def run(world_directory,pdf_directory,review_directory,shop_directory,output,*,cancelled=lambda:False):
    if cancelled():raise CancelledError('Basement alignment cancelled')
    output=Path(output)
    if output.exists():raise ValueError('Fresh basement alignment review output required')
    profile=json.loads(PROFILE.read_text());world_directory=Path(world_directory);pdf_directory=Path(pdf_directory);review_directory=Path(review_directory);shop_directory=Path(shop_directory)
    def pins():
        for name,sha in profile['world_pins'].items():
            if file_hash(world_directory/name)!=sha:raise ValueError('Exact retained station-access world required')
        for name,sha in profile['sources'].items():
            if file_hash(pdf_directory/(sha+'.pdf'))!=sha:raise ValueError('Pinned original '+name+' PDF required')
        for name,sha in profile['review_pins'].items():
            if file_hash(review_directory/name)!=sha:raise ValueError('Pinned source scale/wall review required')
    pins()
    scale=json.loads((review_directory/'wicker-shop-floor-scale-review.json').read_text());floor=json.loads((review_directory/'wicker-shop-local-floor.json').read_text())
    if scale['heldout_max_residual_pdf_points']>.25:raise ValueError('Floor page-scale validation required')
    furniture=np.asarray(scale['roof_to_floor_matrix_row_convention']);floor_points=(np.asarray(floor['native_outer_corners'])-furniture[2])@np.linalg.inv(furniture[:2])
    import pymupdf
    strokes={}
    for name in ['basement','floor']:
        if cancelled():raise CancelledError('Source replay cancelled')
        with pymupdf.open(pdf_directory/(profile['sources'][name]+'.pdf')) as pdf:
            if len(pdf)!=1 or pdf[0].rotation!=90 or list(pdf[0].mediabox)[2:]!=[1684.,2384.]:raise ValueError('Original single rotated source page required')
            strokes[name]=replay_strokes(pdf[0],profile['source_strokes'][name])
    b=strokes['basement'];f=strokes['floor']
    native=lambda p:np.column_stack([np.asarray(p)[:,0],2384-np.asarray(p)[:,1]])
    raw_shop=np.asarray([b[i][1] for i in [319,349,389,419]])
    rotation,translation,fit=rigid_correspondence(native(raw_shop),floor_points)
    # Verify seams on three of the four dashed-outline corners.
    if any(not np.allclose(b[a][1],b[c][0],atol=.02,rtol=0) for a,c in [(319,320),(349,350),(389,390)]):raise ValueError('Shop outline corner seam changed')
    report=json.loads((world_directory/'quality-report.json').read_text())
    access_path=shop_directory/'source-access-review/access-review.json'
    if file_hash(access_path)!=profile['source_access_review_sha256']:
        raise ValueError('Pinned source-access placement review required')
    # The retained corrected-shop record binds the same source-access review.
    from .planning_station_preshow_world import PROFILE as station_profile
    parent_profile=json.loads(station_profile.read_text())
    if file_hash(shop_directory/'quality-report.json')!=parent_profile['base_pins']['report']:raise ValueError('Pinned corrected-shop placement context required')
    access=json.loads(access_path.read_text());a,bb,c,d,e,ff=access['drawing_correspondence']['affine'];pose=np.array([[a,bb],[c,d]]);offset=np.array([e,ff])
    if not np.allclose(pose.T@pose,np.eye(2),atol=1e-8) or np.linalg.det(pose)<0:raise ValueError('Retained unit-scale placement required')
    place=lambda pts:(np.asarray(pts)*UNIT)@pose.T+offset
    basement=lambda raw:place(native(raw)@rotation+translation)
    floor_xy=lambda raw:place((native(raw)-furniture[2])@np.linalg.inv(furniture[:2]))
    original,source_image=basement_review(pdf_directory/(profile['sources']['basement']+'.pdf'))
    inner=Polygon(place((np.asarray(shape(original['inner_clear_envelope_geometry']).exterior.coords)/UNIT)@rotation+translation))
    # Outer bounds are intersections of bound exterior outline strokes, not fill polygons.
    outer_raw=[[799.5589599609375,1125.620361328125],[1068.838134765625,1125.620361328125],
               [1068.838134765625,1574.89990234375],[799.5589599609375,1574.89990234375]]
    outer=Polygon(basement(outer_raw))
    above=Polygon(basement([b[420][0],b[475][0],b[512][1],b[457][1]]))
    floor_low=Polygon(floor_xy([[923.99853515625,1242.6202392578125],[1100.3978271484375,1242.6202392578125],[1100.3978271484375,1459.2197265625],[923.99853515625,1459.2197265625]]))
    floor_tower=Polygon(floor_xy([[927.4779052734375,1073.300048828125],[1096.91845703125,1073.300048828125],[1096.91845703125,1242.6202392578125],[927.4779052734375,1242.6202392578125]]))
    # Numerically coincide the shared joint (sub-micrometre tolerance only).
    # Separate affine batches can otherwise leave a floating-point slit.
    upper_reference=unary_union([floor_low,floor_tower]).buffer(1e-7).buffer(-1e-7)
    queue_points=[f[609][0]]
    for i in range(609,617):
        if not np.allclose(queue_points[-1],f[i][0],atol=.02,rtol=0):raise ValueError('Source queue outer edge is not continuous')
        queue_points.append(f[i][1])
    queue=LineString(floor_xy(queue_points))
    walkway_points=[]
    for i in range(601,605):
        if not np.allclose(f[i][1],f[601+(i-600)%4][0],atol=.02,rtol=0):raise ValueError('Source closed queue rectangle changed')
        walkway_points.append(f[i][0])
    walkway=Polygon(floor_xy(walkway_points))
    features=[('basement-outer-envelope',outer,'exterior envelope includes visible wall gaps'),('basement-inner-envelope',inner,'clear interior envelope; not a closed wall ring'),('preshow-above-basement',above,'dashed building-above reference'),('upper-floor-preshow-reference',upper_reference,'source outer extents with review-clipped joint; internal layout illustrative'),('queue-outer-edge',queue,'open source walkway edge, not a centreline or closed paving polygon'),('queue-closed-walkway',walkway,'four-stroke source queue walkway rectangle')]
    for gap in original['visible_wall_gaps']:
        features.append((gap['id'],LineString(basement(gap['raw_pdf_endpoints'])),'source visible wall gap; circulation role unverified'))
    rows=[json.loads(line) for line in (world_directory/'voxels.jsonl').read_text().splitlines()]
    gate=conflict_review(report,rows,outer,inner,queue)
    result={'version':profile['version'],'status':'source_alignment_complete_world_replacement_blocked','fit':fit,
        'source_pdf_sha256':profile['sources'],'review_input_sha256':profile['review_pins'],'retained_world_input_sha256':profile['world_pins'],
        'implementation_sha256':file_hash(__file__),'profile_sha256':file_hash(PROFILE),
        'floor_reduction_normalization':{'source':'retained page-furniture review','roof_to_floor_matrix_row_convention':furniture.tolist(),'heldout_max_residual_pdf_points':scale['heldout_max_residual_pdf_points']},
        'basement_source_review':original,'source_shop_control_stroke_indices':[319,349,389,419],
        'shared_title_block_does_not_establish_view_alignment':True,'source_proposal_only':True,
        'preshow_above_check':{'independent_building_used_in_fit':False,'source_role_match_verified':False,'reference_area_m2':upper_reference.area,'above_outline_area_m2':above.area,'intersection_over_union':above.intersection(upper_reference).area/above.union(upper_reference).area,'boundary_hausdorff_m':above.boundary.hausdorff_distance(upper_reference.boundary),'basis':'Different-level dashed above outline compared to upper floor extents; diagnostic only, not accepted control'},
        'queue_source_review':{'outer_edge_stroke_indices':list(range(609,617)),'closed_walkway_stroke_indices':list(range(601,605)),'closed_walkway_area_m2':walkway.area,'outer_edge_length_m':queue.length,'outer_edge_to_closed_walkway_distance_m':queue.distance(walkway),'paving_polygon_closed':False,'queue_centreline_extracted':False,'door_thresholds_or_queue_elevation_verified':False},
        'features_nominal_local':[{'id':n,'geometry':mapping(g),'basis':basis} for n,g,basis in features],
        'replacement_gate':gate,'source_world_unchanged':True,'accepted_training_labels':0,'world_geometry_additions':0,'physical_registration_verified':False,
        'limitations':['Shop fit/holdout corners validate related drawing geometry, not survey registration or as-built identity.',
            'Upper floor reduction normalization remains a whole-view hypothesis; figured dimensions take priority.',
            'Other building above extents are diagnostic and are not refitted to conceal disagreements.',
            'No internal staircase or queue passenger/inspection floor relationship is established.',
            'The retained scene is preserved while conflicting upper floor, entry, and plan markers are reconciled.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='basement-alignment-',dir=output.parent) as temp:
        root=Path(temp)/'review';root.mkdir();atomic_json(root/'alignment-review.json',result);source_image.save(root/'original-basement-gaps.png')
        bng=report['alignment']['nominal_local_xy_to_bng_en_affine']
        atomic_json(root/'aligned-evidence-bng.geojson',{'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:27700'}},'features':[{'type':'Feature','geometry':mapping(affine_transform(g,bng)),'properties':{'id':n,'basis':basis,'physical_registration_verified':False}} for n,g,basis in features]})
        preview(root/'alignment-preview.png',features,report,fit,gate)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Aligned basement and queue evidence</h1><p>Drawing alignment completed. World replacement remains blocked by existing entry/upper-footprint conflicts. Existing world unchanged.</p><img style="max-width:100%" src="alignment-preview.png"><p><a href="alignment-review.json">Review and exact conflicts</a> · <a href="aligned-evidence-bng.geojson">Projected BNG evidence</a></p>')
        if cancelled():raise CancelledError('Basement alignment cancelled')
        pins();shutil.move(root,output)
    return result


def preview(path,features,world,fit,gate):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(1260,1050),'#f9f8f2');draw=ImageDraw.Draw(image)
    geometries=[g for _,g,_ in features]+[shape(p['wall_geometry_nominal_local']) for p in world['parts']]
    bounds=unary_union(geometries).bounds;factor=min(1120/(bounds[2]-bounds[0]),760/(bounds[3]-bounds[1]))
    xy=lambda p:(65+(p[0]-bounds[0])*factor,100+(bounds[3]-p[1])*factor)
    def paint(g,colour,width=3):
        if g.geom_type=='Polygon':draw.line([xy(p) for p in g.exterior.coords],fill=colour,width=width)
        elif g.geom_type=='LineString':draw.line([xy(p) for p in g.coords],fill=colour,width=width)
        elif hasattr(g,'geoms'):
            for part in g.geoms:paint(part,colour,width)
    draw.text((24,18),'BASEMENT / PRESHOW / QUEUE: related drawing alignment, current world retained',fill='black')
    draw.text((24,40),'Three shop corners fit; fourth held out: %.3f m drawing residual. No survey or as-built acceptance.'%fit['heldout_residual_m'],fill='black')
    for p in world['parts']:
        g=shape(p['wall_geometry_nominal_local']);paint(g,'#ce7633',4);draw.text(xy(g.centroid.coords[0]),'current '+p['id'],fill='#a94f16')
    colours=['#006e9c','#35a2b5','#20863a','#657e58','#b2248e','#b2248e','#c52819','#c52819']
    for (n,g,basis),colour in zip(features,colours):paint(g,colour,5 if 'gap' in n else 3)
    route=world['entry_flight']['ordered_route_xy'];draw.line([xy((x+.5,y+.5)) for x,y in route],fill='#222222',width=7)
    for x,y in gate['existing_entry_columns_inside_aligned_basement']:
        px,py=xy((x+.5,y+.5));draw.ellipse((px-6,py-6,px+6,py+6),fill='#e33122')
    for i,text in enumerate(['Blue: aligned basement outer and inner extents; red: two visible wall gaps.',
        'Green: source building-above / upper-floor reference. Orange: current world building outlines.',
        'Magenta: original queue outer edge and closed walkway. Black/red: retained entrance route and overlap.',
        'Replacement blocked: reconcile larger basement with upper walls, entrance supports and ride/support markers.',
        'No world blocks changed. Open queue edge is not promoted to a centreline, closed path or staircase.']):
        draw.text((24,910+24*i),text,fill='black')
    image.save(path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['world-directory','pdf-directory','review-directory','shop-directory','output']:p.add_argument('--'+name,required=True)
    a=p.parse_args(argv);r=run(a.world_directory,a.pdf_directory,a.review_directory,a.shop_directory,a.output)
    print(json.dumps({'heldout_residual_m':r['fit']['heldout_residual_m'],'replacement_gate':r['replacement_gate']['status']}))


if __name__=='__main__':main()
