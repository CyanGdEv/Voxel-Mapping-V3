"""Stream GeoJSON feature lines into source-linked park-frame reconstruction records."""
import argparse
import hashlib
import json
from pathlib import Path
from pyproj import CRS,Transformer
from shapely.geometry import shape,mapping
from shapely.ops import transform
from .model import Source
from .sources import geojson_adapter


def normalize(input_path,output_path,source,target_crs):
    input_path,output_path=Path(input_path),Path(output_path)
    if output_path.exists():raise ValueError('Use a fresh normalized output path')
    target=CRS.from_user_input(target_crs)
    if not target.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in target.axis_info[:2]):raise ValueError('Projected metre target required')
    with input_path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    projector=Transformer.from_crs(source.crs,target,always_xy=True)
    temporary=output_path.with_suffix(output_path.suffix+'.partial');count=0
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with input_path.open() as input_stream,temporary.open('w') as output_stream:
        for line_number,line in enumerate(input_stream,1):
            if not line.strip():continue
            if len(line)>8_000_000:raise ValueError('GeoJSON feature line exceeds 8 MB')
            item=json.loads(line)
            if item.get('type')!='Feature':raise ValueError('One GeoJSON Feature per line required')
            identity=item.get('id',line_number);item['id']=f'{source.id}/{identity}'
            feature=geojson_adapter({'features':[item]},source)[0]
            feature.geometry=mapping(transform(projector.transform,shape(feature.geometry)))
            props=item.get('properties',{})
            feature.metadata.update(input_sha256=digest,input_line=line_number,geometry_crs=target.to_string())
            if source.kind in ('planning','cad'):feature.metadata['drawing_state']=props.get('drawing_state',props.get('state','unknown'))
            output_stream.write(json.dumps(feature.__dict__,sort_keys=True)+'\n');count+=1
    temporary.replace(output_path)
    return {'features':count,'input_sha256':digest,'source':source.id,'target_crs':target.to_string(),
            'status':'normalized records; geometry semantics and registration still gated during compilation'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--source',required=True)
    p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    manifest=json.loads(Path(a.manifest).read_text());source=Source(**next(s for s in manifest['sources'] if s['id']==a.source))
    print(json.dumps(normalize(a.input,a.output,source,manifest['crs']),indent=2))

if __name__=='__main__':main()
