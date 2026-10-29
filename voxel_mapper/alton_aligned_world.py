"""Build a bounded, native-metre Alton Towers Bedrock landscape.

The raster frame is BNG/ODN. OSM and historical planning are explicit layers;
imagery supplies appearance and conservative, local paving infill only.
Native classified LiDAR returns supply vegetation voxels and roof samples.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import zipfile

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy import ndimage as ndi
from shapely.affinity import affine_transform
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import transform

from .appearance_palettes import PALETTES, choose, coordinate_random
from .bedrock import ALLOWED_MATERIALS, PLAN_MARKING_WOOLS, VERSION, material_block
from .generation_cycles import atomic_json, file_hash
from .horizontal_grid import OSTN15Transform
from .osm_provisional_alignment import osm_collection
from .transport import transport_profile, TRANSPORT_KINDS
from .wicker_registration import apply_candidate

BUILD_VERSION = 'alton-aligned-world-v4'
WICKER_AFFINE = [0.9998213909931154, 0.01889936804739159,
                 -0.018899368047391618, 0.9998213909931155,
                 407471.9211529803, 343471.93766571034]
WICKER_IDS = {'osm/way/834919978', 'osm/way/834919980', 'osm/way/834919981'}
WICKER_VOXELS_SHA256 = '97288c18e52ffe71360e5c0cdc6b173554d400da4c296c6ac677863e267a404b'
MATERIAL_COLOURS = {
    'grass_block': (99, 137, 69), 'stone': (123, 125, 124),
    'stone_bricks': (139, 140, 136), 'cobblestone': (112, 118, 112),
    'terracotta': (155, 92, 66), 'mud_bricks': (139, 109, 82),
    'oak_planks': (167, 139, 87), 'granite': (145, 106, 90),
    'black_concrete': (38, 40, 43), 'gray_concrete': (84, 85, 89),
    'gray_wool': (76, 79, 84), 'water': (64, 129, 161),
    'dirt': (128, 98, 67), 'coarse_dirt': (126, 102, 72),
    'gravel': (138, 135, 127), 'sand': (204, 192, 144),
    'spruce_planks': (111, 81, 51), 'dark_oak_planks': (69, 49, 29),
}


def _json(path):
    return json.loads(Path(path).read_text())


def _local_mask(geometry, bounds, grid_shape):
    """Rasterise only a geometry's small window; preserve polygon holes."""
    e0, _, _, n1 = bounds
    h, w = grid_shape
    left, bottom, right, top = geometry.bounds
    c0, c1 = max(0, math.floor(left-e0)), min(w, math.ceil(right-e0))
    r0, r1 = max(0, math.floor(n1-top)), min(h, math.ceil(n1-bottom))
    if c0 >= c1 or r0 >= r1:
        return slice(0, 0), slice(0, 0), np.zeros((0, 0), bool)
    mask = rasterize([(mapping(geometry), 1)], out_shape=(r1-r0, c1-c0),
                     transform=from_origin(e0+c0, n1-r0, 1, 1), dtype='uint8') != 0
    return slice(r0, r1), slice(c0, c1), mask


def _paint(array, geometry, value, bounds):
    r, c, mask = _local_mask(geometry, bounds, array.shape)
    array[r, c][mask] = value
    return r, c, mask


def _native_roof(samples, footprint, floor, fallback):
    """Fill missing roof returns inside one footprint, retaining observed shape."""
    valid = footprint & np.isfinite(samples) & (samples > floor+1.5)
    if valid.any():
        _, indices = ndi.distance_transform_edt(~valid, return_indices=True)
        roof = samples[tuple(indices)]
        # A median filter removes isolated return spikes without inventing pitch.
        roof = ndi.median_filter(roof, size=3)
        roof = np.maximum(roof, floor+2.5)
        return roof, int(valid.sum())
    return np.full(samples.shape, floor+fallback, np.float32), 0


