"""Extend the native survey crop to cover mapped station context, not fit it."""
import argparse, hashlib, json, math, sys
from pathlib import Path
import laspy, numpy as np
from shapely.geometry import shape
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.point_cloud import crop_archive

CONTEXT = '58639eb20b641669aa9404e80b4dd00232b16b2caac242b18af7c484693013fd'


def extend(archive, old_cloud, receipt_path, context_path, output):
    old = json.loads(Path(receipt_path).read_text())
    if file_hash(archive) != old['archive_sha256'] or file_hash(old_cloud) != old['sha256']:
        raise ValueError('Pinned survey archive and original crop required')
    if file_hash(context_path) != CONTEXT:
        raise ValueError('Pinned mapped context required')
    context = json.loads(Path(context_path).read_text())
    station = shape(context['station_complex_bng_geometry'])
    bounds = old['bounds']; sb = station.bounds
    requested = [min(bounds[0],math.floor((sb[0]-10)/5)*5), min(bounds[1],math.floor((sb[1]-10)/5)*5),
                 max(bounds[2],math.ceil((sb[2]+10)/5)*5), max(bounds[3],math.ceil((sb[3]+10)/5)*5)]
    output = Path(output)
    if output.exists():raise ValueError('Fresh crop output required')
    output.mkdir(parents=True)
    selection = {'filename':old['archive_filename']}
    path, details = crop_archive(Path(archive),selection,requested,output)
    try:
        original = laspy.read(old_cloud); expanded = laspy.read(path)
        x,y = np.asarray(expanded.x),np.asarray(expanded.y)
        subset = expanded[(x>=bounds[0])&(x<=bounds[2])&(y>=bounds[1])&(y<=bounds[3])]
        if original.header.point_count != old['retained_points'] or subset.points.array.tobytes() != original.points.array.tobytes():
            raise ValueError('Original crop point records did not reproduce inside extension')
        report = {**details, 'bounds':requested, 'survey':old['survey'], 'archive_filename':old['archive_filename'],
                  'archive_sha256':old['archive_sha256'], 'url':old['url'],
                  'selection_basis':'Union of original bounds and mapped station extent with 10 m search margin, rounded outward to 5 m; no point fitting',
                  'mapped_station_bounds_bng':list(sb), 'original_crop_bounds':bounds,
                  'original_crop_points_preserved':len(subset),
                  'original_point_records_byte_identical':True,
                  'original_point_records_sha256':hashlib.sha256(subset.points.array.tobytes()).hexdigest(),
                  'new_crop_point_indices_are_separate_namespace':True,
                  'input_sha256':{'old_cloud':old['sha256'],'old_receipt':file_hash(receipt_path),'context':CONTEXT},
                  'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}
        (output/'crop-receipt.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['archive','old-cloud','receipt','context','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=extend(a.archive,a.old_cloud,a.receipt,a.context,a.output)
    print(json.dumps({k:r[k] for k in ['bounds','retained_points','original_crop_points_preserved','original_point_records_byte_identical']}))

if __name__=='__main__':main()
