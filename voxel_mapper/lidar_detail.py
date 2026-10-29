"""Retain native structural returns and sample roofs without metre-grid smoothing.

Quarter-metre bins index evidence; they do not create additional survey returns.
Ground, vegetation and supported class-6 surfaces cover the whole park frame.
"""
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import time
import zipfile

import laspy
import numpy as np
from scipy.spatial import cKDTree
from shapely import contains_xy

from .generation_cycles import atomic_json, file_hash
from .point_cloud import is_bng

VERSION = 'alton-lidar-detail-v1'


def export_native_crop(archive, source_receipt, bounds, destination):
    """Retain the full-precision, unthinned park cloud as a standard LAZ file."""
    prior = json.loads(Path(source_receipt).read_text())
    if (prior.get('crs') != 'EPSG:27700' or prior.get('vertical_datum') != 'ODN'
            or prior.get('survey_date') != '2022-01-05'
            or file_hash(archive) != prior['archive_sha256']):
        raise ValueError('Pinned native survey archive required')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite native point evidence')
    e0,n0,e1,n1 = bounds
    if not (e0 < e1 and n0 < n1 and (e1-e0)*(n1-n0) <= 3_000_000):
        raise ValueError('Bounded park rectangle required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    scanned = retained = 0
    classes = Counter()
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) != 1 or entries[0].filename != prior['entry']:
                raise ValueError('Pinned dated LAZ entry required')
            with bundle.open(entries[0]) as stream, laspy.open(stream) as reader:
                if not is_bng(reader.header.parse_crs()) or reader.header.point_count != prior['scanned_points']:
                    raise ValueError('Native point-cloud header differs')
                with laspy.open(destination, mode='w', header=copy.deepcopy(reader.header), do_compress=True) as writer:
                    for points in reader.chunk_iterator(500_000):
                        scanned += len(points)
                        x,y,z = np.asarray(points.x),np.asarray(points.y),np.asarray(points.z)
                        valid = ((x>=e0)&(x<e1)&(y<=n1)&(y>n0)&np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
                                 &~np.asarray(points.withheld,bool)&~np.asarray(points.synthetic,bool))
                        subset = points[valid]
                        if len(subset):
                            writer.write_points(subset)
                            retained += len(subset)
                            codes,counts = np.unique(np.asarray(subset.classification),return_counts=True)
                            classes.update({int(k):int(v) for k,v in zip(codes,counts)})
        if scanned != prior['scanned_points'] or not retained:
            raise ValueError('Truncated native source or empty park crop')
        with laspy.open(destination) as reader:
            if reader.header.point_count != retained or not is_bng(reader.header.parse_crs()):
                raise ValueError('Native LAZ export does not reopen correctly')
        result = {'version':VERSION, 'file':destination.name, 'bytes':destination.stat().st_size,
                  'sha256':file_hash(destination), 'bounds_bng':list(bounds), 'crs':'EPSG:27700',
                  'vertical_datum':'ODN', 'survey_id':prior['survey_id'], 'survey_date':prior['survey_date'],
                  'archive_sha256':prior['archive_sha256'], 'url':prior['url'],
                  'scanned_points':scanned, 'retained_points':retained, 'classes':dict(classes),
                  'all_source_point_fields_and_scales_preserved':True, 'random_subsampling':False,
                  'withheld_and_synthetic_excluded':True, 'license':'OGL-UK-3.0',
                  'attribution':prior.get('attribution','Contains Environment Agency information')}
        atomic_json(destination.with_suffix('.json'),result)
        return result
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def sample_archive(archive, source_receipt, bounds, output):
    """Index every eligible return at 0.25 m; also retain raw class-1/6 XYZ."""
    archive, output = Path(archive), Path(output)
    prior = json.loads(Path(source_receipt).read_text())
    if (prior.get('crs') != 'EPSG:27700' or prior.get('vertical_datum') != 'ODN'
            or prior.get('survey_date') != '2022-01-05'):
        raise ValueError('Matched native BNG/ODN survey receipt required')
    if file_hash(archive) != prior['archive_sha256']:
        raise ValueError('Point-cloud archive checksum differs')
    e0, n0, e1, n1 = bounds
    if not (e0 < e1 and n0 < n1 and (e1-e0)*(n1-n0) <= 3_000_000):
        raise ValueError('Bounded park rectangle required')
    output.mkdir(parents=True, exist_ok=True)
    destination = output / 'lidar-detail-samples.npz'
    if destination.exists():
        raise ValueError('Refusing to overwrite retained LiDAR detail')
    coordinates, codes, fine_keys = [], [], []
    classes = Counter()
    scanned = eligible = flagged = 0
    started = time.monotonic()
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) != 1 or entries[0].filename != prior['entry']:
            raise ValueError('Pinned dated LAZ entry required')
        with bundle.open(entries[0]) as stream, laspy.open(stream) as reader:
            if (not is_bng(reader.header.parse_crs())
                    or reader.header.point_count != prior['scanned_points']):
                raise ValueError('Point-cloud native CRS or point count differs')
            for points in reader.chunk_iterator(500_000):
                scanned += len(points)
                x, y, z = np.asarray(points.x), np.asarray(points.y), np.asarray(points.z)
                inside = ((x >= e0) & (x < e1) & (y <= n1) & (y > n0)
                          & np.isfinite(x) & np.isfinite(y) & np.isfinite(z))
                bad = np.asarray(points.withheld, bool) | np.asarray(points.synthetic, bool)
                flagged += int(np.count_nonzero(inside & bad))
                valid = inside & ~bad
                labels = np.asarray(points.classification)
                eligible += int(valid.sum())
                values, counts = np.unique(labels[valid], return_counts=True)
                classes.update({int(k): int(v) for k, v in zip(values, counts)})
                qx = np.floor((x[valid]-e0)*4).astype(np.uint64)
                qr = np.floor((n1-y[valid])*4).astype(np.uint64)
                qz = np.floor(z[valid]*4).astype(np.int64)+2048
                if (np.any(qx >= 1 << 14) or np.any(qr >= 1 << 14)
                        or np.any((qz < 0) | (qz >= 1 << 13))):
                    raise ValueError('Quarter-metre index coordinate budget exceeded')
                fine_keys.append(qx | (qr << 14) | (qz.astype(np.uint64) << 28)
                                 | (labels[valid].astype(np.uint64) << 41))
                structural = valid & np.isin(labels, [1, 6])
                if structural.any():
                    coordinates.append(np.column_stack([x[structural], y[structural], z[structural]]))
                    codes.append(labels[structural])
                if scanned % 10_000_000 == 0:
                    print('Scanned native points', scanned, 'eligible local points', eligible, flush=True)
    if scanned != prior['scanned_points'] or not coordinates:
        raise ValueError('Truncated cloud or no native structural evidence')
    xyz = np.concatenate(coordinates)
    labels = np.concatenate(codes)
    # Keep exact original XYZ as well as a sparse 3-D index. No max-height collapse.
    keys, counts = np.unique(np.concatenate(fine_keys), return_counts=True)
    np.savez_compressed(destination, xyz=xyz, classification=labels,
                        quarter_keys=keys, quarter_counts=counts.astype(np.uint32))
    qx, qr, qz, qclass = decode_quarter(keys)
    coarse = ((qx//4).astype(np.uint64) | ((qr//4).astype(np.uint64) << 14)
              | ((qz//4+512).astype(np.uint64) << 28) | (qclass.astype(np.uint64) << 41))
    unique_native = np.unique(coarse)
    spatial_native = np.unique(unique_native & np.uint64((1 << 41)-1))
    _, layers = np.unique(spatial_native & np.uint64((1 << 28)-1), return_counts=True)
    receipt = {
        'version': VERSION, 'crs': 'EPSG:27700', 'vertical_datum': 'ODN',
        'survey_id': prior['survey_id'], 'survey_date': prior['survey_date'],
        'url': prior['url'], 'archive_sha256': prior['archive_sha256'],
        'entry': prior['entry'], 'bounds_bng': list(bounds),
        'scanned_points': scanned, 'eligible_local_points': eligible,
        'excluded_local_withheld_or_synthetic_points': flagged,
        'eligible_class_counts': dict(classes), 'retained_classes': [1, 6],
        'retained_native_xyz_points': len(xyz), 'random_subsampling': False,
        'sampling_xy_m': .25, 'sampling_z_m': .25,
        'index_is_sparse_3d_not_highest_return_grid': True,
        'raw_xyz_preserved': True, 'quarter_metre_evidence_cells': len(keys),
        'quarter_index_covers_all_eligible_classes': True,
        'quarter_index_classes': sorted(classes),
        'quarter_index_points_accounted_for': int(counts.sum()),
        'one_metre_evidence_cells': len(unique_native),
        'multi_height_native_columns': int(np.count_nonzero(layers > 1)),
        'samples_file': destination.name, 'samples_sha256': file_hash(destination),
        'license': prior.get('license', 'OGL-UK-3.0'),
        'attribution': prior.get('attribution', 'Contains Environment Agency information'),
        'scope': 'Every eligible local return indexed in sparse 0.25 m 3-D cells, including ground and vegetation. Original class-1/6 XYZ additionally retained. Class 1 is unclassified evidence, not automatically a building or ride. Vegetation is not structural height truth. Finer bins do not add observations.',
        'wall_seconds': time.monotonic()-started,
    }
    atomic_json(output / 'lidar-detail-receipt.json', receipt)
    return receipt


def load_samples(receipt_path, bounds, native_receipt):
    path = Path(receipt_path)
    receipt = json.loads(path.read_text())
    if (receipt.get('version') != VERSION or receipt.get('bounds_bng') != list(bounds)
            or receipt.get('crs') != 'EPSG:27700' or receipt.get('vertical_datum') != 'ODN'
            or any(receipt.get(k) != native_receipt.get(k)
                   for k in ('archive_sha256', 'survey_id', 'survey_date'))):
        raise ValueError('Detailed samples must match the original survey and world frame')
    samples = (path.parent / receipt['samples_file']).resolve()
    if file_hash(samples) != receipt['samples_sha256']:
        raise ValueError('Detailed LiDAR sample checksum differs')
    with np.load(samples, allow_pickle=False) as archive:
        xyz, labels = archive['xyz'], archive['classification']
    if (xyz.shape != (receipt['retained_native_xyz_points'], 3)
            or labels.shape != (len(xyz),) or not np.isfinite(xyz).all()
            or not np.isin(labels, [1, 6]).all()):
        raise ValueError('Invalid retained structural samples')
    return xyz, labels, receipt


def decode_quarter(keys):
    keys = np.asarray(keys, np.uint64)
    return ((keys & 16383).astype(np.int32), ((keys >> 14) & 16383).astype(np.int32),
            ((keys >> 28) & 8191).astype(np.int32)-2048, (keys >> 41).astype(np.uint8))


def apply_park_ground_and_foliage(layers, receipt_path, receipt):
    """Use every indexed ground/vegetation return across the park rectangle."""
    if not receipt.get('quarter_index_covers_all_eligible_classes'):
        raise ValueError('Park-wide ground and vegetation index required')
    with np.load(Path(receipt_path).parent/receipt['samples_file']) as samples:
        keys, counts = samples['quarter_keys'], samples['quarter_counts']
    if int(counts.astype(np.uint64).sum()) != receipt['eligible_local_points']:
        raise ValueError('Quarter-metre index lost native returns')
    qx, qr, qz, codes = decode_quarter(keys)
    cc, rr = qx//4, qr//4
    ground = codes == 2
    if not ground.any():
        raise ValueError('Park-wide index has no observed ground')
    cells = rr[ground].astype(np.int64)*layers.width+cc[ground]
    heights = qz[ground]
    weights = counts[ground].astype(np.int64)
    order = np.lexsort((heights, cells))
    cells, heights, weights = cells[order], heights[order], weights[order]
    starts = np.r_[0, np.flatnonzero(np.diff(cells))+1]
    sizes = np.diff(np.r_[starts, len(cells)])
    totals = np.add.reduceat(weights, starts)
    cumulative = np.cumsum(weights)
    within = cumulative-np.repeat(cumulative[starts]-weights[starts], sizes)
    take = within >= np.repeat(totals/2, sizes)
    indices = np.minimum.reduceat(np.where(take, np.arange(len(cells)), len(cells)), starts)
    native_cells = cells[starts]
    r, c = native_cells//layers.width, native_cells % layers.width
    elevation = (heights[indices]+.5)/4
    spread = (np.maximum.reduceat(heights, starts)-np.minimum.reduceat(heights, starts))/4
    supported = ((totals >= 3) & (spread <= 1.5)
                 & (np.abs(elevation-layers.dtm[r,c]) <= 1.5))
    frozen = getattr(layers, 'lidar_frozen_columns', layers.protected)
    supported &= (~layers.footprints[r,c] & ~frozen[r,c]
                  & (layers.water[r,c] == -32768) & (layers.bridge[r,c] == -32768))
    before = layers.ground.copy()
    layers.ground[r[supported],c[supported]] = np.rint(elevation[supported]).astype(np.int16)-1+layers.offset
    layers.lidar_changed_ground = layers.ground != before
    # Regrid all vegetation classes from the fine evidence. At native 1 m block
    # size this intentionally preserves observed occupancy, rather than inventing
    # new leaf positions to make the result look denser.
    vegetation = np.isin(codes, [3,4,5]) & (qz//4 >= -64) & (qz//4 < 500)
    leaf = np.unique((rr[vegetation].astype(np.uint64)*layers.width+cc[vegetation].astype(np.uint64))
                     | ((qz[vegetation]//4+512).astype(np.uint64) << 22))
    ids = (leaf & ((1 << 22)-1)).astype(np.int64)
    chunk = ((ids//layers.width)//16)*(layers.width//16)+(ids % layers.width)//16
    order = np.argsort(chunk, kind='stable')
    leaf, chunk = leaf[order], chunk[order]
    same = np.array_equal(leaf, layers.cloud['leaf_voxels'])
    layers.cloud['leaf_voxels'] = leaf
    layers.cloud['leaf_chunk_offsets'] = np.searchsorted(
        chunk, np.arange((layers.height//16)*(layers.width//16)+1)).astype(np.int64)
    return {'ground_native_columns_with_returns': len(native_cells),
            'supported_ground_columns_applied': int(supported.sum()),
            'changed_native_ground_columns': int(layers.lidar_changed_ground.sum()),
            'ground_return_quantisation_bound_m': .125,
            'terrain_policy': 'Weighted median of every class-2 return through 0.25 m height bins; at least 3 returns; reject >1.5 m mixed heights or DTM disagreement. Preserve water, bridges, buildings and protected references.',
            'vegetation_native_voxels_regridded': len(leaf),
            'vegetation_native_occupancy_matches_prior_full_return_grid': bool(same),
            'foliage_detail_limit': 'All eligible foliage returns already supplied native 1 m occupancy. Finer evidence cannot create additional observed tree detail at this block scale.'}


def observed_roof_layers(xyz, labels, geometry, floor, e0, n1):
    """Supported class-6 layers in each metre column, without median smoothing.

    Keep separated vertical clusters. A higher layer needs two returns or a
    locally supported 3-D neighbourhood; isolated spikes never set a roof.
    """
    left, bottom, right, top = geometry.bounds
    select = ((labels == 6) & (xyz[:, 0] >= left) & (xyz[:, 0] <= right)
              & (xyz[:, 1] >= bottom) & (xyz[:, 1] <= top)
              & (xyz[:, 2] > floor+2.5) & (xyz[:, 2] <= floor+60))
    points = xyz[select]
    if not len(points):
        return {}, [], {'eligible_returns': 0, 'isolated_layer_groups_omitted': 0}
    points = points[contains_xy(geometry, points[:, 0], points[:, 1])]
    if not len(points):
        return {}, [], {'eligible_returns': 0, 'isolated_layer_groups_omitted': 0}
    return supported_layers(points, e0, n1)


def supported_layers(points, e0, n1):
    """Separate locally supported native columns and their observed lower planes."""
    tree = cKDTree(points)
    support = tree.query_ball_point(points, 1.25, return_length=True)
    keys = np.column_stack([np.floor(points[:, 0]-e0), np.floor(n1-points[:, 1]),
                            np.floor(points[:, 2]*2)]).astype(np.int32)
    groups = defaultdict(list)
    for i, key in enumerate(map(tuple, keys)):
        groups[key].append(i)
    tops, accepted = {}, []
    rejected = 0
    for (c, r, half), indices in groups.items():
        indices = np.asarray(indices)
        if len(indices) < 2 and np.max(support[indices]) < 3:
            rejected += 1
            continue
        z = float(np.median(points[indices, 2]))
        cell = int(r), int(c)
        tops[cell] = max(tops.get(cell, -np.inf), z)
        accepted.append((cell, z, indices))
    lower = []
    for cell, z, indices in accepted:
        if tops[cell]-z < 1.5:
            continue
        # Lower roof/awning planes must be observed horizontal/sloped surfaces,
        # not facade points turned into fictional interior floors.
        centre = np.median(points[indices], axis=0)
        local = points[tree.query_ball_point(centre, 1.5)]
        local = local[np.abs(local[:, 2]-z) <= .6]
        if len(local) < 5:
            continue
        centred = local-local.mean(axis=0)
        _, singular, axes = np.linalg.svd(centred, full_matrices=False)
        normal = axes[-1]
        if (singular[1] < .25 or abs(normal[2]) < .65
                or np.percentile(np.abs(centred @ normal), 90) > .2):
            continue
        lower.append((cell, z))
    return tops, lower, {'eligible_returns': len(points),
                         'isolated_layer_groups_omitted': rejected,
                         'supported_height_groups': len(accepted)}


def unmapped_structure_surfaces(layers, xyz, labels, extra):
    """Keep supported class-6 height layers beyond incomplete OSM footprints.

    These are sparse observed surface proxies, not extruded or completed models.
    Two half-block observations sharing a block combine into a full block.
    """
    cc = np.floor(xyz[:,0]-layers.e0).astype(np.int32)
    rr = np.floor(layers.n1-xyz[:,1]).astype(np.int32)
    high = xyz[:,2]-layers.dtm[rr,cc]
    frozen = getattr(layers, 'lidar_frozen_columns', layers.protected)
    context_frozen = getattr(layers, 'lidar_support_frozen_columns', frozen)
    keep = ((labels == 6) & (high >= 1) & (high <= 60)
            & ~layers.footprints[rr,cc] & ~context_frozen[rr,cc]
            & (layers.water[rr,cc] == -32768) & (layers.bridge[rr,cc] == -32768))
    keep &= ((layers.family[rr,cc] == 0) | (xyz[:,2]+layers.offset >= layers.ground[rr,cc]+4))
    points = xyz[keep]
    if not len(points):
        return {'eligible_returns':0, 'observed_surface_blocks':0, 'isolated_half_layers_omitted':0}
    tree = cKDTree(points)
    support = tree.query_ball_point(points, 1.25, return_length=True)
    keys = np.column_stack([np.floor(points[:,0]-layers.e0), np.floor(layers.n1-points[:,1]),
                            np.floor((points[:,2]+layers.offset)*2)]).astype(np.int32)
    groups = defaultdict(list)
    for i, key in enumerate(map(tuple, keys)):
        groups[key].append(i)
    halves = defaultdict(int)
    rejected = 0
    for (c,r,level), indices in groups.items():
        # Semantic suppression changes output, not whether neighbouring source
        # returns support a surface just beyond the suppression boundary.
        if frozen[r,c]:
            continue
        if len(indices) < 2 and np.max(support[indices]) < 3:
            rejected += 1
            continue
        half = int(round((float(np.median(points[indices,2]))+layers.offset)*2))
        y = half//2 if half % 2 else half//2-1
        if not -60 <= y < 316:
            continue
        halves[int(c),y,int(r)] |= 1 if half % 2 else 2
    for (c,y,r), occupied in halves.items():
        rgb = layers.rgb[r,c]
        base = 'dark_oak_slab' if rgb.mean() < 65 else 'brick_slab' if rgb[0] > rgb[1]*1.16 else 'stone_slab'
        if occupied == 3:
            material = {'dark_oak_slab':'dark_oak_planks', 'brick_slab':'bricks', 'stone_slab':'stone_bricks'}[base]
        else:
            material = base+('_top' if occupied == 2 else '')
        z = r-layers.height
        extra[c//16,z//16].append((c % 16,y,z % 16,material))
        layers.protected[r,c] = True
    return {'eligible_returns':len(points), 'observed_surface_blocks':len(halves),
            'isolated_half_layers_omitted':rejected,
            'policy':'Every supported class-6 half-height layer outside mapped buildings; no solid extrusion, footprint completion or gap interpolation. Protected references, water, bridges and path headroom excluded. Materials are RGB appearance proxies.'}


def apply(layers, receipt_path):
    """Apply evidence after v3 reference geometry, keeping its protected corridors."""
    from .alton_aligned_world import _local_mask
    xyz, labels, receipt = load_samples(receipt_path, layers.bounds, layers.cloud_receipt)
    # Preserve entire grade/roof columns around existing blocks and reserved
    # passages without globally removing natural canopy above those columns.
    frozen = layers.protected.copy()
    for name in ('detail', 'clear', 'reference_detail', 'reference_air'):
        for (cx,cz), rows in getattr(layers,name,{}).items():
            for row in rows:
                frozen[cz*16+row[2]+layers.height,cx*16+row[0]] = True
    for x,y,z in getattr(layers,'parent_wicker_detail',{}):
        frozen[z+layers.height,x]=True
    if hasattr(layers,'structural_vegetation_max'):
        layers.lidar_support_frozen_columns = frozen.copy()
        frozen |= layers.structural_vegetation_max > -32768
    layers.lidar_frozen_columns = frozen
    park = apply_park_ground_and_foliage(layers, receipt_path, receipt)
    before = layers.roof_half.copy()
    extra = defaultdict(list)
    reviews, residual_before, residual_after = [], [], []
    added = set()
    for feature in layers.building_features:
        geometry = feature['geometry']
        rs, cs, mask = _local_mask(geometry, layers.bounds, layers.ground.shape)
        if not mask.any():
            continue
        mask &= (~frozen[rs, cs] & (layers.building_floor[rs, cs] > -32768)
                 & (layers.water[rs, cs] == -32768))
        if not mask.any():
            continue
        floor = float(np.percentile(layers.dtm[rs, cs][mask], 70))
        tops, lower, stats = observed_roof_layers(xyz, labels, geometry, floor, layers.e0, layers.n1)
        changed = used = 0
        for (r, c), elevation in tops.items():
            if not (rs.start <= r < rs.stop and cs.start <= c < cs.stop
                    and mask[r-rs.start, c-cs.start]):
                continue
            half = int(round((elevation+layers.offset)*2))
            old = int(layers.roof_half[r, c])
            if not (-116 <= half < 630):
                continue
            residual_before.append(abs(old/2-layers.offset-elevation))
            residual_after.append(abs(half/2-layers.offset-elevation))
            layers.roof_half[r, c] = half
            changed += int(half != old)
            used += 1
        lower_used = 0
        for (r, c), elevation in lower:
            if not (rs.start <= r < rs.stop and cs.start <= c < cs.stop
                    and mask[r-rs.start, c-cs.start]):
                continue
            half = int(round((elevation+layers.offset)*2))
            y = half//2 if half % 2 else half//2-1
            position = int(c), y, int(r-layers.height)
            if position in added:
                continue
            material = str(layers.roof_material[r, c])+('_top' if half % 2 == 0 else '')
            extra[c//16, (r-layers.height)//16].append((c % 16, y, (r-layers.height) % 16, material))
            added.add(position)
            lower_used += 1
        reviews.append({'id': feature['id'], 'name': feature['properties'].get('name'),
                        **stats, 'sampled_roof_columns': used, 'changed_roof_columns': changed,
                        'observed_lower_surface_cells': lower_used})
    unmapped = unmapped_structure_surfaces(layers, xyz, labels, extra)
    layers.lidar_detail = dict(extra)
    layers.lidar_changed_roofs = layers.roof_half != before
    layers.audit['lidar_detail'] = {
        'version': VERSION, 'receipt_sha256': file_hash(receipt_path), 'source': receipt,
        'park_wide_ground_and_vegetation': park,
        'structures_outside_mapped_buildings': unmapped,
        'changed_roof_columns': int(layers.lidar_changed_roofs.sum()),
        'additional_observed_lower_surface_cells': len(added), 'buildings': reviews,
        'accepted_layer_fit_median_p95_before_m': np.percentile(residual_before, [50, 95]).tolist() if residual_before else [],
        'accepted_layer_fit_median_p95_after_m': np.percentile(residual_after, [50, 95]).tolist() if residual_after else [],
        'fit_metric': 'Residual to accepted survey layer medians, not held-out or independent physical accuracy.',
        'geometry_policy': 'All eligible source returns indexed across the complete park frame. Supported class-6 surfaces alter geometry inside and outside mapped building footprints. No global 3x3 median filter on observed roofs. Separate observed height layers retained. Protected Wicker, ride/guideway and reference corridors unchanged; unseen geometry is not completed.',
        'minecraft_horizontal_resolution_m': 1, 'minecraft_roof_vertical_step_m': .5,
        'unclassified_points_automatically_promoted_to_structures': False,
        'new_observations_created': False, 'minecraft_client_tested': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--source-receipt', required=True)
    parser.add_argument('--frame', required=True)
    destinations = parser.add_mutually_exclusive_group(required=True)
    destinations.add_argument('--output', help='Directory for sparse quarter-metre samples')
    destinations.add_argument('--native-crop', help='Full-precision unthinned park LAZ destination')
    args = parser.parse_args()
    frame = json.loads(Path(args.frame).read_text())
    if args.native_crop:
        result = export_native_crop(args.archive,args.source_receipt,frame['bounds_bng'],args.native_crop)
    else:
        result = sample_archive(args.archive, args.source_receipt, frame['bounds_bng'], args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
