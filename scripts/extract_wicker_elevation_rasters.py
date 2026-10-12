"""Export pinned shop elevation rasters with native pixel-to-page provenance."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from voxel_mapper.drawing_page_tools import native_inverse

SOURCE = 'd1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    data = Path(args.pdf).read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE:
        raise ValueError('Pinned elevation PDF checksum mismatch')
    out = Path(args.output)
    if out.exists():
        raise ValueError('Fresh output directory required')
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        page = doc[0]
        inverse = native_inverse(page)
        records = []
        assets = {}
        for ordinal, info in enumerate(page.get_image_info(xrefs=True)):
            xref = info['xref']
            if not xref:
                raise ValueError('Unresolved inline image')
            asset = doc.extract_image(xref)
            digest = hashlib.sha256(asset['image']).hexdigest()
            filename = digest + '.' + asset['ext']
            assets[filename] = asset['image']
            matrix = pymupdf.Matrix(1/info['width'], 1/info['height']) * pymupdf.Matrix(info['transform']) * inverse
            corners = [[*(pymupdf.Point(x,y) * matrix)] for x,y in [(0,0),(info['width'],0),(info['width'],info['height']),(0,info['height'])]]
            records.append({'placement':ordinal,'xref':xref,'asset':filename,'asset_sha256':digest,
                            'size_pixels':[info['width'],info['height']], 'pixel_to_native_matrix':list(matrix),
                            'native_corners_points':corners,
                            'pixel_step_points':[(matrix.a**2+matrix.b**2)**.5,(matrix.c**2+matrix.d**2)**.5],
                            'soft_mask_xref':doc.xref_get_key(xref,'SMask')[1],
                            'physical_boundary_verified':False})
        clips = [{'ordinal':i,'scissor_points':list(r['scissor']), 'item_count':len(r.get('items',[]))}
                 for i,r in enumerate(page.get_cdrawings(extended=True)) if r['type']=='clip']
        report = {'source_sha256':SOURCE,'native_page_rotation':page.rotation,
                  'coordinate_frame':'PDF native points, y up; pixel coordinates use image top-left',
                  'placements':records,'unique_asset_count':len(assets),'clip_scopes':clips,
                  'status':'raster_sources_only','world_geometry_additions':0,
                  'limitations':['Image placements are not roof or wall boundaries.',
                                  'Sampling steps exclude drawing accuracy and edge interpretation error.',
                                  'Image masks and page clipping require rendering before boundary interpretation.']}
        out.mkdir(parents=True)
        for filename, payload in sorted(assets.items()):
            (out/filename).write_bytes(payload)
        (out/'raster-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'placements':len(records),'unique_assets':len(assets),'manifest':str(out/'raster-manifest.json')}))

if __name__ == '__main__':
    main()
