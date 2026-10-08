"""Park-wide planning paving and bounded nearby OSM material inheritance."""
import argparse
import collections
import copy
import json
import math
from pathlib import Path
from pyproj import CRS,Transformer
from shapely.geometry import Point,shape,mapping
from shapely.ops import transform,unary_union
from shapely.strtree import STRtree
from .paving_palette import PALETTES,material_label,palette_block,palette_preview
from .terrain import Terrain
from .survey import activate_retained_grid
from .xsector import apply_overlay

KINDS={'path','plaza','queue','sidewalk','steps','cycleway'}


class NearbyMaterials:
    def __init__(self,features,distance=2):
        if not math.isfinite(distance) or not 0<=distance<=10:raise ValueError('Material proximity must be 0–10 metres')
        self.distance=distance
        self.features=[f for f in features if material_label(f['properties'].get('surface','')) is not None
                       and f['properties'].get('material_status')=='contained_native_floor_label']
        self.geometries=[shape(f['geometry']) for f in self.features]
        self.tree=STRtree(self.geometries)

    def match_geometry(self,geometry):
        """Transfer across the whole footprint only for a close polygon match."""
        matches=[]
        for i in self.tree.query(geometry.buffer(self.distance+1e-8)):
            donor=self.geometries[i]
            ratio=geometry.area/donor.area if donor.area else 0
            coverage=geometry.intersection(donor.buffer(self.distance)).area/geometry.area if geometry.area else 0
            boundary_distance=geometry.hausdorff_distance(donor)
            if not .5<=ratio<=2 or coverage<.75 or boundary_distance>self.distance+1e-8:continue
            props=self.features[i]['properties']
            matches.append({'status':'planning_material_inherited','surface':material_label(props['surface']),
                            'planning_feature':str(self.features[i].get('id',i)),
                            'distance_m':geometry.distance(donor),'coverage_fraction':coverage,
                            'max_boundary_distance_m':boundary_distance,
                            'area_ratio':ratio,'method':'close_footprint_match',
                            'document_id':props['document_id']})
        if not matches or len({m['surface'] for m in matches})!=1:return None
        return max(matches,key=lambda m:m['coverage_fraction'])

    def match(self,point):
        candidates=[]
        for i in self.tree.query(point.buffer(self.distance+1e-8)):
            geometry=self.geometries[i];d=geometry.distance(point)
            if d>self.distance+1e-8:continue
            props=self.features[i]['properties'];surface=material_label(props['surface'])
            # Overlap first, then nearest edge. Differing equidistant labels stay unresolved.
            candidates.append((d,str(self.features[i].get('id',i)),surface,int(i)))
        if not candidates:return None
        candidates.sort();best=candidates[0]
        if any(abs(c[0]-best[0])<.25 and c[2]!=best[2] for c in candidates[1:]):return {'status':'ambiguous_material_proximity'}
        return {'status':'planning_material_inherited','surface':best[2],
                'planning_feature':best[1],'distance_m':best[0],
                'document_id':self.features[best[3]]['properties']['document_id']}


def clipped_features(features,boundary,exclusions):
    result=[]
    for feature in features:
        polygon=shape(feature['geometry'])
        if not polygon.is_valid or polygon.geom_type not in ('Polygon','MultiPolygon'):continue
        polygon=polygon.intersection(boundary).difference(exclusions)
        if polygon.is_empty or polygon.geom_type not in ('Polygon','MultiPolygon'):continue
        result.append({**feature,'geometry':mapping(polygon)})
    return result


