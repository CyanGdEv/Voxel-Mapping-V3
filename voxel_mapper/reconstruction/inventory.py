"""Park-independent coverage inventory; discovery does not imply usable geometry."""
from collections import Counter


def source_inventory(raw,planning_records,acquisition,sources,heritage_records=()):
    candidates=[]
    for element in raw.get('elements',[]):
        tags=element.get('tags',{});family=None;needs=[]
        if tags.get('roller_coaster')=='track':family='track';needs=['3D profile','cross-section','supports','clearance']
        elif tags.get('aerialway'):family='cable';needs=['cable levels and sag','pylons','station geometry']
        elif tags.get('railway')=='monorail':family='beam';needs=['beam levels','cross-section','piers']
        elif tags.get('barrier'):family='wall';needs=['height','material']
        elif tags.get('building'):family='building_shell';needs=['roof/wall heights','openings','facade']
        elif tags.get('highway') or tags.get('area:highway'):family='paving';needs=['surface material','width for lines']
        elif tags.get('attraction'):family='ride_extent';needs=['physical track or structure geometry; extent is not a ride mesh']
        if family:candidates.append({'id':f"osm/{element['type']}/{element['id']}",'name':tags.get('name'),'family':family,
                                     'geometry_points':len(element.get('geometry',[])),'needed_evidence':needs,
                                     'status':'mapped_candidate; not reconstructed'})
    candidates.extend(heritage_records)
    return {'providers':acquisition.get('providers',[]),'sources':sources,'mapped_candidates':candidates,
            'candidates_by_family':dict(Counter(c['family'] for c in candidates)),
            'planning_adapter_records':len(planning_records),
            'available_existing_adapters':['OSM/Overpass','registered GeoJSON','planning record validation','Overture buildings','terrain/DSM rasters','classified building LiDAR returns','reviewed orthophoto paving masks','NHLE heritage discovery (no extrusion)'],
            'unimplemented_adapters':['general CAD/BIM meshes','photogrammetric meshes','unclassified ride point clouds'],
            'limitations':['Availability, registration, vertical datum and material/profile evidence are checked separately.','No promise of complete geometry for every attraction; unsupported components remain listed.']}
