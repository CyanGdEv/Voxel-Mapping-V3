"""Location-only automatic acquisition through Bedrock world export."""
import datetime
import json
from pathlib import Path

from pyproj import Geod

from .acquisition import resolve_location, acquire_terrain, acquire_surface
from .cli import build, fetch_osm, validate_config
from .bedrock import export_world


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
        manifest.write_text(json.dumps(acquisition,indent=2))
        collection, raw, skipped = fetch_osm(bounds)
        acquisition['providers'].append({'provider':'osm','status':'downloaded','feature_count':len(collection['features'])})
        (output/'osm-raw.json').write_text(json.dumps(raw))
        (output/'input.geojson').write_text(json.dumps(collection))
        (output/'resolved-config.json').write_text(json.dumps(config,indent=2))
        report = build(config,collection,output)
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
                                  'building_surface_profiles':'automatic_2_5d' if config_surface else 'unavailable', 'planning_drawings':'not_implemented',
                                  'independent_accuracy_validation':'not_implemented', '3d_building_meshes':'not_implemented',
                                  'coaster_3d_geometry':'not_implemented', 'bedrock_world':'automatic'}
        report['issues'].append({'severity':'warning','reason':'Planning drawings, independent surveyed control points, building meshes and 3D attraction geometry are not acquired by this pipeline'})
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
