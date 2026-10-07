"""Live public-provider probe; this does not certify world accuracy."""
import json
from pathlib import Path

from voxel_mapper.overture import acquire_buildings

collection, result = acquire_buildings([-.52,51.39,-.50,51.41],Path('source-check'))
print(json.dumps(result,indent=2))
if result['status'] != 'downloaded' or not collection['features']:
    raise SystemExit('Live Overture provider check failed; evidence report retained')
