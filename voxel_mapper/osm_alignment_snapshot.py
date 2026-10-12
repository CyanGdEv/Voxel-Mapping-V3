"""Bounded official OSM snapshot acquisition and checksum-verified cycle reuse."""
from datetime import datetime,timezone
import math
from pathlib import Path
import json
import requests
from .acquisition import USER_AGENT
from .generation_cycles import atomic_json,file_hash
from .osm_provisional_alignment import osm_collection

VERSION='osm-alignment-snapshot-v1'
URL='https://api.openstreetmap.org/api/0.6/map'


def acquire(directory,bounds,*,offline=False,fetch=None):
    if (not isinstance(bounds,(list,tuple)) or len(bounds)!=4
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds)
            or not -180<=bounds[0]<bounds[2]<=180 or not -90<bounds[1]<bounds[3]<90
            or bounds[2]-bounds[0]>.1 or bounds[3]-bounds[1]>.1):
        raise ValueError('Finite small-area WGS84 OSM bounds required')
    bounds=list(bounds);root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    path=root/'osm.xml';receipt=root/'snapshot.json'
    if receipt.exists():
        record=json.loads(receipt.read_text())
        if record['bounds_wgs84']!=bounds or record['source_url']!=URL:raise ValueError('OSM snapshot source/bounds changed')
        if file_hash(path)!=record['sha256']:raise ValueError('Retained OSM snapshot changed')
        return path,record
    if offline:return None,{'status':'awaiting_osm_snapshot','bounds_wgs84':bounds,'source_url':URL,'world_geometry_additions':0}
    if fetch:data=fetch(URL,bounds)
    else:
        with requests.get(URL,params={'bbox':','.join(map(str,bounds))},headers={'User-Agent':USER_AGENT},
                stream=True,allow_redirects=False,timeout=(10,30)) as response:
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('OSM redirect/non-200 requires source review')
            result=bytearray()
            for chunk in response.iter_content(65536):
                result.extend(chunk)
                if len(result)>32000000:raise ValueError('OSM snapshot byte budget exceeded')
            data=bytes(result)
    if not isinstance(data,bytes) or len(data)>32000000:raise ValueError('Bounded OSM snapshot bytes required')
    temporary=root/'osm.xml.partial';temporary.write_bytes(data)
    try:osm_collection(temporary)
    except Exception:
        temporary.unlink(missing_ok=True);raise
    temporary.replace(path)
    record={'version':VERSION,'status':'observed_osm_snapshot','source_url':URL,'bounds_wgs84':bounds,
        'sha256':file_hash(path),'bytes':len(data),'retrieved_at':datetime.now(timezone.utc).isoformat(),
        'registration_verified':False,'world_geometry_additions':0}
    atomic_json(receipt,record);return path,record


def local_frame(bounds):
    return f'+proj=aeqd +lat_0={(bounds[1]+bounds[3])/2} +lon_0={(bounds[0]+bounds[2])/2} +datum=WGS84 +units=m +no_defs'
