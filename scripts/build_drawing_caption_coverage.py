"""Inventory original numbered captions independently of artwork crops."""
import argparse
import json
from pathlib import Path
from voxel_mapper.drawing_caption_inventory import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('references', 'source-catalogue', 'source-directory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--max-checks', type=int, default=100000)
    result = build(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ('status', 'counts', 'checks', 'directory')}))
