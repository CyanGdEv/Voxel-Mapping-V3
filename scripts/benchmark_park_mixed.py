"""Mixed synthetic multi-cell park geometry benchmark; no real-drawing accuracy claim."""
import argparse,json,resource,time
from pathlib import Path
from shapely.geometry import box,mapping
from voxel_mapper.reconstruction.batch import GeometryStore
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.sources import evidence


def run(output,count=10000):
    if not 1<=count<=100000:raise ValueError('Mixed fixture budget is 1–100000 features')
    source=Source('fixture','synthetic-benchmark','https://github.com/CyanGdEv/Voxel-Mapping-V3','synthetic-fixture','EPSG:27700','ODN','accepted')
    def e(value):return evidence(value,'fixture')
    families=['path','plaza','wood_fence','metal_fence','building_shell','rocks','lake','ride_layout','ride_support_member','bridge']
    def features():
        for i in range(count):
            x,z=(i%100)*32,(i//100)*32;family=families[i%len(families)];geom=mapping(box(x+2,z+2,x+6,z+6));params={}
            if family=='path':geom={'type':'LineString','coordinates':[[x+2,z+2],[x+12,z+6]]};params={'width_m':e(3),'surface':e('asphalt')}
            elif family=='plaza':params={'surface':e('gravel')}
            elif family in ('wood_fence','metal_fence'):geom={'type':'LineString','coordinates':[[x+2,z+2],[x+12,z+2]]};params={'height_m':e(2),'material':e('oak_fence' if family=='wood_fence' else 'iron_bars')}
            elif family=='building_shell':params={'height_m':e(6),'material':e('stone_bricks')}
            elif family=='rocks':params={'height_m':e(3),'rock_type':e('jagged')}
            elif family=='lake':params={'surface_elevation_m':e(3),'bed_elevation_m':e(0),'bed_material':e('gravel')}
            elif family=='ride_layout':geom={'type':'LineString','coordinates':[[x+2,z+2,4],[x+7,z+7,9],[x+12,z+2,5]]};params={'material':e('iron_block')}
            elif family=='ride_support_member':geom={'type':'LineString','coordinates':[[x+4,z+4,1],[x+4,z+4,12]]};params={'material':e('iron_block')}
            else:
                geom={'type':'Point','coordinates':[x+5,z+5]}
                params={'base_elevation_m':e(2),'rotation_degrees':e(0),'components':e([{'id':'deck','geometry_source':'fixture','geometry':mapping(box(-3,-1,3,1)),'parameters':{'bottom_m':e(0),'top_m':e(1),'material':e('oak_planks')}}])}
            yield Feature(f'mixed/{i}',family,geom,'fixture',params)
    ctx=Context({'fixture':source},lambda x,z:0,box(0,0,3200,((count+99)//100)*32),'ODN',max_total_voxels=count*200)
    root=Path(output);root.mkdir(parents=True,exist_ok=True);store=GeometryStore(root/'geometry.sqlite',{'mixed_fixture_features':count,'version':'v1'})
    try:
        start=time.perf_counter();report=store.compile(features(),ctx);report['compile_seconds']=time.perf_counter()-start
        start=time.perf_counter();resume=store.compile(features(),ctx);report['resume_seconds']=time.perf_counter()-start
        report.update(resume_features=resume['resumed_features'],peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,fixture='Synthetic mixed multi-cell geometry: paths, plazas, fences, shells, rocks, water, 3D ride routes/supports and bridge components')
        assert report['features']==count and report['decisions']=={'planned':count} and report['resume_features']==count
        (root/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:store.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--features',type=int,default=10000);args=p.parse_args();print(json.dumps(run(args.output,args.features),indent=2))
