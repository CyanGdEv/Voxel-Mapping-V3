"""Observe classified LAS evidence for registered surface cells, without writes."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def audit(args):
    from affine import Affine
    from voxel_mapper.point_cloud import summarize_cell_returns
    request=json.loads(args.requests.read_text());reg=json.loads(args.registration.read_text())
    source=json.loads(args.source.read_text())
    if reg['horizontal_crs']!='EPSG:27700' or request['registration_sha256']!=sha(args.registration):
        raise ValueError('Point source and registered request CRS/identity mismatch')
    if source['vertical_datum']!=reg['vertical_ground_surface']['datum'] or source['classified_cloud']['units']!='m':
        raise ValueError('Native vertical datum/metre evidence required')
    grid=Affine(*reg['world_grid_edge_to_bng_affine'])
    for c in request['cells']:
        e,n=grid*(c['x']+.5,c['z']+.5)
        if abs(e-c['easting'])>1e-7 or abs(n-c['northing'])>1e-7:raise ValueError('Native cell centres shifted')
    result=summarize_cell_returns(args.cloud,request['cells'],list(grid)[:6],expected_sha256=source['classified_cloud']['sha256'])
    result.update(requests_sha256=sha(args.requests),registration_sha256=sha(args.registration),
        source_metadata_sha256=sha(args.source),survey=source['survey'],license=source['license'],
        lineage_family=source['lineage_family'],vertical_datum=source['vertical_datum'],accepted_for_block_edits=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['cloud','requests','registration','source','output']:p.add_argument('--'+name,type=Path,required=True)
    r=audit(p.parse_args());print(json.dumps({'scanned':r['scanned_points'],'retained':r['raw_retained_points'],
        'observed_clear_cells':sum(c['observed_clear_ground'] for c in r['cells'])}))
