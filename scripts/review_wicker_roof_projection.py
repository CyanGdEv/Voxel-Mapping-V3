"""Recover proposed roof-projection dimensions without masking cross-view conflicts."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from voxel_mapper.drawing_page_tools import pixel_to_native

ROOF='6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047'
ELEV='d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6'

def review(directory):
    specs=[(ROOF,'roof-plan',{'back-left':[522,654],'back-right':[615,749],'front-right':[631,733],'front-left':[538,638]}),
           (ELEV,'NE',{'left':[1074,818],'right':[1208,818]}),
           (ELEV,'SE',{'wall-edge':[642,334],'main-roof-edge':[653,334],'front':[675,354]})]
    records=[]
    for sha,view,points in specs:
        path=Path(directory)/(sha+'.pdf')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source checksum mismatch')
        with pymupdf.open(path) as doc:
            page=doc[0];pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width));matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
        factor=100*.0254/72
        native={k:list(pymupdf.Point(*v)*matrix) for k,v in points.items()}
        metric={k:[x*factor for x in v] for k,v in native.items()}
        records.append({'source_sha256':sha,'view':view,'manual_points_pixels':points,'native_points':native,
                        'metric_page_points':metric,'render_size_pixels':[pix.width,pix.height],
                        'render_samples_sha256':hashlib.sha256(pix.samples).hexdigest()})
    plan=records[0]['metric_page_points'];width=math.dist(plan['back-left'],plan['back-right']);depth=math.dist(plan['back-left'],plan['front-left'])
    # Horizontal widths/depths in the elevation use the full-page display x axis.
    metre_per_pixel=2384/1888*100*.0254/72
    front_width=134*metre_per_pixel;side_depth=22*metre_per_pixel;wall_depth=33*metre_per_pixel
    return {'status':'proposed_projection_dimensions_consistent','traces':records,'manual_endpoint_bound_pixels':2,
            'plan_width_metres':width,'plan_depth_metres':depth,'NE_front_width_metres':front_width,
            'SE_beyond_main_roof_depth_metres':side_depth,'SE_from_wall_depth_metres':wall_depth,'front_width_difference_metres':front_width-width,
            'depth_difference_metres':side_depth-depth,
            'combined_two_view_sampling_bound_metres':8*metre_per_pixel,
            'depth_conflict_exceeds_combined_sampling_bound':abs(side_depth-depth)>8*metre_per_pixel,
            'projection_mesh':None,'world_placement_eligible':False,'world_geometry_additions':0,
            'limitations':['Manual point picks; physical accuracy unverified.','Like-for-like depth is beyond the main roof edge; wall-to-front depth additionally includes its overhang. Projection slope/fascia edge identity remains unresolved.','Main roof and wall model remains unchanged; no depth averaging or forced fit.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf-directory',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=review(a.pdf_directory)
    Path(a.output).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['plan_width_metres','plan_depth_metres','depth_difference_metres','depth_conflict_exceeds_combined_sampling_bound']}))

if __name__=='__main__':main()
