"""Bounded existing canopy outline; estimated height/material, provisional pose."""
import hashlib,math
import numpy as np
from shapely.geometry import Polygon,Point
from .generation_cycles import file_hash
from .mutiny_bay_review import ROOF
from .forbidden_valley import reviewed_outline
from .wicker_registration import similarity_candidates,apply_candidate

CORNERS=[(721.4383544921875,886.7982177734375),(860.759033203125,887.0386962890625),
 (860.0390625,931.1994018554688),(907.5589599609375,932.3988037109375),
 (904.55908203125,1072.07861328125),(857.3983154296875,1070.9979248046875),
 (859.55810546875,1118.27880859375),(719.8782958984375,1115.2789306640625),
 (720.718505859375,1067.759033203125),(674.038818359375,1069.437744140625),
 (676.6795654296875,930.1187133789062),(720.718505859375,930.8386840820312)]
SCALE=200*.0254/72


def source_canopy(pdf):
 import pymupdf
 if file_hash(pdf)!=ROOF:raise ValueError('Pinned existing canopy roof PDF required')
 with pymupdf.open(pdf) as d:
  p=d[0]
  if 'Existing Roof Plan' not in p.get_text() or '1 : 200' not in p.get_text():raise ValueError('Existing roof identity/scale changed')
  g=reviewed_outline(p,CORNERS,tolerance=.01)
 if not 215<g.area*SCALE*SCALE<230:raise ValueError('Canopy outline changed')
 return g,{'document_sha256':ROOF,'page':1,'drawing':'3023-10 Existing Roof Plan','frame':'displayed_pdf_points_rotation_applied',
   'corners':list(g.exterior.coords),'area_m2':g.area*SCALE*SCALE,'scale_m_per_pdf_point':SCALE,
   'identity':'Visually reviewed central cruciform canopy; snapped native straight-line endpoints',
   'source_state':'2017 existing drawing; current as-built state unverified'}


def provisional_pose(source_court,mapped_court):
 candidates=similarity_candidates(list(source_court.minimum_rotated_rectangle.exterior.coords)[:4],list(mapped_court.minimum_rotated_rectangle.exterior.coords)[:4])
 # Correct orientation from the site north arrow; do not choose a rotated/reflected best envelope by residual alone.
 candidates=[c for c in candidates if .7<c['rotation'][0][0]<1 and -.7<c['rotation'][0][1]<-.3]
 if len(candidates)!=1:raise ValueError('Ambiguous courtyard north direction')
 c=candidates[0];rotation=np.asarray(c['rotation']);a=np.asarray(source_court.centroid.coords[0])*[1,-1]
 c={k:v for k,v in c.items() if k!='shop_corner_rms_m'}
 c.update(scale_m_per_pdf_point=SCALE,translation_epsg27700_m=(np.asarray(mapped_court.centroid.coords[0])-SCALE*a@rotation).tolist())
 transformed=Polygon(apply_candidate(source_court.exterior.coords,c))
 audit={'status':'provisional_fixed_printed_scale','mapped_identity':'courtyard relation 5496185 inner member 106842140',
  'inner_area_ratio':transformed.area/mapped_court.area,'inner_boundary_hausdorff_m':transformed.hausdorff_distance(mapped_court),
  'candidate':c,'registration_verified':False,'independent_survey_controls':0,
  'limits':'Correct ring and north orientation, fixed printed scale; differing roof/wall extents and independent registration unresolved'}
 return c,audit


def canopy_rows(polygon,ground,*,eaves=182,ridge=184):
 """Height/material proxies only. Six supported posts keep the central aisle open."""
 if not eaves<ridge or ridge-eaves>4:raise ValueError('Bounded canopy height required')
 rows={};foot={};xmin,zmin,xmax,zmax=polygon.bounds
 for x in range(math.floor(xmin),math.ceil(xmax)):
  for z in range(math.floor(zmin),math.ceil(zmax)):
   p=Point(x+.5,z+.5)
   if polygon.covers(p):
    y=ground(x,z)
    if y is None or not 2<=eaves-y<=6:continue
    foot[x,z]=y;roof=eaves+min(ridge-eaves,math.floor(polygon.boundary.distance(p)*.35))
    rows[x,roof,z]={'x':x,'y':roof,'z':z,'material':'spruce_slab','kind':'structure','feature':'mutiny/canopy-roof'}
 heights={(x,z):y for x,y,z in rows}
 for (x,z),y in heights.items():
  if any(heights.get((x+dx,z+dz),y)<y for dx,dz in ((1,0),(-1,0),(0,1),(0,-1))):
   rows[x,y-1,z]={'x':x,'y':y-1,'z':z,'material':'spruce_planks','kind':'structure','feature':'mutiny/canopy-roof-seam'}
 # Support two outer rows with three columns; nearest roof cell is used, not an unsupported outside sample.
 if foot:
  chosen=set()
  for fx in (.16,.84):
   for fz in (.16,.5,.84):
    target=Point(xmin+(xmax-xmin)*fx,zmin+(zmax-zmin)*fz)
    cell=min(foot,key=lambda c:target.distance(Point(c[0]+.5,c[1]+.5)));chosen.add(cell)
  for x,z in chosen:
   roof=next(y for xx,y,zz in rows if xx==x and zz==z)
   for y in range(foot[x,z]+1,roof):rows[x,y,z]={'x':x,'y':y,'z':z,'material':'spruce_fence','kind':'structure','feature':'mutiny/canopy-support'}
   # Closed decorative cap underneath the roof; a visual proxy, not a measured bracket.
   y=roof-1
   for dx,dz,direction in ((1,0,'west'),(-1,0,'east')):
    if (x+dx,z+dz) in foot and (x+dx,y,z+dz) not in rows:
     rows[x+dx,y,z+dz]={'x':x+dx,'y':y,'z':z+dz,'material':'spruce_trapdoor_'+direction,'kind':'structure','feature':'mutiny/canopy-bracket'}
 return rows,{'roof_columns':len(foot),'eaves_estimate_m':eaves,'ridge_estimate_m':ridge,
  'height_basis':'Bounded visual estimate inside retained native canopy height envelope; no source height claim',
  'materials':'Spruce slab, fence and trapdoor proxies; canopy finish is not source-specified'}