class ParkLayers:
    def __init__(self, work, wicker, surface_layers=None, reference_edits=None, lidar_detail=None):
        self.work, self.wicker = Path(work), Path(wicker)
        self.supplemental_sources = []
        if surface_layers:
            from .world_surface_layers import load_manifest
            self.supplemental_sources, self.surface_manifest_sha256 = load_manifest(surface_layers)
        self.wicker_quality = _json(self.wicker/'quality-report.json')
        if file_hash(self.wicker/'voxels.jsonl') != WICKER_VOXELS_SHA256:
            raise ValueError('The affine requires the pinned retained Wicker Man detail; a different build needs a new registration')
        self.frame = _json(self.work/'frame.json')
        self.bounds = self.frame['bounds_bng']
        self.e0, self.n0, self.e1, self.n1 = self.bounds
        self.width, self.height = self.e1-self.e0, self.n1-self.n0
        if self.width % 16 or self.height % 16 or self.width*self.height > 3_000_000:
            raise ValueError('Bounded, chunk-aligned native metre frame required')
        with rasterio.open(self.work/'inputs/survey/ea-national-dtm.tif') as ds:
            if ds.crs.to_epsg() != 27700 or tuple(ds.bounds) != tuple(self.bounds) or ds.res != (1, 1):
                raise ValueError('DTM must match the exact BNG frame')
            self.dtm = ds.read(1, masked=True).filled(np.nan)
        with rasterio.open(self.work/'inputs/survey/ea-national-dsm.tif') as ds:
            if tuple(ds.bounds) != tuple(self.bounds) or ds.res != (1, 1):
                raise ValueError('DSM must match the exact BNG frame')
            self.dsm = ds.read(1, masked=True).filled(np.nan)
        if not np.isfinite(self.dtm).all():
            raise ValueError('Complete terrain coverage required')
        survey_receipt = _json(self.work/'inputs/survey/survey-receipt.json')
        for kind in ('dtm', 'dsm'):
            if file_hash(self.work/f'inputs/survey/ea-national-{kind}.tif') != survey_receipt[kind+'_sha256']:
                raise ValueError('Terrain/surface raster checksum differs from receipt')
        self.offset = 64-math.floor(float(self.dtm.min()))
        self.ground = (np.rint(self.dtm).astype(np.int16)-1+self.offset)
        # NPZ indexing decompresses on every access; retain these bounded grids once.
        with np.load(self.work/'inputs/point-cloud-grids.npz') as archive:
            self.cloud = {key: archive[key] for key in archive.files}
        cloud_receipt = _json(self.work/'inputs/point-cloud-receipt.json')
        if file_hash(self.work/'inputs/point-cloud-grids.npz') != cloud_receipt['grid_file_sha256']:
            raise ValueError('Classified cloud grid checksum differs from receipt')
        if cloud_receipt['bounds_bng'] != self.bounds or cloud_receipt['survey_date'] != '2022-01-05':
            raise ValueError('Survey-matched classified cloud required')
        self.cloud_receipt = cloud_receipt
        specification = {'method': 'ostn15-bng-v1', 'path': self.frame['datum_grid']['file'],
                         'sha256': self.frame['datum_grid']['sha256']}
        self.project = OSTN15Transform(4326, 27700, specification)
        self.audit = {'version': BUILD_VERSION, 'bounds_bng': self.bounds,
                      'resolution_m': 1, 'vertical_offset_blocks': self.offset,
                      'sources': {}, 'geometry': {}, 'limitations': []}
        self._sample_rgb()
        self._map_layers()
        self._planning_layers()
        if self.supplemental_sources:
            from .world_surface_layers import apply_surfaces
            apply_surfaces(self, self.supplemental_sources, self.surface_manifest_sha256)
        self._paving()
        self._buildings()
        self._detail()
        if reference_edits:
            from .reference_world_scene import apply
            apply(self, reference_edits)
        if lidar_detail:
            from .lidar_detail import apply
            apply(self, lidar_detail)
        self._trees()
        self._spawn()
        self.audit['sources'] = {
            'osm': _json(self.work/'inputs/osm/snapshot.json'),
            'aerial': _json(self.work/'inputs/aerial-receipt.json'),
            'survey': _json(self.work/'inputs/survey/survey-receipt.json'),
            'point_cloud': cloud_receipt,
            'horizontal_operation': self.project.report(),
            'wicker': {'voxels_sha256': file_hash(self.wicker/'voxels.jsonl'),
                       'quality_report_sha256': file_hash(self.wicker/'quality-report.json'),
                       'nominal_plan_to_bng_affine': WICKER_AFFINE,
                       'method': 'Inverse nearest-cell categorical resampling; ODN levels preserved; 1 m voxel quantisation',
                       'physical_registration_verified': False}}
        self.audit['limitations'] = [
            'Draft multi-date landscape: 2022 LiDAR, current OSM snapshot and mixed historical planning; not a single-date as-built survey.',
            'Coordinate transformation is explicit OSTN15; physical OSM/aerial/planning registration has not been independently surveyed.',
            'Wicker Man retains the existing detailed build. Other buildings use mapped footprints and LiDAR/DSM roof estimates; missing roof coverage uses an estimated height.',
            'Other ride tracks, trains, mechanisms and ride vehicles have not been reconstructed.',
            'RGB appearance is a visual proxy, not measured material composition. Shadowed/occluded paving uses the nearest visible sample in the same material family.',
            'Raw classified foliage returns are voxelised; trunk locations and species are estimates. A 1 m grid cannot resolve every narrow edge.',
            'Lake levels are terrain estimates; beds are shallow visual shelves, not bathymetry. Dry-land foundations are artificial.',
            'Full rectangular landscape context surrounds the mapped park. Terrain beyond the export may be generated by Minecraft.',
            'Native block/state validation does not establish in-game visual fidelity; no Minecraft client was run.']
        if self.supplemental_sources:
            self.audit['limitations'].append('Supplemental surface interiors and explicitly digitised reference geometry are assistant source-assisted drafts, not independently reviewed truth. Annotation colours alone do not establish dimensions or heights.')
        if reference_edits:
            self.audit['limitations'] = [s for s in self.audit['limitations'] if not s.startswith('Other ride tracks,')]
            self.audit['limitations'].append('Reference update: mapped Galactica, Nemesis Reborn, The Smiler and monorail geometry is reconstructed. Their vertical profiles and support positions are estimates; inversions, banking and vehicles are not reconstructed. Source-assisted tunnel/theming geometry remains provisional.')

    def _sample_rgb(self):
        receipt = _json(self.work/'inputs/aerial-receipt.json')
        image = np.asarray(Image.open(self.work/'inputs/aerial.png').convert('RGB'), np.float32)
        if file_hash(self.work/'inputs/aerial.png') != receipt['image_sha256']:
            raise ValueError('Aerial source checksum differs')
        rows, cols = np.indices(self.dtm.shape)
        ee, nn = cols+self.e0+.5, self.n1-rows-.5
        lon, lat = self.project.inverse(ee, nn)
        xx, yy = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon, lat)
        left, bottom, right, top = receipt['extent_epsg3857']
        px = (xx-left)/(right-left)*image.shape[1]-.5
        py = (top-yy)/(top-bottom)*image.shape[0]-.5
        self.rgb = np.stack([ndi.map_coordinates(image[..., i], [py, px], order=1, mode='nearest') for i in range(3)], axis=-1)
        self.rgb = ndi.uniform_filter(self.rgb, size=(3, 3, 1))
        self.ee, self.nn = ee, nn
        if self.supplemental_sources:
            from .world_surface_layers import merge_rgb
            base_sampling = 1/np.hypot(np.gradient(px, axis=1), np.gradient(py, axis=1))
            merge_rgb(self, self.supplemental_sources, self.surface_manifest_sha256, base_sampling)
        self.chm = np.maximum(0, np.nan_to_num(self.dsm-self.dtm, nan=0))
        self.green = (self.rgb[..., 1] > self.rgb[..., 0]*1.07) & (self.rgb[..., 1] > self.rgb[..., 2]*1.08)
        self.visible = (self.chm < 1.5) & ~self.green & (self.rgb.mean(axis=-1) > 52)

    def _map_layers(self):
        collection, osm_digest, skipped = osm_collection(self.work/'inputs/osm/osm.xml')
        self.features, self.pois, self.building_features = [], [], []
        self.family = np.zeros(self.dtm.shape, np.uint8)  # 1 brick, 2 asphalt, 3 stone, 4 unpaved, 5 wood
        self.surface_source = np.zeros(self.dtm.shape, np.uint8)
        self.water = np.full(self.dtm.shape, -32768, np.int16)
        self.bridge = np.full(self.dtm.shape, -32768, np.int16)
        self.footprints = np.zeros(self.dtm.shape, bool)
        self.protected = np.zeros(self.dtm.shape, bool)
        counts, water_review, transport_review = Counter(), [], []
        scope = box(*self.bounds)
        for feature in collection['features']:
            props = feature['properties']; kind = props.get('kind', 'named-poi')
            geom = transform(self.project.transform, shape(feature['geometry']))
            if not geom.is_valid or geom.is_empty or not geom.intersects(scope):
                continue
            counts[kind] += 1
            row = {'id': feature['id'], 'geometry': geom, 'properties': props}
            self.features.append(row)
            if geom.geom_type == 'Point':
                self.pois.append(row); continue
            if kind == 'building':
                if geom.geom_type not in ('Polygon', 'MultiPolygon'): continue
                _paint(self.footprints, geom, True, self.bounds)
                if feature['id'] in WICKER_IDS:
                    _paint(self.protected, geom.buffer(3), True, self.bounds)
                else:
                    self.building_features.append(row)
            elif kind == 'water':
                if geom.geom_type not in ('Polygon', 'MultiPolygon'): continue
                r, c, mask = _local_mask(geom, self.bounds, self.dtm.shape)
                values = self.dtm[r, c][mask]
                if not len(values): continue
                q10, q50, q90 = np.percentile(values, [10, 50, 90])
                # Rivers follow local terrain; ponds/lakes require a dominant low plateau.
                flowing = props.get('water') in ('river', 'stream') or props.get('waterway') in ('river', 'stream', 'ditch')
                if flowing:
                    levels = np.rint(self.dtm[r, c][mask]).astype(np.int16)-1+self.offset
                    method = 'local terrain, flowing water'
                else:
                    low = values[values <= q10+1]
                    level = float(np.median(low)) if q90-q10 > 1 else float(q50)
                    levels = round(level)-1+self.offset
                    method = 'dominant low terrain plateau estimate' if q90-q10 > 1 else 'interior terrain median estimate'
                self.water[r, c][mask] = levels
                water_review.append({'id': row['id'], 'columns': int(mask.sum()), 'method': method,
                                     'dtm_p10_p50_p90_m': [float(q10), float(q50), float(q90)], 'bathymetry_measured': False})
        # Planning buildings can be untagged relation members in a newer OSM
        # snapshot. Protect their registered geometry independently of OSM IDs.
        preserved_footprints = [p['wall_geometry_nominal_local'] for p in self.wicker_quality['parts']]
        preserved_footprints.append(self.wicker_quality['maintenance']['wall_geometry_nominal_local'])
        for geometry in preserved_footprints:
            footprint = affine_transform(shape(geometry), WICKER_AFFINE)
            _paint(self.footprints, footprint, True, self.bounds)
            _paint(self.protected, footprint.buffer(3), True, self.bounds)
        # Polygons first, centreline corridors last; no building/water pixels are ground paving.
        for row in sorted(self.features, key=lambda f: f['geometry'].geom_type.endswith('LineString')):
            props, geom = row['properties'], row['geometry']; kind = props.get('kind', 'named-poi')
            if kind not in TRANSPORT_KINDS | {'parking'}: continue
            line = geom.geom_type in ('LineString', 'MultiLineString')
            profile = transport_profile(props, 'road' if kind == 'parking' else kind, line)
            footprint = geom.buffer(profile['width_m']/2, cap_style=2, join_style=2) if line else geom
            surface = props.get('surface', '')
            family = 2 if kind in ('road', 'parking') else 3
            if surface in ('asphalt',): family = 2
            elif surface in ('brick', 'bricks'): family = 1
            elif surface in ('ground', 'dirt', 'earth', 'gravel', 'fine_gravel', 'compacted', 'unpaved', 'sand'): family = 4
            elif surface == 'wood': family = 5
            r, c, mask = _paint(self.family, footprint, family, self.bounds)
            self.surface_source[r, c][mask] = 1
            transport_review.append({'id': row['id'], 'kind': kind, 'family': family,
                                     'width_m': profile['width_m'], 'width_source': profile['width_source'],
                                     'surface_tag': surface, 'geometry': 'OSM mapped footprint' if not line else 'buffered OSM centreline'})
            if props.get('bridge') in ('yes', 'viaduct', 'boardwalk'):
                local = self.dsm[r, c]; base = self.dtm[r, c]
                valid = mask & np.isfinite(local) & ((local-base) < 15)
                if valid.sum() >= .75*mask.sum() and valid.any():
                    # A bridge is one deck voxel, never a ground-fill dam.
                    deck = int(round(float(np.median(local[valid]))))-1+self.offset
                    self.bridge[r, c][mask] = deck
        self.audit['geometry'].update(osm_counts=dict(counts), osm_skipped_elements=len(skipped), osm_sha256=osm_digest,
                                      water=water_review, transport=transport_review)

    def _planning_layers(self):
        data = Path(__file__).parent/'data'
        review = []
        extension = _json(data/'alton-paving-extensions.geojson')
        for f in extension['features']:
            g = transform(self.project.transform, shape(f['geometry']))
            r, c, mask = _paint(self.family, g, 3, self.bounds)
            self.surface_source[r, c][mask] = 2
            review.append({'id': f['id'], 'document_id': f['properties']['document_id'],
                           'application': f['properties']['application_reference'],
                           'source_url': f['properties']['source_url'], 'status': 'historical provisional corridor',
                           'columns': int(mask.sum())})
        gardens = _json(data/'alton-gardens-v16.json')
        sources = {s['document_id']: s for s in gardens['sources']}
        by_title = {s['title']: s for s in gardens['sources']}
        def projected(geom, candidate):
            def convert(x, y, z=None):
                arr = apply_candidate(list(zip(x, y)), candidate)
                return arr[:, 0], arr[:, 1]
            return transform(convert, geom)
        for f in gardens['features']:
            if f['kind'] != 'path': continue
            g = projected(shape(f['native_geometry']), sources[f['document_id']]['alignment']['candidate'])
            if g.geom_type.endswith('LineString'): g = g.buffer(f['width_m']/2, cap_style=2)
            r, c, mask = _paint(self.family, g, 3, self.bounds)
            self.surface_source[r, c][mask] = 2
            review.append({'id': f['id'], 'document_id': f['document_id'], 'application': gardens['application'],
                           'status': 'historical garden survey alignment, provisional', 'columns': int(mask.sum())})
        for f in _json(data/'alton-garden-surfaces-v19.json')['surfaces']:
            src = by_title[f['sheet']]
            g = projected(Polygon(f['polygon']), src['alignment']['candidate'])
            r, c, mask = _paint(self.family, g, 2 if f['material']=='asphalt' else 3, self.bounds)
            self.surface_source[r, c][mask] = 2
            review.append({'id': f['id'], 'document_id': src['document_id'], 'application': gardens['application'],
                           'source_url': src['source_url'], 'material_evidence': f['material_evidence'],
                           'status': 'historical garden surface trace, provisional', 'columns': int(mask.sum())})
        self.audit['geometry']['planning_surfaces'] = review

    def _paving(self):
        blocked = self.footprints | (self.water > -32768)
        self.family[blocked] = 0
        self.surface_source[blocked] = 0
        # Conservative local image infill only, seeded by existing mapped paving.
        seed = (self.family > 0) & self.visible
        distance, nearest = ndi.distance_transform_edt(~seed, return_indices=True)
        near_rgb = self.rgb[tuple(nearest)]
        delta = np.sqrt(np.mean((self.rgb-near_rgb)**2, axis=-1))
        guide_exclusions = getattr(self, 'guide_exclusions', np.zeros(self.dtm.shape, bool))
        classified_roof = np.isfinite(self.cloud['roof']) & (self.cloud['roof'] > self.dtm+2)
        infill = (self.family == 0) & ~blocked & ~guide_exclusions & ~classified_roof & self.visible & (distance <= 4) & (delta <= 13)
        self.family[infill] = self.family[tuple(nearest)][infill]
        self.surface_source[infill] = 3
        # Explicit planting visible inside broad mapped plazas is an island, not paving.
        islands = (self.surface_source == 1) & (self.family == 3) & self.green & (self.chm < .6)
        components, _ = ndi.label(islands)
        sizes = np.bincount(components.ravel())
        islands &= sizes[components] >= 6
        self.family[islands] = 0
        self.surface_source[islands] = 0
        # Only unspecified pedestrian paving may acquire a warm brick family.
        warm = (self.rgb[..., 0] > self.rgb[..., 1]*1.08) & (self.rgb[..., 1] > self.rgb[..., 2]*1.04)
        self.family[(self.family == 3) & warm & self.visible & (self.surface_source != 2)] = 1
        self.material = np.full(self.dtm.shape, 'grass_block', dtype='U24')
        values, used = [], Counter()
        for family_id, family in ((1, 'brick'), (2, 'asphalt'), (3, 'stone')):
            mask = self.family == family_id
            if not mask.any(): continue
            samples = self.rgb.copy()
            # Nearest visible samples in the same family avoid interpreting canopy and hard shadow as darker asphalt.
            good = mask & self.visible
            if good.any():
                _, nearest_good = ndi.distance_transform_edt(~good, return_indices=True)
                samples[mask & ~good] = samples[tuple(nearest_good)][mask & ~good]
            else:
                samples[mask] = (150, 125, 100) if family == 'brick' else (100, 100, 100)
            chosen, strengths = choose(family, samples[mask], self.ee[mask].astype(int), self.nn[mask].astype(int))
            self.material[mask] = chosen
            used.update(chosen.tolist())
            values.append({'family': family, 'columns': int(mask.sum()), 'strength_mean': float(strengths.mean()),
                           'visible_rgb_columns': int(good.sum()), 'occluded_or_shadowed_columns': int((mask & ~good).sum())})
        self.material[self.family == 4] = 'coarse_dirt'
        self.material[self.family == 5] = 'oak_planks'
        self.audit['appearance'] = {'version': 'colour-strength-paving-v1', 'palettes': PALETTES,
                                     'families': values, 'block_recipe_counts': dict(used),
                                     'local_image_infill_columns': int(infill.sum()), 'retained_visible_grass_islands_columns': int(islands.sum()),
                                     'geometry_rule': 'Colour only changes existing paving; local 4 m infill requires low surface and visible compatible RGB. Buildings, water, classified roof returns and explicit guide exclusions screen infill.'}

    def _buildings(self):
        self.building_floor = np.full(self.dtm.shape, -32768, np.int16)
        self.roof_half = np.full(self.dtm.shape, -32768, np.int16)
        self.wall = np.zeros(self.dtm.shape, bool)
        self.roof_material = np.full(self.dtm.shape, 'stone_slab', dtype='U24')
        self.wall_material = np.full(self.dtm.shape, 'stone_bricks', dtype='U24')
        review = []
        for f in self.building_features:
            r, c, mask = _local_mask(f['geometry'], self.bounds, self.dtm.shape)
            mask &= ~self.protected[r, c]
            if not mask.any(): continue
            floor = float(np.percentile(self.dtm[r, c][mask], 70))
            try: fallback = min(35, max(2.5, float(f['properties'].get('height', float(f['properties'].get('building:levels', 1))*3))))
            except (ValueError, TypeError): fallback = 4
            # Class 6 returns are preferable to a DSM that may include trees above roofs.
            roof, observed = _native_roof(self.cloud['roof'][r, c], mask, floor, fallback)
            method = 'classified class-6 returns, nearest missing cells' if observed else 'estimated OSM/default height'
            if not observed:
                candidates = self.dsm[r, c].copy()
                candidates[(self.cloud['vegetation_count'][r, c] > 0) | (candidates > floor+45)] = np.nan
                candidate, count = _native_roof(candidates, mask, floor, fallback)
                if count >= max(3, .2*mask.sum()):
                    roof, observed, method = candidate, count, 'DSM surface without classified vegetation, missing cells estimated'
            half = np.rint((roof+self.offset)*2).astype(np.int16)
            self.roof_half[r, c][mask] = half[mask]
            self.building_floor[r, c][mask] = round(floor)-1+self.offset
            boundary = mask & ~ndi.binary_erosion(np.pad(mask, 1))[1:-1, 1:-1]
            self.wall[r, c][boundary] = True
            rgb = np.median(self.rgb[r, c][mask], axis=0)
            roof_mat = 'brick_slab' if rgb[0] > rgb[1]*1.16 else 'stone_slab'
            if rgb.mean() < 65: roof_mat = 'dark_oak_slab'
            self.roof_material[r, c][mask] = roof_mat
            self.wall_material[r, c][mask] = 'mud_bricks' if rgb[0] > rgb[1]*1.12 else 'stone_bricks'
            review.append({'id': f['id'], 'name': f['properties'].get('name'), 'columns': int(mask.sum()),
                           'observed_roof_columns': observed, 'roof_method': method,
                           'floor_odn_m': floor, 'roof_min_max_odn_m': [float(roof[mask].min()), float(roof[mask].max())],
                           'roof_form': 'half-block slabs, surface heights estimated', 'facades': 'generic hollow shell'})
        self.audit['geometry']['buildings'] = review

    def _detail(self):
        records = [json.loads(line) for line in (self.wicker/'voxels.jsonl').open()]
        source = defaultdict(list)
        for row in records: source[(row['x'], row['z'])].append(row)
        a, b, d, e, tx, ty = WICKER_AFFINE
        inverse = np.linalg.inv(np.array([[a, b], [d, e]]))
        source_extent = box(min(k[0] for k in source), min(k[1] for k in source),
                            max(k[0] for k in source)+1, max(k[1] for k in source)+1)
        extent = affine_transform(source_extent, WICKER_AFFINE)
        rs, cs, mask = _local_mask(extent, self.bounds, self.dtm.shape)
        detail, clear = defaultdict(list), defaultdict(list)
        markers, emitted = 0, Counter()
        source_air = defaultdict(set)
        for x, y, z in _json(self.wicker/'running-clearance-air.json'):
            source_air[(x, z)].add(y)
        for lr, lc in zip(*np.nonzero(mask)):
            r, c = rs.start+lr, cs.start+lc
            nx, nz = inverse @ np.array([self.e0+c+.5-tx, self.n1-r-.5-ty])
            column = (math.floor(nx), math.floor(nz))
            rows = source.get(column, [])
            if not rows: continue
            key = (c//16, (r-self.height)//16)
            terrain = [row for row in rows if row['kind'] == 'terrain']
            structures = [row for row in rows if row['kind'] != 'terrain']
            if terrain:
                top = max(terrain, key=lambda q: q['y'])
                material = top['material']
                if material in PLAN_MARKING_WOOLS | {'light_blue_concrete'}:
                    markers += 1
                elif material != 'grass_block':
                    self.ground[r, c] = top['y']+self.offset
                    self.material[r, c] = material
                    self.surface_source[r, c] = 4
                # Preserve source building/track grades, blending the outer terrain context.
                if structures or self.protected[r, c]:
                    self.ground[r, c] = top['y']+self.offset
            for row in structures:
                mat = row['material']
                if mat in PLAN_MARKING_WOOLS | {'light_blue_concrete'}: markers += 1; continue
                if mat not in ALLOWED_MATERIALS: raise ValueError('Unsupported retained detail: '+mat)
                detail[key].append((c % 16, row['y']+self.offset, (r-self.height) % 16, mat))
                emitted[mat] += 1
            for y in source_air.get(column, ()):
                clear[key].append((c % 16, y+self.offset, (r-self.height) % 16))
        self.detail, self.clear = dict(detail), dict(clear)
        self.audit['geometry']['wicker_detail'] = {'retained_blocks': int(sum(emitted.values())),
                    'materials': dict(emitted), 'discarded_diagnostic_guide_cells': markers,
                    'clearance_air_cells': int(sum(map(len, clear.values()))),
                    'source_scope': 'Shop, station/preshow, maintenance, queue, full track and dark-oak fence supports',
                    'preserved_source_planning_pins': self.wicker_quality['planning_source_pins']}

    def _trees(self):
        chm = np.nan_to_num(self.cloud['vegetation']-self.dtm, nan=0)
        peaks = (chm == ndi.maximum_filter(chm, size=9)) & (chm > 5)
        peaks &= ~ndi.binary_dilation(self.footprints, iterations=2) & (self.water == -32768) & (self.family == 0) & ~self.protected
        self.trunks = defaultdict(list)
        self.tree_species = np.floor(coordinate_random(self.ee.astype(int)//7, self.nn.astype(int)//7, 7)*3).astype(np.uint8)
        for r, c in zip(*np.nonzero(peaks)):
            base = int(self.ground[r, c])+1
            top = int(math.floor(self.cloud['vegetation'][r, c]+self.offset-2))
            top = max(base, min(top, base+25))
            wood = ('oak', 'spruce', 'birch')[self.tree_species[r, c]]
            self.trunks[(c//16, (r-self.height)//16)].append((c%16, base, (r-self.height)%16, top, wood+'_log'))
        self.audit['geometry']['vegetation'] = {'source_observed_foliage_voxels': int(len(self.cloud['leaf_voxels'])),
                    'estimated_trunks': int(peaks.sum()), 'species': 'coordinate-based visual proxies; not measured',
                    'policy': 'Classified observed foliage positions; exclude buildings, water, retained structures and path headroom'}

    def _spawn(self):
        points = [f for f in self.pois if f['properties'].get('name') == 'Towers Street']
        if not points: points = [f for f in self.pois if 'Entrance' in f['properties'].get('name', '')]
        p = points[0]['geometry'] if points else Point(self.e0+600, self.n1-250)
        c, r = int(p.x-self.e0), int(self.n1-p.y)
        candidates = (self.family > 0) & ~self.footprints & (self.water == -32768) & ~self.protected
        rr, cc = np.nonzero(candidates)
        index = np.argmin((rr-r)**2+(cc-c)**2)
        self.spawn = [int(cc[index]), int(self.ground[rr[index], cc[index]])+2, int(rr[index]-self.height)]
        self.waypoints = []
        names = ('Entrance', 'Towers Street', 'Wicker Man', 'Oblivion', 'The Smiler', 'Rita', 'Thirteen', 'Galactica', 'Nemesis', 'The Towers')
        for f in self.pois:
            name = f['properties'].get('name', '')
            if not any(n.lower() in name.lower() for n in names): continue
            c, r = int(f['geometry'].x-self.e0), int(self.n1-f['geometry'].y)
            if not (0 <= c < self.width and 0 <= r < self.height): continue
            self.waypoints.append({'name': name, 'source_id': f['id'], 'minecraft_x_y_z': [c, int(self.ground[r, c])+3, r-self.height],
                                   'role': 'mapped location; presence of a waypoint does not imply a reconstructed ride'})


def preview(layers, output):
    """North-up reconstruction review, not a Minecraft client screenshot."""
    rgb = np.zeros((*layers.dtm.shape, 3), np.uint8)
    for mat in np.unique(layers.material): rgb[layers.material == mat] = MATERIAL_COLOURS.get(mat, (125, 122, 115))
    rgb[layers.water > -32768] = MATERIAL_COLOURS['water']
    dy, dx = np.gradient(layers.dtm)
    shade = np.clip(.95-.14*dx+.18*dy, .60, 1.15)
    rgb = np.clip(rgb*shade[..., None], 0, 255).astype(np.uint8)
    buildings = layers.roof_half > -32768
    rgb[buildings] = (154, 142, 127)
    canopy = (layers.cloud['vegetation_count'] > 0) & (layers.chm > 2) & ~layers.footprints
    rgb[canopy] = np.clip(np.array([51, 97, 48])*shade[canopy, None], 0, 255).astype(np.uint8)
    for (cx, cz), rows in layers.detail.items():
        for x, y, z, mat in rows:
            c, r = cx*16+x, cz*16+z+layers.height
            rgb[r, c] = MATERIAL_COLOURS.get(mat, (145, 112, 65))
    extra_colours = {'white_concrete':(220,223,216),'light_gray_concrete':(165,170,166),
                     'red_concrete':(165,39,34),'iron_block':(193,196,192),
                     'oak_log':(114,83,45),'dark_oak_fence':(72,48,29),'dark_oak_planks':(64,43,27)}
    for (cx,cz), rows in getattr(layers,'reference_detail',{}).items():
        for x,y,z,mat in sorted(rows,key=lambda row:row[1]):
            c,r=cx*16+x,cz*16+z+layers.height
            rgb[r,c]=extra_colours.get(mat,MATERIAL_COLOURS.get(mat,(107,84,52)))
    im = Image.fromarray(rgb)
    draw = ImageDraw.Draw(im)
    for p in layers.waypoints:
        x, _, z = p['minecraft_x_y_z']; r = z+layers.height
        draw.ellipse((x-3, r-3, x+3, r+3), fill='white', outline='black')
        draw.text((x+5, r+3), p['name'], fill='white', stroke_width=2, stroke_fill='black')
    im.save(output/'Alton-Towers-Overview.png')
    Image.fromarray(np.clip(layers.rgb, 0, 255).astype(np.uint8)).save(output/'Aligned-Aerial-Review.png')
    swatch = Image.new('RGB', (850, 270), 'white'); draw = ImageDraw.Draw(swatch)
    for i, key in enumerate(PALETTES):
        x = i*170
        draw.text((x+8, 12), key.replace('_', ' '), fill='black')
        family = key.split('_')[0]
        sample = (190, 115, 85) if key == 'brick_strong' else (155, 147, 135) if family == 'brick' else (45, 47, 50) if key == 'asphalt_strong' else (140, 140, 140)
        rr, cc = np.indices((16, 12)); mats, _ = choose(family, np.full((16, 12, 3), sample), cc, rr)
        for r in range(16):
            for c in range(12):
                draw.rectangle((x+8+c*12, 40+r*12, x+18+c*12, 50+r*12), fill=MATERIAL_COLOURS[str(mats[r, c])])
    swatch.save(output/'Material-Palettes.png')


class ChunkRenderer:
    def __init__(self, layers):
        self.l = layers
        mats = set(layers.material.ravel()) | set(layers.roof_material.ravel()) | set(layers.wall_material.ravel())
        mats |= {'air', 'stone', 'dirt', 'water', 'grass_block', 'stone_slab', 'stone_slab_top',
                 'brick_slab_top', 'dark_oak_slab_top', 'oak_leaves', 'spruce_leaves', 'birch_leaves',
                 'oak_log', 'spruce_log', 'birch_log'}
        for rows in layers.detail.values(): mats.update(r[3] for r in rows)
        for rows in getattr(layers,'reference_detail',{}).values(): mats.update(r[3] for r in rows)
        for rows in getattr(layers,'lidar_detail',{}).values(): mats.update(r[3] for r in rows)
        if mats-ALLOWED_MATERIALS: raise ValueError('Unknown materials: '+str(mats-ALLOWED_MATERIALS))
        self.materials = ['air']+sorted(mats-{'air'})
        self.ids = {m: i for i, m in enumerate(self.materials)}
        self.ground_ids = np.zeros(layers.ground.shape, np.uint16)
        self.roof_ids = self.ground_ids.copy(); self.wall_ids = self.ground_ids.copy()
        for m, i in self.ids.items():
            self.ground_ids[layers.material == m] = i
            self.wall_ids[layers.wall_material == m] = i
        for r, c in zip(*np.nonzero(layers.roof_half > -32768)):
            top = int(layers.roof_half[r, c])
            m = layers.roof_material[r, c]
            self.roof_ids[r, c] = self.ids[m+('_top' if top % 2 == 0 else '')]

    def chunk(self, cx, cz):
        l = self.l; ids = self.ids
        r0, c0 = cz*16+l.height, cx*16
        rs, cs = slice(r0, r0+16), slice(c0, c0+16)
        ground = l.ground[rs, cs].copy()
        wet = l.water[rs, cs]; water = wet > -32768
        ground[water] = wet[water]-2
        floor, half = l.building_floor[rs, cs], l.roof_half[rs, cs]
        detail = l.detail.get((cx, cz), ())
        clear = l.clear.get((cx, cz), ())
        reference_detail = getattr(l,'reference_detail',{}).get((cx,cz),())
        reference_air = getattr(l,'reference_air',{}).get((cx,cz),())
        lidar_detail = getattr(l,'lidar_detail',{}).get((cx,cz),())
        bottom = int(min(ground.min(), floor[floor > -32768].min() if np.any(floor > -32768) else ground.min()))-4
        bottom = min(bottom, min((row[1] for row in detail), default=bottom), min((row[1] for row in clear), default=bottom))
        bottom = min(bottom,min((row[1]-2 for row in reference_detail),default=bottom),
                     min((row[1]-2 for row in reference_air),default=bottom))
        top = max(int(ground.max())+2, int(half.max()//2)+2,
                  int(l.bridge[rs, cs].max())+2,
                  max((row[1]+2 for row in detail), default=0),
                  max((row[1]+2 for row in clear), default=0),
                  int(np.nanmax(np.nan_to_num(l.cloud['vegetation'][rs, cs], nan=0)))+l.offset+2)
        top=max(top,max((row[1]+2 for row in reference_detail),default=top),max((row[1]+2 for row in reference_air),default=top))
        top=max(top,max((row[1]+2 for row in lidar_detail),default=top))
        bottom = max(-60, bottom); top = min(316, top)
        yy = np.arange(bottom, top+1)[None, :, None]
        g = ground.T[:, None, :]
        arr = np.zeros((16, top-bottom+1, 16), np.uint16)
        arr[np.broadcast_to(yy <= g, arr.shape)] = ids['stone']
        arr[np.broadcast_to((yy > g-3) & (yy < g), arr.shape)] = ids['dirt']
        xx, zz = np.indices((16, 16))
        arr[xx, ground.T-bottom, zz] = self.ground_ids[rs, cs].T
        for r, c in zip(*np.nonzero(water)):
            arr[c, ground[r, c]-bottom:wet[r, c]-bottom+1, r] = ids['water']
            arr[c, ground[r, c]-bottom, r] = ids['stone']
        for r, c in zip(*np.nonzero(floor > -32768)):
            f = int(floor[r, c]); roof_y = int(half[r, c]//2) if half[r, c] % 2 else int(half[r, c]//2)-1
            arr[c, max(0, ground[r, c]-bottom):f-bottom+1, r] = ids['stone_bricks']
            arr[c, f-bottom+1:roof_y-bottom, r] = self.wall_ids[r0+r, c0+c] if l.wall[r0+r, c0+c] else 0
            arr[c, roof_y-bottom, r] = self.roof_ids[r0+r, c0+c]
        # One-block bridge decks leave terrain/water underneath intact.
        for r, c in zip(*np.nonzero(l.bridge[rs, cs] > -32768)):
            y = int(l.bridge[r0+r, c0+c])-bottom
            if 0 <= y < arr.shape[1]:
                arr[c, y, r] = self.ground_ids[r0+r, c0+c] if l.family[r0+r, c0+c] else ids['stone_bricks']
        chunk_id = (r0//16)*(l.width//16)+cx
        offsets = l.cloud['leaf_chunk_offsets']
        leaf = l.cloud['leaf_voxels'][offsets[chunk_id]:offsets[chunk_id+1]]
        cells = (leaf & ((1 << 22)-1)).astype(np.int64)
        rr, cc = cells//l.width, cells % l.width
        ys = (leaf >> 22).astype(np.int64)-512+l.offset
        acceptable = ~l.footprints[rr, cc] & ~l.protected[rr, cc] & (l.water[rr, cc] == -32768)
        acceptable &= (ys > l.ground[rr, cc]+1) & ((l.family[rr, cc] == 0) | (ys > l.ground[rr, cc]+4))
        acceptable &= (ys >= bottom) & (ys <= top)
        rr, cc, ys = rr[acceptable], cc[acceptable], ys[acceptable]
        leaf_ids = np.array([ids[w+'_leaves'] for w in ('oak', 'spruce', 'birch')], np.uint16)[l.tree_species[rr, cc]]
        arr[cc % 16, ys-bottom, rr % 16] = leaf_ids
        for x, y, z, end, mat in l.trunks.get((cx, cz), ()):
            arr[x, max(0, y-bottom):min(top-bottom+1, end-bottom+1), z] = ids[mat]
        for x,y,z,mat in lidar_detail:
            if not bottom<=y<=top:raise ValueError('Observed LiDAR surface outside chunk envelope')
            arr[x,y-bottom,z]=ids[mat]
        for x,y,z in reference_air:
            if bottom<=y<=top:arr[x,y-bottom,z]=0
        for x,y,z,mat in reference_detail:
            if not bottom<=y<=top:raise ValueError('Reference structure outside native chunk envelope')
            arr[x,y-bottom,z]=ids[mat]
        # Clear retained riding headroom, then replay its actual structure last.
        for x, y, z in l.clear.get((cx, cz), ()):
            if bottom <= y <= top: arr[x, y-bottom, z] = 0
        for x, y, z, mat in detail:
            if not bottom <= y <= top: raise ValueError('Retained structure outside chunk envelope')
            arr[x, y-bottom, z] = ids[mat]
        sx, sy, sz = l.spawn
        if sx//16 == cx and sz//16 == cz:
            arr[sx % 16, sy-1-bottom:min(arr.shape[1], sy+3-bottom), sz % 16] = 0
        return arr, bottom


def _canonical(block, expected):
    return block.namespaced_name == expected.namespaced_name and all(block.properties.get(k) == v for k, v in expected.properties.items())


def export(layers, output, verify=True):
    from amulet.api.chunk import Chunk
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from amulet_nbt import ByteTag, IntTag, LongTag, StringTag
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    world = output/'bedrock-world'
    if world.exists(): raise ValueError('Refusing to overwrite an existing native world')
    renderer = ChunkRenderer(layers)
    blocks = [material_block(m) for m in renderer.materials]
    wrapper = LevelDBFormat(str(world)); wrapper.create_and_open('bedrock', VERSION)
    root = wrapper.root_tag.compound
    root['LevelName'] = StringTag('Alton Towers — LiDAR detail v4' if hasattr(layers,'lidar_detail') else 'Alton Towers — reference update v3' if hasattr(layers,'reference_detail') else 'Alton Towers — updated landscape' if layers.supplemental_sources else 'Alton Towers — aligned landscape draft')
    root['GameType'], root['Difficulty'] = IntTag(1), IntTag(0)
    root['RandomSeed'], root['Time'] = LongTag(0), LongTag(6000)
    for key, value in zip(('SpawnX', 'SpawnY', 'SpawnZ'), layers.spawn): root[key] = IntTag(value)
    for key, value in [('commandsEnabled', 1), ('showcoordinates', 1), ('spawnMobs', 0), ('doDaylightCycle', 0), ('doMobSpawning', 0), ('doWeatherCycle', 0), ('doTileDrops', 0)]: root[key] = ByteTag(value)
    root['randomTickSpeed'] = IntTag(0)
    coordinates = [(x, z) for z in range(-layers.height//16, 0) for x in range(layers.width//16)]
    counts = np.zeros(len(blocks), np.int64); start = time.monotonic()
    try:
        for index, (cx, cz) in enumerate(coordinates):
            arr, bottom = renderer.chunk(cx, cz)
            chunk = Chunk(cx, cz)
            palette = np.array([chunk.block_palette.get_add_block(block) for block in blocks], np.uint32)
            if palette[0] != 0: raise ValueError('Air must be palette index zero')
            chunk.blocks[:, bottom:bottom+arr.shape[1], :] = palette[arr]
            chunk.changed = True; wrapper.commit_chunk(chunk, 'minecraft:overworld')
            counts += np.bincount(arr.ravel(), minlength=len(blocks))
            if (index+1) % 500 == 0: print('Wrote chunks', index+1, '/', len(coordinates), flush=True)
        wrapper.save()
    finally:
        wrapper.close()
    verification = {'status': 'not_run'}
    if verify:
        wrapper = LevelDBFormat(str(world)); wrapper.open()
        checked, checked_cells = 0, 0
        try:
            actual = set(wrapper.all_chunk_coords('minecraft:overworld'))
            if actual != set(coordinates): raise ValueError('Native chunk coverage differs')
            for index, (cx, cz) in enumerate(coordinates):
                expected, bottom = renderer.chunk(cx, cz)
                chunk = wrapper.load_chunk(cx, cz, 'minecraft:overworld')
                observed_ids = np.asarray(chunk.blocks[:, bottom:bottom+expected.shape[1], :])
                # Translation must preserve every declared material property, not only occupancy.
                for code in np.unique(expected):
                    actual_codes = np.unique(observed_ids[expected == code])
                    if any(not _canonical(chunk.block_palette[int(i)], blocks[int(code)]) for i in actual_codes):
                        raise ValueError(f'Native material/state mismatch in {cx},{cz}: {renderer.materials[int(code)]}')
                solid = np.array([b.base_name != 'air' for b in chunk.block_palette])
                for sy in chunk.blocks.sub_chunks:
                    section = chunk.blocks.get_sub_chunk(sy)
                    yy = np.arange(sy*16, sy*16+16)
                    outside = (yy < bottom) | (yy >= bottom+expected.shape[1])
                    if np.any(solid[section[:, outside, :]]): raise ValueError('Unexpected solid outside rendered envelope')
                checked += 1; checked_cells += int(expected.size)
                if (index+1) % 1000 == 0: print('Verified chunks', index+1, '/', len(coordinates), flush=True)
        finally:
            wrapper.close()
        verification = {'status': 'passed', 'chunks': checked, 'compared_envelope_cells': checked_cells,
                        'all_unwritten_section_air_checked': True, 'material_properties_checked': True}
    layers.audit['native_world'] = {'target_bedrock_version': VERSION, 'chunks': len(coordinates),
            'occupied_blocks': int(counts[1:].sum()), 'materials': {m: int(n) for m, n in zip(renderer.materials, counts) if n and m != 'air'},
            'spawn_x_y_z': layers.spawn, 'round_trip': verification, 'minecraft_client_tested': False,
            'seconds': time.monotonic()-start, 'foundation': 'per-chunk minimum surface minus four blocks; artificial subsurface'}
    atomic_json(output/'world-report.json', layers.audit)
    atomic_json(output/'waypoints.json', layers.waypoints)
    atomic_json(world/'voxel-georeferencing.json', {**layers.frame, 'vertical_offset_blocks': layers.offset,
                'native_block_centres': 'E = origin_easting + X + 0.5; N = origin_northing - Z - 0.5',
                'block_height': 'ODN approximate solid top = Y - offset + 1; retained detail uses source integer ODN indices',
                'quality': 'draft_unverified'})
    shutil.copy2(output/'world-report.json', world/'voxel-quality-report.json')
    shutil.copy2(output/'waypoints.json', world/'waypoints.json')
    shutil.copy2(layers.wicker/'quality-report.json', world/'Wicker-Man-Retained-Detail-Report.json')
    (world/'ATTRIBUTION.txt').write_text('OpenStreetMap contributors © ODbL-1.0 — https://www.openstreetmap.org/copyright\nContains Environment Agency information © Environment Agency and/or database right, OGL-UK-3.0.\nEsri World Imagery and imagery providers — source metadata retained in voxel-quality-report.json. Provider RGB source imagery is not included in this world archive.\nHistorical planning: Staffordshire Moorlands District Council public planning applications; document identifiers and source URLs retained in report.\n', encoding='utf-8')
    preview(layers, output)
    package(output)
    return layers.audit


def package(output):
    output = Path(output); world = output/'bedrock-world'
    package_path = output/'Alton-Towers-Aligned-World.mcworld'
    with zipfile.ZipFile(package_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(world.rglob('*')):
            if file.is_file() and file.name != 'LOCK': archive.write(file, file.relative_to(world))
    with zipfile.ZipFile(package_path) as archive:
        if archive.testzip(): raise ValueError('World ZIP integrity check failed')
        if 'level.dat' not in archive.namelist() or not any(n.startswith('db/') for n in archive.namelist()):
            raise ValueError('Native Bedrock files missing')
    atomic_json(output/'export-receipt.json', {'file': package_path.name, 'bytes': package_path.stat().st_size,
                'sha256': file_hash(package_path), 'format': 'Bedrock .mcworld', 'zip_crc': 'passed',
                'world_report_sha256': file_hash(output/'world-report.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True); parser.add_argument('--wicker', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--surface-layers', help='Pinned clean imagery and partial source-assisted surface interiors; sparse trace masks are rejected')
    parser.add_argument('--reference-edits',help='Pinned source-assisted boundaries, classified survey objects and mapped ride geometry')
    parser.add_argument('--lidar-detail',help='Matched native-return receipt for quarter-metre structural sampling and supported roof details')
    args = parser.parse_args(); output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    layers = ParkLayers(args.work, args.wicker, args.surface_layers, args.reference_edits, args.lidar_detail)
    if args.prepare_only:
        atomic_json(output/'layer-report.json', layers.audit); preview(layers, output)
    else:
        export(layers, output)


if __name__ == '__main__': main()
