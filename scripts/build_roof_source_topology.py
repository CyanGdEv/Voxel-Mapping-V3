"""Build original roof junctions and conditional relative-position checks."""
import argparse
import json
from pathlib import Path
from voxel_mapper.roof_source_topology import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-gradient', 'source-partial', 'gable', 'profile', 'preview', 'components', 'views', 'corpus', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--max-checks', type=int, default=100000)
    print(json.dumps(build(**vars(parser.parse_args()))))
