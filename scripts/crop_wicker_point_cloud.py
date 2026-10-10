"""Replay the dated native-BNG point-cloud crop from a pinned EA archive."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.point_cloud import crop_archive,select_cloud


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','catalogue','receipt','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();receipt=json.loads(Path(a.receipt).read_text())
    if file_hash(a.archive)!=receipt['archive_sha256'] or file_hash(a.catalogue)!=receipt['catalogue_sha256']:
        raise ValueError('Pinned archive and catalogue required')
    selection=select_cloud(json.loads(Path(a.catalogue).read_text()),{
        'url':receipt['url'].replace('national_lidar_programme_point_cloud','national_lidar_programme_dtm'),
        'survey':receipt['survey']})
    if selection['filename']!=receipt['archive_filename']:raise ValueError('Dated filename mismatch')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    path,details=crop_archive(Path(a.archive),selection,receipt['bounds'],out)
    if details['sha256']!=receipt['sha256'] or details['retained_points']!=receipt['retained_points']:
        path.unlink(missing_ok=True);raise ValueError('Crop did not reproduce pinned evidence')
    print(json.dumps(details))


if __name__=='__main__':main()
