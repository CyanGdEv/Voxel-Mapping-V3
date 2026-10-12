"""Project retained context hypotheses onto imagery without image registration."""
import argparse, hashlib, json
from pathlib import Path
from xml.etree import ElementTree as ET
from pyproj import datadir, Transformer
from pyproj.transformer import TransformerGroup
from shapely.geometry import shape
from shapely.ops import transform as geometry_transform

PINNED = {
    'context': '58639eb20b641669aa9404e80b4dd00232b16b2caac242b18af7c484693013fd',
    'lidar': 'b4d282fd2e9a14b27417f4db04951327fbac48224fa63281dd6e8260b02ace6f',
    'imagery': '46292810f963704172108ba215122fbd176b01b22f87d06ac7e54bd33cc0d733',
    'svg': '05ff9037de11f0a577bc716dc11bb12cf4139b98cd7dc0280ea0ee68b9c1349f',
    'grid': '5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa',
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def overlay(paths):
    for name, path in paths.items():
        if digest(path) != PINNED[name]:
            raise ValueError(f'Pinned {name} input required')
    context, lidar, imagery = (json.loads(Path(paths[k]).read_text()) for k in ['context', 'lidar', 'imagery'])
    datadir.append_data_dir(str(Path(paths['grid']).resolve().parent))
    group = TransformerGroup(27700, 4326, always_xy=True)
    if not group.best_available:
        raise ValueError('Best datum transform unavailable')
    datum = next(t for t in group.transformers if 0 <= t.accuracy <= 1)
    mercator = Transformer.from_crs(4326, 3857, always_xy=True)
    resolution, _, _, _, xmin, ymax = imagery['tiles'][0]['pixel_to_epsg3857']
    def project(e, n, z=None):
        x, y = mercator.transform(*datum.transform(e, n))
        return (x - xmin) / resolution, (ymax - y) / resolution
    rows = []
    stable = next(e for e in lidar['envelopes'] if e['point_count'] == 505)
    for h in stable['hypotheses']:
        for key, label, colour in [('placed_main_roof_geometry', 'Main roof hypothesis', '#00ffff'),
                                   ('placed_canopy_geometry', 'Canopy hypothesis', '#ffde00' if h['rotation_degrees'] < 0 else '#ff64dd')]:
            pixel_geometry = geometry_transform(project, shape(h[key]))
            rows.append({'label': label, 'rotation_degrees': h['rotation_degrees'], 'colour': colour,
                         'geometry_mosaic_pixel_edges': pixel_geometry.__geo_interface__,
                         'registration_verified': False})
    station = geometry_transform(project, shape(context['station_complex_bng_geometry']))
    rows.append({'label': 'Mapped adjacent complex', 'colour': '#ff9a40',
                 'geometry_mosaic_pixel_edges': station.__geo_interface__, 'registration_verified': False})
    # Reuse the source SVG verbatim so no tile bytes or image enhancement change.
    svg = Path(paths['svg']).read_text()
    svg = svg.replace('height="930"', 'height="1030"').replace('0 0 800 930', '0 0 800 1030')
    annotations = ['<defs><clipPath id="mosaic"><rect x="25" y="100" width="750" height="750"/></clipPath></defs>', '<g fill="none" stroke-width="2.5" clip-path="url(#mosaic)">']
    for row in rows:
        geom = shape(row['geometry_mosaic_pixel_edges'])
        polygons = [geom] if geom.geom_type == 'Polygon' else list(geom.geoms)
        for polygon in polygons:
            for ring in [polygon.exterior, *polygon.interiors]:
                points = ' '.join(f'{25+x*375/256:.3f},{100+y*375/256:.3f}' for x, y in ring.coords)
                annotations.append(f'<polygon points="{points}" stroke="{row["colour"]}"/>')
    annotations.append('</g>')
    for y, colour, text in [(940, '#007c85', 'Cyan: provisional main roof · orange: mapped adjacent complex'),
                            (968, '#746000', 'Yellow: NE canopy hypothesis · pink: opposite canopy hypothesis'),
                            (996, '#222222', 'No image shift / rotation fitted · canopy identity unresolved')]:
        annotations.append(f'<text x="25" y="{y}" fill="{colour}" font-family="sans-serif" font-size="15">{text}</text>')
    svg = svg.replace('</svg>', '\n'.join(annotations) + '\n</svg>')
    ET.fromstring(svg)
    report = {'status': 'context_overlay_only', 'input_sha256': PINNED,
              'transform': {'datum_pipeline': datum.definition, 'datum_reported_accuracy_metres': datum.accuracy,
                            'mosaic_pixel_edges_to_epsg3857': [resolution, 0, 0, -resolution, xmin, ymax],
                            'mosaic_size_pixels': [512, 512], 'fitted_image_translation_pixels': [0, 0],
                            'fitted_image_rotation_degrees': 0},
              'overlays': rows, 'imagery_date_at_shop': imagery['image_acquisition_date'],
              'source_resolution_metres': imagery['source_resolution_metres'],
              'reported_imagery_accuracy_metres': imagery['reported_positional_accuracy_metres'],
              'review': {'main_roof_candidate_visible': True,
                        'rear_canopy_independently_identified': False,
                        'orientation_independently_resolved': False,
                        'reason': 'Main roof and nearby roof cluster are visible. The narrow attachment zone is not cleanly separable from roof edges, shadows and adjacent structures at this source resolution.'},
              'limitations': ['Mapped outlines and LiDAR fit are hypotheses, not image-derived measurements.',
                              'No manual image controls, canopy corners or image adjustment were introduced.',
                              '8.47 m reported imagery accuracy exceeds the 1 m control gate.',
                              'Shop-point acquisition citation is not a date verification for every mosaic pixel.'],
              'accepted_controls': 0, 'accepted_checkpoints': 0, 'world_geometry_additions': 0}
    return report, svg

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in [*PINNED, 'output', 'output-svg']:
        p.add_argument('--' + key, required=True)
    a = vars(p.parse_args())
    report, svg = overlay({k: a[k] for k in PINNED})
    Path(a['output']).write_text(json.dumps(report, indent=2) + '\n')
    Path(a['output_svg']).write_text(svg)
    print('Projected two stable roof/canopy hypotheses and adjacent complex; no registration accepted')

if __name__ == '__main__':
    main()
