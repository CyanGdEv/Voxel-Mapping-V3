"""Add explicitly reviewed source footprints with hypothetical heights to a shell study."""
import copy,hashlib,json,math
from shapely.geometry import LineString,Polygon,box,shape
from .wing_shell_study import solid
from .wing_block_shapes import occupied_halves

VERSION='wing-interior-partition-study-v1'


def apply(model,cells,audit,review,seed):
    if seed.get('version')!=VERSION or seed.get('source_footprint_reviewed') is not True or seed.get('parent_model_sha256')!=model['parent_model_sha256']:
        raise ValueError('Explicit source footprint review and parent pin required')
    if hashlib.sha256(json.dumps(review,sort_keys=True).encode()).hexdigest()!=seed.get('review_sha256'):
        raise ValueError('Partition review checksum changed')
    height=seed.get('display_height_m');chosen=seed.get('selected_band_ids')
    if type(height) not in (int,float) or not math.isfinite(height) or not 1.5<=height<=min(3,model['measurements']['eaves_m']):raise ValueError('Bounded hypothetical partition height required')
    if not isinstance(chosen,list) or not 1<=len(chosen)<=16 or len(set(chosen))!=len(chosen):raise ValueError('Unique bounded reviewed bands required')
    if review.get('status')!='source_partition_candidates_only' or review['source_pdf_sha256']!=model['source_pdf_sha256']['plan']:raise ValueError('Same complete plan review required')
    bands={b['id']:b for b in review['bands']};segments={r['id']:r for r in review['segments']};components={r['id']:r for r in review['source_components']}
    new_model=copy.deepcopy(model);result=dict(cells);new_audit=copy.deepcopy(audit);added=[];rows=[]
    for identifier in chosen:
        if identifier not in bands:raise ValueError('Reviewed band missing')
        band=bands[identifier];g=shape(band['local_geometry']);source=shape(band['geometry']);sides=[]
        for ref in band['source_line_references']:
            record=segments[ref['component_id']];proof=record['source_segment'];original=components[proof['component_id']]
            if ref['component_contract']!=record['extraction_contract']:raise ValueError('Partition segment contract changed')
            original_geom=shape(original['geometry']);chains=[original_geom.coords] if original_geom.geom_type=='LineString' else [original_geom.exterior.coords,*[r.coords for r in original_geom.interiors]]
            points=list(chains[proof['ring_index']]);p,q=points[proof['segment_index']:proof['segment_index']+2]
            if [list(p),list(q)]!=proof['native_endpoints'] or shape(record['geometry']).coords[:]!=[p,q] or original['extraction_contract']!=proof['component_contract']:
                raise ValueError('Original partition segment proof changed')
            if review.get('version')=='wing-source-segment-partition-review-v2':
                operators=proof.get('literal_operator_proofs',[]);paint_ordinals={p['ordinal'] for p in original['paint_references']}
                from .literal_path_edges import key
                if not operators or any(o.get('operator') not in ('l','re','qu') or o.get('paint_ordinal') not in paint_ordinals or key(*o['native_endpoints'])!=key(p,q) for o in operators):
                    raise ValueError('Literal original operator proof changed')
            lo,hi=ref['source_interval_fraction']
            if not all(type(v) in (int,float) and math.isfinite(v) for v in (lo,hi)) or not 0<=lo<hi<=1:raise ValueError('Original source interval required')
            line=LineString([p,q]);side=LineString([line.interpolate(lo,normalized=True),line.interpolate(hi,normalized=True)])
            if side.difference(source.boundary.buffer(1e-7)).length>1e-7:raise ValueError('Partition band side disagrees with source')
            sides.append(side)
        if len(sides)!=2:raise ValueError('Two original sides required')
        reconstructed=Polygon([sides[0].coords[0],sides[0].coords[1],sides[1].coords[1],sides[1].coords[0]])
        if not reconstructed.is_valid:reconstructed=Polygon([sides[0].coords[0],sides[0].coords[1],sides[1].coords[0],sides[1].coords[1]])
        if reconstructed.symmetric_difference(source).area>1e-7:raise ValueError('Partition polygon disagrees with original sides')
        from shapely.affinity import affine_transform
        if affine_transform(source,review['native_to_local_matrix']).symmetric_difference(g).area>1e-8:raise ValueError('Partition local transform changed')
        x0,z0,x1,z1=g.bounds
        if z1-z0<5*(x1-x0):raise ValueError('Only transverse source partition strips supported')
        keep_gaps=seed.get('preserve_partition_endpoint_gaps',False)
        if type(keep_gaps) is not bool:raise ValueError('Explicit endpoint clearance policy required')
        gap_columns=[];wall_thickness=model['thicknesses_m']['wall'];depth=model['measurements']['depth_m']
        if keep_gaps:
            if .5<=z0-wall_thickness<2:gap_columns.append(max(1,math.floor(z0)))
            if .5<=depth-wall_thickness-z1<2:gap_columns.append(min(audit['native_grid'][1]-2,math.floor(z1)))
        new_model['components'].append({'id':'interior_partition_'+identifier[:12],'evidence':'explicitly reviewed source footprint; hypothetical height',
                                        'mesh':solid(g,2,0,height),'source_band_id':identifier,'height_measured':False})
        part_added=[]
        for z in range(math.floor(z0),math.ceil(z1)):
            if z in gap_columns:continue
            choices=[(g.intersection(box(x,z,x+1,z+1)).area,x) for x in range(math.floor(x0),math.ceil(x1))]
            area,x=max(choices,key=lambda r:(r[0],-r[1]))
            if area<=1e-9 or min(z+1,z1)-max(z,z0)<.5:continue
            for y in range(math.ceil(height)):
                material='stone_brick_slab' if height-y<=.5 else 'stone_bricks';p=(x,y,z)
                if p in result:continue
                result[p]=material;part_added.append({'cell':list(p),'material':material,'source_band_id':identifier})
        added.extend(part_added);rows.append({'source_band_id':identifier,'source_footprint':band['local_geometry'],'display_height_m':height,'height_measured':False,
                                            'native_one_block_thickness_is_quantization':True,'added_cells':len(part_added),
                                            **({'native_endpoint_gap_columns':gap_columns,'gap_identity_verified':False,
                                                'source_front_gap_to_display_wall_m':z0-wall_thickness,
                                                'source_rear_gap_to_display_wall_m':depth-wall_thickness-z1} if keep_gaps else {})})
        for z in gap_columns:
            candidates=[(g.intersection(box(x,z,x+1,z+1)).area,x) for x in range(math.floor(x0),math.ceil(x1))]
            _,x=max(candidates,key=lambda r:(r[0],-r[1]))
            occupied=occupied_halves(result)
            if any((2*x+dx,hy,2*z+dz) in occupied for dx in (0,1) for hy in range(4) for dz in (0,1)):
                raise ValueError('Retained shell obstructs partition endpoint gap')
        if keep_gaps:rows[-1]['native_endpoint_gap_air_verified']=True
    half=occupied_halves(result)
    for x in audit['arch_columns']:
        for z in range(audit['native_grid'][1]):
            if any((2*x+dx,hy,2*z+dz) in half for dx in (0,1) for hy in range(4) for dz in (0,1)):raise ValueError('Partition obstructs arch standing clearance')
    if any(result[p]!=m for p,m in cells.items()):raise ValueError('Partition overwrote retained shell cells')
    new_model['partition_study']={'version':VERSION,'review_sha256':seed['review_sha256'],'rows':rows,'room_inventory_complete':False}
    new_model['assumptions']=[s.replace('Room partitions, upper floors','Remaining room partitions, upper floors') for s in new_model['assumptions']]
    new_model['assumptions'].append('Added partition footprints follow selected original plan sides; height and native thickness remain display hypotheses. Other room walls are unresolved.')
    new_audit.update(partition_study=new_model['partition_study'],partition_added_cells=added,total_surface_cells=len(result),retained_shell_cells_unchanged=True,assumptions=new_model['assumptions'])
    return new_model,result,new_audit
