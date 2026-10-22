"""Build short-edge source evidence downstream of the pitched roof review."""
import argparse
import json
from pathlib import Path
from voxel_mapper.automatic_partial_gables import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('gable', 'profile', 'preview', 'components', 'views', 'corpus', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--max-checks', type=int, default=100000)
    args = parser.parse_args()
    print(json.dumps(build(args.gable, args.profile, args.preview, args.components, args.views, args.corpus, args.output, max_checks=args.max_checks)))