def emit_paving(mapped,planning,terrain,boundary,exclusions,proximity=2,max_cells=500000):
    plans=clipped_features(planning,boundary,exclusions)
    matcher=NearbyMaterials(plans,proximity);rows={};decisions=[];stats=collections.Counter()
    def emit(feature,planned=False):
        polygon=shape(feature['geometry']);props=feature['properties'];fid=feature.get('id','paving')
        surface=material_label(props.get('surface','')) or 'stone';floorlabel=props.get('material_status')=='contained_native_floor_label'
        whole_match=matcher.match_geometry(polygon) if not planned else None
        local=collections.Counter();transfers=collections.Counter();distances=[];skipped=0
        x0,z0,x1,z1=polygon.bounds
        if (x1-x0)*(z1-z0)>3000000:raise ValueError('Paving feature bounds exceed park budget')
        for x in range(math.floor(x0),math.ceil(x1)):
            for z in range(math.floor(z0),math.ceil(z1)):
                point=Point(x+.5,z+.5)
                if not polygon.covers(point):continue
                ground=terrain(x+.5,z+.5)
                if ground is None or not math.isfinite(ground):skipped+=1;continue
                chosen=surface;inherit=None
                if not planned:inherit=whole_match or matcher.match(point)
                if inherit and inherit['status']=='planning_material_inherited':
                    chosen=inherit['surface'];transfers[inherit['planning_feature']]+=1;distances.append(inherit['distance_m'])
                if inherit and inherit['status']=='ambiguous_material_proximity':stats['ambiguous_inheritance_cells']+=1
                origin=('planning_floor_label' if floorlabel else 'planning_paving_unspecified_material') if planned else 'nearby_planning_material_estimate' if inherit and inherit['status']=='planning_material_inherited' else 'osm_surface_palette' if props.get('surface') else 'generic_paving_palette_assumed'
                key=(x,math.floor(ground),z)
                row={'x':x,'y':key[1],'z':z,'kind':'plaza' if planned else props['kind'],
                     'material':palette_block(chosen,x,z),'feature':fid,'source':props.get('source_id','planning-paving'),
                     'surface':chosen,'material_origin':origin}
                if planned:row['document_id']=props.get('document_id')
                if inherit and inherit['status']=='planning_material_inherited':row['material_inheritance']=inherit
                if planned or key not in rows:rows[key]=row
                local[chosen]+=1
                if len(rows)>max_cells:raise ValueError('Park paving cell budget exceeded')
        decisions.append({'feature':fid,'source':'planning' if planned else 'osm','material_cells':dict(local),
                          'inherited_from':dict(transfers),'max_inheritance_distance_m':max(distances) if distances else None,
                          'missing_ground_cells':skipped,'document_id':props.get('document_id'),
                          'material_evidence':props.get('material_evidence',[]),'state':props.get('state'),
                          'whole_footprint_material_match':whole_match,
                          'registration_verified':props.get('registration_verified',False)})
    for f in clipped_features([f for f in mapped if f['properties'].get('kind') in KINDS
                              and f['properties'].get('bridge','no')=='no'
                              and f['properties'].get('tunnel','no')=='no'
                              and str(f['properties'].get('layer','0'))=='0'],boundary,exclusions):emit(f)
    # Broad unlabelled paving first; explicit material polygons win where overlap.
    for f in sorted(plans,key=lambda f:f['properties'].get('material_status')=='contained_native_floor_label'):emit(f,True)
    return list(rows.values()),{'features':decisions,'proximity_m':proximity,'overlay_records':len(rows),
                               'planning_polygons_after_clipping':len(plans),
                               'final_material_cells':dict(collections.Counter(r['surface'] for r in rows.values())),
                               'final_origin_cells':dict(collections.Counter(r['material_origin'] for r in rows.values())),
                               **dict(stats)}


def wicker_paving(source,project):
    collection=json.loads((source/'wicker-man-surface-candidates.geojson').read_text());result=[]
    for i,f in enumerate(collection['features']):
        props=copy.deepcopy(f['properties']);labels=props.get('contained_labels',[])
        materials={material_label(label) for label in labels}-{None}
        props['surface']=next(iter(materials)) if len(materials)==1 else 'paving_stones' if props.get('state')=='new' else 'stone'
        props['material_status']='contained_native_floor_label' if len(materials)==1 else 'unspecified_paving_approximation'
        props['material_evidence']=labels if materials else []
        result.append({'type':'Feature','id':f'planning-paving/wicker/{i}','geometry':mapping(transform(project,shape(f['geometry']))),'properties':props})
    return result


