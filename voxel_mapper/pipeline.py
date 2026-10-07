"""Location-only automatic acquisition through Bedrock world export."""
import datetime
import json
from pathlib import Path

from pyproj import Geod

from .acquisition import resolve_location, acquire_terrain, acquire_surface
from .cli import build, fetch_osm, validate_config
from .bedrock import export_world
from .planning import discover_planning, match_planning, SOURCE as PLANNING_SOURCE
from .council import acquire_council, SOURCE as COUNCIL_SOURCE
from .overture import acquire_buildings, supplement_buildings, SOURCE as OVERTURE_SOURCE


def run_auto(output, location=None, bounds=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Avoid stale successful exports being mistaken for a failed current run.
    if any(output.iterdir()):
        raise ValueError('Output directory must be empty; use a fresh directory per run')
    acquisition = {'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'automatic':True, 'providers':[]}
    manifest = output/'acquisition.json'
    config = {'voxel_size_m':1, 'max_area_m2':4_000_000, 'max_voxels':8_000_000,
              'max_column_checks':15_000_000, 'fallback_heights_m':{'building':6}, 'fallback_width_m':2}
    try:
        if bounds is None:
            bounds, result = resolve_location(location, output)
            config['location'] = result['display_name']
            if result.get('geojson',{}).get('type') in ('Polygon','MultiPolygon'):
                config['boundary_geojson'] = result['geojson']
                # The administrative/leisure outline excludes adjacent lakes.
                # Acquire a bounded context region rather than clipping to that outline.
                geod = Geod(ellps='WGS84')
                west,south,east,north = bounds
                west = geod.fwd(west,(south+north)/2,270,200)[0]
                east = geod.fwd(east,(south+north)/2,90,200)[0]
                south = geod.fwd((west+east)/2,south,180,200)[1]
                north = geod.fwd((west+east)/2,north,0,200)[1]
                bounds = [west,south,east,north]
                config['clip_to_boundary'] = False
                acquisition['context_margin_m'] = 200
        else:
            config['location'] = 'Specified geographic area'
        config['bbox'] = bounds
        validate_config(config)
        # Check geographic area before any terrain or OSM download.
        west,south,east,north = bounds
        geod = Geod(ellps='WGS84')
        geographic_area = abs(geod.polygon_area_perimeter([west,east,east,west],[south,south,north,north])[0])
        if geographic_area > config['max_area_m2']:
            raise ValueError('Area exceeds 4 km² build budget; select a smaller region')
        acquisition['bbox'] = bounds
        manifest.write_text(json.dumps(acquisition,indent=2))
        config['terrain'], terrain_source, attempts = acquire_terrain(bounds,output)
        acquisition['providers'].extend(attempts)
        config['sources'] = [terrain_source, {'id':'osm','url':'https://www.openstreetmap.org/copyright',
                             'license':'ODbL-1.0','attribution':'© OpenStreetMap contributors'}]
        config_surface, surface_source, surface_attempts = acquire_surface(bounds, output, terrain_source)
        acquisition['providers'].extend(surface_attempts)
        if config_surface:
            config['surface'] = config_surface
            config['sources'].append(surface_source)
            if surface_source.get('fallback_surface'):
                config['surface_fallback']=surface_source['fallback_surface']['config']
                config['sources'].append(surface_source['fallback_surface']['source'])
        manifest.write_text(json.dumps(acquisition,indent=2))
        collection, raw, skipped = fetch_osm(bounds)
        acquisition['providers'].append({'provider':'osm','status':'downloaded','feature_count':len(collection['features'])})
        (output/'osm-raw.json').write_text(json.dumps(raw))
        additional, overture = acquire_buildings(bounds,output)
        acquisition['providers'].append(overture)
        collection, overture_matches = supplement_buildings(collection,additional,bounds,overture.get('release'))
        (output/'overture-matches.json').write_text(json.dumps(overture_matches,indent=2))
        if overture['status'] in ('downloaded','empty_coverage_unknown'):
            config['sources'].append(OVERTURE_SOURCE)
        manifest.write_text(json.dumps(acquisition,indent=2))
        planning = discover_planning(bounds, output)
        collection, planning_matches = match_planning(collection, planning, bounds)
        (output/'planning-matches.json').write_text(json.dumps(planning_matches, indent=2))
        site_name = config['location'].split(',')[0].strip() if location else None
        if not site_name:
            names = {e.get('tags',{}).get('name') for e in raw.get('elements',[])
                     if e.get('tags',{}).get('leisure') == 'theme_park' and e.get('tags',{}).get('name')}
            if len(names) == 1:
                site_name = names.pop()
        council = acquire_council(planning_matches['authorities'],planning['records'],site_name,output,bounds=bounds)
        # Drawing adapters may supply registered, semantic, permission-checked
        # components. Raw PDF paths and application-site boundaries are excluded.
        collection['planning_geometry_records'] = council.get('geometry_records', [])
        if council['status'] != 'not_supported':
            config['sources'].append(COUNCIL_SOURCE)
        acquisition['providers'].append({'provider':council['provider'], 'status':council['status'],
            'application_search':council['application_search'], 'drawing_count':len(council['documents']),
            'failures':council['failures']})
        planning_summary = {k:v for k,v in planning.items() if k != 'records'}
        planning_summary['record_count'] = len(planning['records'])
        acquisition['providers'].append(planning_summary)
        if planning['status'] != 'not_supported':
            config['sources'].append(PLANNING_SOURCE)
        manifest.write_text(json.dumps(acquisition, indent=2))
        (output/'input.geojson').write_text(json.dumps(collection))
        (output/'resolved-config.json').write_text(json.dumps(config,indent=2))
        report = build(config,collection,output)
        report['supplemental_buildings'] = {'discovery':overture,'matching':overture_matches}
        if overture['status'] != 'downloaded' or overture_matches['added_physical_features']:
            report['issues'].append({'severity':'warning',
                'reason':'Supplemental building evidence is unavailable, empty, or includes unverified footprint/roofprint additions',
                'status':overture['status'],'added_features':overture_matches['added_physical_features']})
        report['planning_discovery'] = planning_summary
        report['planning_matches'] = planning_matches
        report['council_drawings'] = council
        report['issues'].append({'severity':'warning', 'reason':'Planning evidence/drawing inspection is unverified context; no verified as-built geometry replacement',
                                 'provider_status':planning['status'], 'documents':planning['documents']['status']})
        report['skipped_osm'] = skipped
        if skipped:
            report['issues'].append({'severity':'error','reason':'OSM features skipped','count':len(skipped)})
        if terrain_source['resolution_m'] > 1:
            report['issues'].append({'severity':'warning','reason':'Automatic fallback terrain is coarser than 1 m; voxel scale does not imply measured detail', 'resolution_m':terrain_source['resolution_m']})
        coordinate_transform = terrain_source.get('coordinate_transform', {})
        if coordinate_transform and not coordinate_transform.get('best_available', False):
            report['issues'].append({'severity':'warning','reason':'Best horizontal datum transformation unavailable', 'accuracy_m':coordinate_transform.get('accuracy_m')})
        # These absent adapters must never be mistaken for universal automatic completeness.
        report['capabilities'] = {'osm':'automatic', 'terrain':'automatic', 'surface':'automatic' if config_surface else 'unavailable',
                                  'transport_surfaces':'automatic_tagged_widths_and_materials',
                                  'bridge_decks':'automatic_unverified_surface_candidates' if config_surface else 'unavailable',
                                  'supplemental_buildings':overture['status'],
                                  'planning_records':'automatic_england_context' if planning['status'] == 'checked' else planning['status'],
                                  'planning_feature_matching':'automatic_spatial_candidates_only',
                                  'building_surface_profiles':'automatic_2_5d' if config_surface else 'unavailable',
                                  'planning_drawings':'automatic_consultation_inspection' if council['documents'] else council['status'],
                                  'planning_drawing_geometry':'verified_adapter_polygons' if any(
                                      d['status']=='accepted_verified_adapter_record' for d in report['planning_geometry_decisions']) else 'no_usable_geometry_provider',
                                  'lakebed_geometry':'measured_raster_supported_no_automatic_provider',
                                  'geopdf_registration':'automatic_wgs84_control_validation',
                                  'drawing_vector_candidates':'reuse_gated_straight_paths_only',
                                  'independent_accuracy_validation':'not_implemented', '3d_building_meshes':'not_implemented',
                                  'coaster_3d_geometry':'not_implemented', 'bedrock_world':'automatic'}
        report['issues'].append({'severity':'warning','reason':'Verified drawing geometry, independent surveyed control points, building meshes and 3D attraction geometry are not acquired by this pipeline'})
        if not config_surface:
            report['issues'].append({'severity':'warning','reason':'Surface-height acquisition unavailable; building heights/roofs use explicit tags or documented assumptions'})
        report['quality_status'] = 'draft_unverified'
        report['world'] = export_world(output/'voxels.jsonl',output,report,config['location'])
        (output/'quality-report.json').write_text(json.dumps(report,indent=2))
        acquisition['status'] = 'completed_draft'
        acquisition['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        manifest.write_text(json.dumps(acquisition,indent=2))
        return report
    except Exception as error:
        acquisition.update(status='failed', error=str(error))
        manifest.write_text(json.dumps(acquisition,indent=2))
        raise
