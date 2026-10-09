"""Reproducible synthetic feature-count stress test; not actual park reconstruction."""
import argparse,json,resource,time
from pathlib import Path
from shapely.geometry import box,mapping
from voxel_mapper.reconstruction.batch import GeometryStore,DEFAULT_MAX_FEATURES
from voxel_mapper.reconstruction.engine import Context
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.sources import evidence

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--features',type=int,default=150000);a=p.parse_args()
if not 1<=a.features<=DEFAULT_MAX_FEATURES:raise ValueError(f'Benchmark count must be 1–{DEFAULT_MAX_FEATURES}')
root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
source=Source('synthetic','synthetic-benchmark','https://github.com/CyanGdEv/Voxel-Mapping-V3','synthetic-fixture','EPSG:27700','ODN')
context=Context({'synthetic':source},lambda x,z:0,box(0,0,400,(a.features+399)//400),'ODN',max_total_voxels=a.features)
def features():
 for i in range(a.features):
  x,z=i%400,i//400
  yield Feature(f'synthetic/{i}','plaza',mapping(box(x+.1,z+.1,x+.9,z+.9)),'synthetic',{'surface':evidence('asphalt','synthetic')})
store=GeometryStore(root/'geometry.sqlite',{'synthetic_features':a.features,'version':'v1'})
try:
 start=time.perf_counter();report=store.compile(features(),context);report['compile_seconds']=time.perf_counter()-start
 start=time.perf_counter();resume=store.compile(features(),context);report['resume_seconds']=time.perf_counter()-start;report['resume_features']=resume['resumed_features']
 report['peak_process_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
 report['fixture']='Synthetic independent one-cell plazas; tests feature-count scale, not real PDF semantics or park accuracy'
 assert report['features']==a.features and report['unique_voxel_cells']==a.features and report['resume_features']==a.features
 (root/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
finally:store.close()