def generate(source,park,plans_dir,output,grid,proximity=2):
    source,park,plans_dir,output=map(Path,(source,park,plans_dir,output))
    quality=json.loads((source/'quality-report.json').read_text());config=json.loads((source/'resolved-config.json').read_text())
    crs=CRS.from_wkt(quality['crs']);project=Transformer.from_crs(4326,crs,always_xy=True)
    datum=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'));datum['coordinate_transform']['grid']['file']=grid;activate_retained_grid(datum)
    mapped=json.loads((park/'features-local.geojson').read_text())['features']
    boundary=transform(project.transform,shape(config['boundary_geojson']))
    exclusions=unary_union([shape(f['geometry']) for f in mapped if f['properties']['kind'] in ('building','water')])
    plans=json.loads((plans_dir/'park-planning-paving.geojson').read_text())['features']
    plans+=wicker_paving(park,project.transform)
    # Only explicit constituent labels may donate material to nearby OSM geometry.
    # Generic new-paving pattern is not evidence of brick or stone composition.
    terrain=Terrain(config['terrain'],crs,{s['id']:s for s in config['sources']})
    ride_cells=set()
    try:
        rows,report=emit_paving(mapped,plans,terrain.sample,boundary,exclusions,proximity)
        retained=quality.get('xsector_reconstruction',{})
        if retained.get('oblivion_reconstruction'):
            # Recover its existing cell mask only; no ride geometry is applied.
            from .oblivion_reconstruction import emit_track
            station=next(s for s in retained['stations'] if s['name']=='Oblivion Station')
            existing,detail=emit_track(retained['rides']['Oblivion'],station,terrain.sample)
            if detail['phase_model']!=retained['oblivion_reconstruction']['phase_model']:
                raise ValueError('Retained ride mask cannot be reproduced; refusing to alter ride cells')
            ride_cells={(r['x'],r['y'],r['z']) for r in existing}
    finally:terrain.close()
    # Protect retained ride shells/roofs and water at the exact composed cell.
    protected=set(ride_cells);mapped_cells=set()
    with (park/'voxels.jsonl').open() as stream:
        for line in stream:
            record=json.loads(line);key=(record['x'],record['y'],record['z'])
            if record['kind'] in ('structure','building','roof','water'):protected.add(key)
            if record['kind'] in KINDS:mapped_cells.add((record['x'],record['z']))
    before_count=len(rows)
    rows=[r for r in rows if (r['x'],r['y'],r['z']) not in protected]
    report.update(status='provisional_park_paving_generation',stations=[],
                  world_name='Alton Towers — Park Paths and Plazas',
                  planning_geometry_new_horizontal_cells=sum(r['source']=='planning-paving' and (r['x'],r['z']) not in mapped_cells for r in rows),
                  protected_cells_withheld=before_count-len(rows),
                  retained_ride_mask_cells=len(ride_cells),
                  final_material_cells=dict(collections.Counter(r['surface'] for r in rows)),
                  final_origin_cells=dict(collections.Counter(r['material_origin'] for r in rows)),
                  source_audit=json.loads((plans_dir/'park-planning-paving-audit.json').read_text()),
                  limitations=['Planning alignment is provisional and inherits Wicker Man registration',
                               'Historical/proposed surfaces are a draft, not independently verified present-day paving',
                               'Material proximity is an estimate, not proof of identical construction',
                               'Unspecified paving uses a generic stone palette; block-paving labels do not establish brick',
                               'Patterns approximate materials with vanilla blocks; exact colour and joint dimensions are not surveyed'])
    report['overlay_records']=len(rows)
    # View the retained Wicker entrance where the labelled brick paving is located.
    report['spawn_minecraft_xyz']=[-405,144,-96]
    apply_overlay(source,output,rows,report,report_key='park_paving',report_filename='park-paving-report.json')
    for name in ('park-planning-paving.geojson','park-planning-paving-audit.json'):
        import shutil
        shutil.copy2(plans_dir/name,output/name)
    (output/'paving-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (output/'paving-palettes.json').write_text(json.dumps(PALETTES,indent=2))
    palette_preview(output/'paving-palettes.png')
    print(json.dumps({k:report[k] for k in ('overlay_records','planning_polygons_after_clipping','planning_geometry_new_horizontal_cells','final_material_cells','world_verification')},indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-output',required=True);parser.add_argument('--park-output',required=True)
    parser.add_argument('--planning-output',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--datum-grid',required=True);parser.add_argument('--proximity-m',type=float,default=2)
    a=parser.parse_args();generate(a.source_output,a.park_output,a.planning_output,a.output,a.datum_grid,a.proximity_m)


if __name__=='__main__':main()
