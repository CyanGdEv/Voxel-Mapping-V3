import json,hashlib,math
from pathlib import Path
import numpy as np,pymupdf
from shapely.geometry import LineString,mapping,shape,box
from voxel_mapper.wicker_patterns import flatten_cubic
root=Path('recovery/gardens-research');docs=json.loads((root/'garden-registered-faces.json').read_text())
# Reviewed native plan traces: the path centre between visible grey boundaries.
# Widths approximate those boundaries at the registered scale, not survey claims.
traces={
 'Upper Gardens Area plan':[
 ('Conservatory north terrace',2.2,False,[(18,257),(143,250),(216,213),(278,187),(349,179),(432,188),(489,205),(670,217),(769,221),(858,206),(935,167)]),
 ('Conservatory south promenade',2.5,False,[(14,310),(146,328),(250,320),(361,315),(423,333),(476,321),(508,308),(550,313),(585,343),(659,340),(732,334),(754,325),(822,337),(922,347),(1010,366)]),
 ('Middle terrace',2,False,[(239,365),(272,382),(343,394),(462,403),(590,419),(711,431),(762,428),(813,420),(894,394)]),
 ('Bandstand terrace',2.2,False,[(465,478),(532,489),(631,489),(703,478),(737,492),(795,527),(840,529),(889,532),(992,583),(1086,619)]),
 ('Bandstand stair connection',2,True,[(750,339),(733,367),(735,407),(746,433),(730,455),(731,479)]),
 ('Western cascade descent',1.8,True,[(192,406),(211,445),(220,487),(245,527),(290,551),(312,560)]),
 ],
 'Lower Gardens area plan':[
 ('Lower terrace lake promenade',2.4,False,[(49,267),(133,288),(247,316),(357,317),(446,300),(541,268),(612,264),(644,285),(729,303),(823,326),(907,357),(982,403),(1023,437)]),
 ('Pagoda lake west and south walk',2.2,False,[(50,294),(87,383),(157,430),(264,478),(404,500),(546,527),(648,566),(720,599),(812,633),(897,656),(990,609),(1025,556)]),
 ('Lower gardens long stair flight',2,True,[(471,564),(503,593),(535,637),(555,674)]),
 ('Lower gardens cross terrace',2,False,[(199,522),(292,567),(366,574),(422,555),(473,557),(520,574),(595,603),(657,609)]),
 ('Pagoda east connection',2,True,[(982,403),(1017,442),(1050,489),(1078,530),(1025,556)]),
 ]}
features=[];sources=[]
for doc in docs:
 digest=doc['document_id'];pdf=Path('recovery/v4/files')/(digest+'.pdf');assert hashlib.sha256(pdf.read_bytes()).hexdigest()==digest
 sources.append({k:doc[k] for k in ('title','document_id','source_url','alignment')})
 for name,width,stairs,coords in traces.get(doc['title'],[]):
  features.append({'id':name,'kind':'path','native_geometry':mapping(LineString(coords)),'width_m':width,'force_stairs':stairs,'document_id':digest,'geometry_status':'reviewed_native_boundary_centre_trace_with_estimated_width','material':'stone','material_status':'unspecified_paving_estimate','colour':None})
 # Retained narrow closed survey faces, reviewed against the drawings. Building,
 # planting, ponds, annotations and large lawn faces deliberately excluded.
 walls={'Upper Gardens Area plan':[80,104,105],'White bridge plan':[0,1],'Lower Gardens area plan':[97]}.get(doc['title'],[])
 for i in walls:
  features.append({'id':doc['title']+f' wall face {i}','kind':'wall','native_geometry':doc['faces'][i]['geometry'],'document_id':digest,'geometry_status':'reviewed_closed_native_survey_face','height_status':'local_bank_relief_estimate_capped_3m','material':'stone_bricks','material_status':'stone_wall_proxy'})
 with pymupdf.open(pdf) as p:
  for index,draw in enumerate(p[0].get_drawings()):
   c=draw.get('color');width=draw.get('width') or 0
   if not c or width<1.9:continue
   if not ((c[0]>.95 and c[1]<.2 and c[2]<.1) or (c[0]<.1 and c[1]>.65 and c[2]>.85)):continue
   # Exclude legend/title blocks, including heavy example strokes.
   bounds=draw['rect'];clip=box(0,0,1191,778)
   if doc['title']=='White bridge plan':clip=clip.difference(box(1015,385,1191,842))
   else:
    clip=clip.difference(box(1025,20,1191,260)).difference(box(1015,635 if doc['title']=='Upper Gardens Area plan' else 650,1191,842))
   parts=[]
   for item in draw['items']:
    if item[0]=='l':coords=[list(item[1]),list(item[2])]
    elif item[0]=='c':
     a,b,c1,d=(np.array(v,float) for v in item[1:]);coords=[a.tolist()]+flatten_cubic(a,b,c1,d,tolerance=.2)
    else:continue
    line=LineString(coords).intersection(clip)
    if line.is_empty:continue
    lines=list(line.geoms) if line.geom_type=='MultiLineString' else [line]
    for line in lines:
     if line.length*doc['alignment']['candidate']['scale_m_per_pdf_point']<.2:continue
     features.append({'id':doc['title']+f' railing {index}-{len(features)}','kind':'barrier','native_geometry':mapping(line),'document_id':digest,'geometry_status':'native_coloured_fence_route_segment','colour':'RAL6008','height_m':1.1,'height_status':'fencing_detail_373_82_10D','material_status':'green_glass_user_authorized_colour_proxy','proposal_status':'mixed_retained_and_proposed_routes_from_2013_application'})
payload={'application':'SMD/2013/1105','registration_verified':False,'registration_note':'Shared survey-label fit inherits provisional Wicker absolute registration. Relative sheet alignment is checked; absolute placement remains provisional.','sources':sources,'specification_sources':[{'title':'Fencing details 373/82/10D','document_id':'deeab25a69238e98b4f72897af951a614189d171842c1a8573bafe318a6fe2b9','source_url':'https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=56611','evidence':['RAL6008 dark green steel','1100 mm railing height; 900 mm stair handrails']}],'features':features,'excluded':'Legend, titleblock, scale bar; ponds, tree circles, planting, buildings; pond-fill and vegetation-removal proposals are not generated.'}
Path('voxel-mapper/voxel_mapper/data/alton-gardens-v16.json').write_text(json.dumps(payload,indent=2))
print(json.dumps({'features':len(features),'types':{k:sum(f['kind']==k for f in features) for k in ('path','wall','barrier')}}))
