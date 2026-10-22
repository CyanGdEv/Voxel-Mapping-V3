"""Build source-linked additional roof elevations from pinned original PDFs."""
import argparse
import json
from pathlib import Path
from voxel_mapper.roof_reference_evidence import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('topology', 'components', 'views', 'corpus', 'source-catalogue', 'additional-pdfs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--max-checks', type=int, default=100000)
    print(json.dumps(build(**vars(parser.parse_args()))))
