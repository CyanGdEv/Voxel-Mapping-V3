"""Retain a small public imagery context view with service-derived tile georeferencing."""
import argparse,base64,hashlib,json
from pathlib import Path
from urllib.parse import urlencode

BASE='https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'

def retain(directory):
    root=Path(directory);service=json.loads((root/'esri-current.json').read_text());info=service['tileInfo']
    lod=next(x for x in info['lods'] if x['level']==19);res=lod['resolution'];origin=info['origin'];size=info['rows']
    if size!=256 or info['cols']!=256 or info['spatialReference']['latestWkid']!=3857:raise ValueError('Expected Web Mercator tiles required')
    metadata=json.loads((root/'shop-esri-citation-9.json').read_text())
    if len(metadata.get('features',[]))!=1:raise ValueError('Unique shop-location citation required')
    attrs=metadata['features'][0]['attributes'];tiles=[]
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="930" viewBox="0 0 800 930">','<rect width="800" height="930" fill="#f5f7fa"/>','<text x="25" y="35" font-family="sans-serif" font-size="22">Wicker shop area · independent imagery context</text>','<text x="25" y="64" font-family="sans-serif" font-size="15">Shop-location source date: 2023-05-27 · north up · imagery context, not survey controls</text>']
    for row in [170812,170813]:
        for col in [259392,259393]:
            path=root/f'esri-19-{row}-{col}.jpg';data=path.read_bytes()
            if not data.startswith(b'\xff\xd8'):raise ValueError('JPEG source tile required')
            xmin=origin['x']+col*size*res;ymax=origin['y']-row*size*res
            tiles.append({'url':f'{BASE}/tile/19/{row}/{col}','level':19,'row':row,'column':col,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                          'pixel_to_epsg3857':[res,0,0,-res,xmin,ymax],'bounds_epsg3857':[xmin,ymax-size*res,xmin+size*res,ymax],
                          'pixel_reference':'upper-left pixel edge; centre offset is half a pixel'})
            x=25+(col-259392)*375;y=100+(row-170812)*375
            svg.append(f'<image x="{x}" y="{y}" width="375" height="375" href="data:image/jpeg;base64,{base64.b64encode(data).decode()}"/>')
    svg.extend(['<text x="25" y="881" font-family="sans-serif" font-size="15">Source: Esri World Imagery · WV02 / Vivid / Vantor (shop-location citation)</text>',
                '<text x="25" y="907" font-family="sans-serif" font-size="15">0.5 m source resolution · reported positional accuracy 8.47 m · no checkpoints accepted</text>','</svg>'])
    params={'f':'json','geometry':json.dumps({'x':-1.8888,'y':52.98955,'spatialReference':{'wkid':4326}}),'geometryType':'esriGeometryPoint','inSR':4326,'spatialRel':'esriSpatialRelIntersects','outFields':'*','returnGeometry':'false'}
    report={'status':'dated_georeferenced_imagery_context_only','retrieved_date':'2026-10-10','service_url':BASE,'service_metadata_sha256':hashlib.sha256((root/'esri-current.json').read_bytes()).hexdigest(),
            'tiles':tiles,'shop_location_citation_url':BASE+'/9/query?'+urlencode(params),'citation_response_sha256':hashlib.sha256((root/'shop-esri-citation-9.json').read_bytes()).hexdigest(),
            'shop_location_attributes':attrs,'image_acquisition_date':'2023-05-27','source_resolution_metres':attrs['SRC_RES'],'reported_positional_accuracy_metres':attrs['SRC_ACC'],
            'accuracy_meets_1m_registration_gate':attrs['SRC_ACC']<=1,'metadata_scope':'shop query point only; surrounding tile coverage dates not independently checked',
            'limitations':['Basemap acquisition date is separate from release date.','Tile georeferencing does not turn roof pixels into surveyed ground controls.','Shop-location citation is not proven to apply to every pixel of all four tiles.','No entrance/canopy identity or positional control is accepted from this view.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}
    return report,'\n'.join(svg)+'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['directory','output','svg']:p.add_argument('--'+k,required=True)
    a=p.parse_args();report,svg=retain(a.directory);Path(a.output).write_text(json.dumps(report,indent=2)+'\n');Path(a.svg).write_text(svg)
    print('Retained four imagery tiles and shop-location acquisition/accuracy citation')

if __name__=='__main__':main()
