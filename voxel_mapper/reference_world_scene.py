"""Apply registered user references to native world geometry, with explicit evidence.

Annotation colours select roles. They do not supply elevations or turn whole
image classes into physical truth. Literal source-assisted boundaries, survey
returns and mapped ride topology supply separate reconstruction layers.
"""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import cv2
import laspy
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from shapely import contains_xy
from shapely.geometry import Polygon, MultiPoint

from .appearance_palettes import choose
from .generation_cycles import file_hash
from .ride_aerial_supervision import project_pixels

VERSION = 'alton-reference-world-edits-v1'


def thin(mask):
    """Zhang–Suen centre strokes, preserving separate painted components."""
    a = np.pad(np.asarray(mask, bool), 1)
    for _ in range(128):
        changed = False
        for second in (False, True):
            p = [a[:-2,1:-1], a[:-2,2:], a[1:-1,2:], a[2:,2:],
                 a[2:,1:-1], a[2:,:-2], a[1:-1,:-2], a[:-2,:-2]]
            n = sum(x.astype(np.uint8) for x in p)
            transitions = sum((~p[i] & p[(i+1)%8]).astype(np.uint8) for i in range(8))
            if second:
                edges = ~(p[0]&p[2]&p[6]) & ~(p[0]&p[4]&p[6])
            else:
                edges = ~(p[0]&p[2]&p[4]) & ~(p[2]&p[4]&p[6])
            remove = a[1:-1,1:-1] & (n>=2) & (n<=6) & (transitions==1) & edges
            if remove.any(): a[1:-1,1:-1][remove] = False; changed = True
        if not changed: break
    return a[1:-1,1:-1]


def _json(path): return json.loads(Path(path).read_text())


class ReferenceScene:
    def __init__(self, layers, manifest_file):
        from .alton_aligned_world import _local_mask
        self.local_mask = _local_mask
        self.l = layers; self.manifest_file = Path(manifest_file)
        self.manifest = _json(manifest_file)
        if self.manifest.get('version') != VERSION: raise ValueError('Pinned reference-world edit manifest required')
        self.profile = _json(self.asset('profile'))
        self.structure_profile = _json(self.asset('structure_profile')) if 'structure_profile' in self.manifest else None
        if self.structure_profile and self.structure_profile.get('version') not in ('wicker-structural-reconstruction-v1','wicker-structural-reconstruction-v2'):
            raise ValueError('Pinned structural reconstruction profile required')
        if self.structure_profile:self.l.wicker_sculpture_revision=self.structure_profile['version']
        if self.profile.get('version') != VERSION: raise ValueError('Explicit source-assisted world profile required')
        self.references = {}; self.records = []
        for key, item in self.manifest['references'].items():
            folder = (self.manifest_file.parent/item['folder']).resolve()
            if file_hash(folder/'review.json') != item['review_sha256']: raise ValueError('Reference review changed')
            review = _json(folder/'review.json'); receipt = _json(folder/'imagery-receipt.json')
            if key in self.profile['sources'] and review['source_pins']['reference'] != self.profile['sources'][key]:
                raise ValueError('World feature uses a different marked source')
            if file_hash(folder/'user-reference.jpg') != review['source_pins']['reference']:
                raise ValueError('Reference image changed')
            if file_hash(folder/'model-input.png') != receipt['image_sha256']:
                raise ValueError('Separate clean imagery changed')
            self.references[key] = (folder, review, receipt)
        self.blocks = {}; self.air = set(); self.roles = defaultdict(set)
        self.old_solid = set(); self.old_air = set()
        for (cx,cz), rows in layers.detail.items():
            self.old_solid.update((cx*16+x,y,cz*16+z) for x,y,z,m in rows)
        for (cx,cz), rows in layers.clear.items():
            self.old_air.update((cx*16+x,y,cz*16+z) for x,y,z in rows)
        # Station placeholders may be opened at mapped portals, but roofs stay
        # intact. Height estimates must fit the passage rather than cut a roof.
        for r,c in zip(*np.nonzero(layers.roof_half>-32768)):
            half=int(layers.roof_half[r,c]);y=half//2 if half%2 else half//2-1
            self.old_solid.add((int(c),y,int(r-layers.height)))
        self.changed_surface = np.zeros(layers.ground.shape, bool)
        self.before_material = layers.material.copy()
        self.before_protected = layers.protected.copy()
        self.nonpaving = np.zeros(layers.ground.shape, bool)
        self.track_samples = _json(self.asset('track_samples'))
        from .alton_aligned_world import WICKER_AFFINE
        a,b,d,e,tx,ty = WICKER_AFFINE
        xy = np.array([s['cells_xy'][len(s['cells_xy'])//2] for s in self.track_samples],float)+.5
        self.track_xy = xy@np.array([[a,d],[b,e]])+[tx,ty]
        self.track_tree = cKDTree(self.track_xy)
        self.track_top = np.array([s['running_top_m'] for s in self.track_samples])
        self.cloud = None

    def asset(self, key):
        p = (self.manifest_file.parent/self.manifest[key]).resolve()
        if file_hash(p) != self.manifest[key+'_sha256']: raise ValueError('Pinned world edit asset changed: '+key)
        return p

    def xy(self, key, pixels):
        _, r, receipt = self.references[key]
        a = np.asarray(pixels,float)
        size = r['legend']['reference_size']
        if a.ndim!=2 or a.shape[1]!=2 or not np.isfinite(a).all() or np.any(a<0) or np.any(a>np.asarray(size)):
            raise ValueError('Bounded literal source vertices required')
        matrix = np.asarray(r['registration']['reference_to_clean'])
        clean = a@matrix[:,:2].T+matrix[:,2]
        return project_pixels(clean,(receipt['width'],receipt['height']),receipt['extent_epsg3857'],self.l.project)

    def geometry(self, feature):
        key = feature['source']
        g = Polygon(self.xy(key,feature['outer']),[self.xy(key,p) for p in feature.get('holes',[])])
        for ring in feature.get('exclusions',[]): g = g.difference(Polygon(self.xy(key,ring)))
        if g.is_empty or not g.is_valid or not 0<g.area<30000: raise ValueError('Valid bounded source polygon required: '+feature['id'])
        return g

    def cells(self, geometry):
        rs,cs,mask = self.local_mask(geometry,self.l.bounds,self.l.ground.shape)
        rr,cc = np.nonzero(mask)
        return rr+rs.start,cc+cs.start

    def add(self,x,y,z,material,role,respect_air=True):
        p=(int(x),int(y),int(z))
        if not (0<=p[0]<self.l.width and -self.l.height<=p[2]<0 and -60<=p[1]<316):return False
        if p in self.old_solid or p in self.old_air or (respect_air and p in self.air):return False
        # An acoustic wall replaces its own provisional interior-air cell.
        # Later independent ride passage reservations can still withhold it.
        if not respect_air:self.air.discard(p)
        self.blocks[p]=material;self.roles[role].add(p);return True

    def clearance(self,x,y,z):
        p=(int(x),int(y),int(z))
        if p not in self.old_solid:self.air.add(p)

    def paint(self,geometry,role):
        l=self.l;rr,cc=self.cells(geometry)
        keep=~l.footprints[rr,cc]&(l.water[rr,cc]==-32768)&~self.nonpaving[rr,cc]
        rr,cc=rr[keep],cc[keep]
        if not len(rr):return 0
        existing=l.family[rr,cc].copy();known=existing[np.isin(existing,[1,2,3])]
        family=int(np.bincount(known,minlength=4)[1:].argmax()+1) if len(known) else 3
        existing[~np.isin(existing,[1,2,3])]=family
        l.family[rr,cc]=existing;l.surface_source[rr,cc]=6
        # Geometry is supplied by the paired user boundaries, including hidden paths.
        # Canopy colour cannot erase that geometry or turn it into darker asphalt.
        for code,name in [(1,'brick'),(2,'asphalt'),(3,'stone')]:
            pick=existing==code
            if not pick.any():continue
            r,c=rr[pick],cc[pick];rgb=l.rgb[r,c].copy();good=l.visible[r,c]
            if good.any():
                _,ix=cKDTree(np.column_stack([r[good],c[good]])).query(np.column_stack([r[~good],c[~good]]))
                rgb[~good]=rgb[good][ix]
            else:rgb[:]=(160,130,105) if code==1 else (105,105,105)
            mats,_=choose(name,rgb,l.ee[r,c].astype(int),l.nn[r,c].astype(int));l.material[r,c]=mats
        self.changed_surface[rr,cc]|=l.material[rr,cc]!=self.before_material[rr,cc]
        self.records.append({'id':role,'role':'source_assisted_paving','accepted_columns':len(rr),
            'changed_material_columns':int(np.count_nonzero(l.material[rr,cc]!=self.before_material[rr,cc])),
            'ground_level_changed':False,'under_canopy_geometry_retained':True})
        return len(rr)

    def load_cloud(self):
        if self.cloud is not None:return self.cloud
        receipt=_json(self.asset('cloud_receipt'));path=self.asset('cloud')
        if file_hash(path)!=receipt['sha256'] or receipt['crs']!='EPSG:27700' or receipt['survey_date']!='2022-01-05':
            raise ValueError('Matched classified survey crop required')
        a=laspy.read(path)
        valid=~np.asarray(a.withheld,bool)&~np.asarray(a.synthetic,bool)
        xyz=np.column_stack([np.asarray(a.x),np.asarray(a.y),np.asarray(a.z)])[valid]
        codes=np.asarray(a.classification)[valid]
        rr=np.floor(self.l.n1-xyz[:,1]).astype(int);cc=np.floor(xyz[:,0]-self.l.e0).astype(int)
        ground=self.l.dtm[rr,cc]
        self.cloud=(xyz,codes,ground)
        return self.cloud

    def queue(self,feature):
        folder,_,_=self.references[feature['source']]
        mask=np.asarray(Image.open(folder/'reference-labels.png'))==feature['label_code']
        yy,xx=np.nonzero(thin(mask));en=self.xy(feature['source'],np.column_stack([xx,yy]))
        geometry=MultiPoint(en).buffer(1.1)
        self.paint(geometry,feature['id']+'-paving')
        # Queue guides describe lanes. Put rails outside their walkable band,
        # rather than filling the marked lane centres with fence blocks.
        rr,cc=self.cells(geometry.buffer(.8).difference(geometry))
        cells=set(zip(cc.tolist(),(rr-self.l.height).tolist()))
        added=0
        for x,z in cells:
            r=z+self.l.height
            if not(0<=x<self.l.width and 0<=r<self.l.height) or self.l.footprints[r,x] or self.l.water[r,x]>-32768:continue
            added+=self.add(x,int(self.l.ground[r,x])+1,z,'dark_oak_fence',feature['id'])
        self.records.append({'id':feature['id'],'role':'paved_queue_lanes_with_outer_railings','fence_cells':int(added),
            'provisional_walkable_band_width_m':2.2,'marked_lane_centres_blocked_by_railings':False,
            'lane_entrances_or_unmarked_connections_invented':False,'lane_widths_verified':False})

    def boundary_trace(self,feature):
        folder,_,_=self.references[feature['source']]
        mask=np.asarray(Image.open(folder/'reference-labels.png'))==feature['label_code']
        yy,xx=np.nonzero(thin(mask));en=self.xy(feature['source'],np.column_stack([xx,yy]))
        cells=set((math.floor(e-self.l.e0),math.floor(self.l.n0-n)) for e,n in en)
        material='oak_fence' if feature['kind']=='fence_trace' else 'stone_slab'
        added=0
        for x,z in cells:
            r=z+self.l.height
            if not(0<=x<self.l.width and 0<=r<self.l.height) or self.l.footprints[r,x] or self.l.water[r,x]>-32768:continue
            added+=self.add(x,int(self.l.ground[r,x])+1,z,material,feature['id'])
        self.records.append({'id':feature['id'],'role':feature['kind'],'native_cells':int(added),
            'vertical_size':'one fence block' if material=='oak_fence' else 'half-block stone boundary proxy',
            'height_measured':False,'image_local_legend_preserved':True})

    def theming(self,feature,g):
        if self.structure_profile:
            from .wicker_structure_semantics import complete_effigy
            return complete_effigy(self,feature,g)
        xyz,codes,ground=self.load_cloud();inside=contains_xy(g,xyz[:,0],xyz[:,1])
        good=inside&(xyz[:,2]>ground+2.5)&np.isin(codes,[1,5,6])
        seed=good&np.isin(codes,[1,6]);qualified=seed.copy()
        if seed.any():
            d,_=cKDTree(xyz[seed]).query(xyz[good]);idx=np.flatnonzero(good)
            qualified[idx[d<=2]]=True
        points=xyz[qualified]
        if len(points)<8:raise ValueError('Insufficient observed theming structure returns')
        rr,cc=self.cells(g);self.l.protected[rr,cc]=True
        voxels=Counter((math.floor(e-self.l.e0),math.floor(z)+self.l.offset,math.floor(self.l.n0-n)) for e,n,z in points)
        for (x,y,z),count in voxels.items():self.add(x,y,z,'oak_log' if count>=3 else 'dark_oak_fence',feature['id'])
        columns=defaultdict(list)
        for x,y,z in voxels:columns[x,z].append(y)
        for (x,z),ys in columns.items():
            ys=sorted(ys)
            for a,b in zip(ys,ys[1:]):
                if b-a==2:self.add(x,a+1,z,'dark_oak_fence',feature['id'])
        self.records.append({'id':feature['id'],'role':'observed_theming_surface_voxels','eligible_returns':len(points),
            'classes':dict(Counter(map(str,codes[qualified].tolist()))),'odn_min_max_m':[float(points[:,2].min()),float(points[:,2].max())],
            'vegetation_reclassification':'Only inside user-marked object and within 2 m of class-1/6 seeds',
            'interpolation':'Single-cell vertical gaps only; no solid footprint extrusion',
            'finished_sculpture_accuracy_verified':False})

    def tunnel(self,feature,g):
        xyz,codes,ground=self.load_cloud();good=contains_xy(g,xyz[:,0],xyz[:,1])&(codes==6)&(xyz[:,2]>ground+3)
        points=xyz[good]
        if len(points)<8:raise ValueError('Insufficient class-6 acoustic-roof context')
        tree=cKDTree(points[:,:2]);rr,cc=self.cells(g);roof_count=0;unresolved=0;skipped=0
        self.l.protected[rr,cc]=True
        for r,c in zip(rr,cc):
            e,n=self.l.e0+c+.5,self.l.n1-r-.5
            d,ix=tree.query([e,n],k=min(5,len(points)))
            if np.min(d)>8:unresolved+=1;continue
            values=points[np.atleast_1d(ix)[np.atleast_1d(d)<=8],2]
            top=int(round((float(np.median(values))+self.l.offset)*2));y=top//2 if top%2 else top//2-1
            material='dark_oak_slab' if top%2 else 'dark_oak_slab_top'
            x,z=int(c),int(r-self.l.height)
            track=self.track_tree.query_ball_point([e,n],2)
            running=[float(self.track_top[i]+self.l.offset) for i in track]
            def passage(level):return any(h-1<=level<=h+3 for h in running)
            for level in range(int(self.l.ground[r,c])+1,y):
                self.clearance(x,level,z)
            edge=g.boundary.distance(MultiPoint([(e,n)]))<1.1
            if edge:
                for level in range(int(self.l.ground[r,c])+1,y):
                    if not passage(level):self.add(x,level,z,'dark_oak_planks',feature['id'],respect_air=False)
            if not passage(y):roof_count+=self.add(x,y,z,material,feature['id'],respect_air=False)
            else:skipped+=1
        self.records.append({'id':feature['id'],'role':'hollow_survey_roof_shell','class6_roof_returns':len(points),
            'roof_columns':int(roof_count),'unsupported_roof_columns_unbuilt':unresolved,'roof_cells_withheld_for_running_passage':skipped,
            'roof_estimation':'Local median of up to 5 class-6 returns within 8 m; half-block roof; no treetop height labels',
            'passage_heights':'Existing separate track visits retained; wall portals and existing running clearances preserved',
            'exact_section_verified':False})

    def apply(self):
        if self.structure_profile:
            from .wicker_structure_semantics import support_volumes
            support_volumes(self)
        features=self.profile['features']
        for f in features:
            if f.get('exclusions'):
                for ring in f['exclusions']:
                    r,c=self.cells(Polygon(self.xy(f['source'],ring)));self.nonpaving[r,c]=True
        for f in features:
            kind=f['kind']
            if kind=='paving':
                g=self.geometry(f);self.paint(g,f['id'])
                if f.get('hole_material')=='grass_block':
                    for ring in f.get('holes',[]):
                        rr,cc=self.cells(Polygon(self.xy(f['source'],ring)))
                        keep=~self.l.footprints[rr,cc]&(self.l.water[rr,cc]==-32768)&(self.l.bridge[rr,cc]==-32768)
                        rr,cc=rr[keep],cc[keep];self.l.material[rr,cc]='grass_block';self.l.family[rr,cc]=0
            elif kind=='queue_trace':self.queue(f)
            elif kind in ('fence_trace','rock_boundary_trace'):self.boundary_trace(f)
            elif kind=='theming_cloud':self.theming(f,self.geometry(f))
            elif kind=='sound_tunnel':self.tunnel(f,self.geometry(f))
            elif kind=='track_check':
                _,r,_=self.references[f['source']];p=np.array([v['bng_en'] for v in r['review_points'] if v['label']=='roller_coaster_track'])
                d,_=self.track_tree.query(p)
                self.records.append({'id':f['id'],'role':'independent_layer_alignment_comparison',
                    'guide_points':len(p),'distance_median_p95_m':np.percentile(d,[50,95]).tolist(),
                    'metric':'Guide/map agreement, not surveyed accuracy; retained planned track not flattened to 2D ink'})
            else:raise ValueError('Unsupported reference world feature')
        if self.manifest.get('rides'):
            from .supported_ride_layouts import build_rides
            build_rides(self,self.manifest['rides'])
        if self.structure_profile:
            from .wicker_structure_semantics import report_vegetation
            report_vegetation(self)
        grouped=defaultdict(list);air=defaultdict(list)
        for (x,y,z),m in self.blocks.items():grouped[x//16,z//16].append((x%16,y,z%16,m))
        for x,y,z in self.air:air[x//16,z//16].append((x%16,y,z%16))
        self.l.reference_detail=dict(grouped);self.l.reference_air=dict(air)
        self.l.reference_roles={role:sorted(cells) for role,cells in self.roles.items()}
        self.l.reference_surface_changed=self.l.material!=self.before_material
        self.l.reference_protected_added=self.l.protected&~self.before_protected
        self.l.audit['reference_world_edits']={'version':VERSION,'manifest_sha256':file_hash(self.manifest_file),
            'profile_sha256':self.manifest['profile_sha256'],'features':self.records,
            'input_pins':{k:v for k,v in self.manifest.items() if k.endswith('_sha256')},
            'sources':{k:{'reference_sha256':v[1]['source_pins']['reference'],'review_sha256':self.manifest['references'][k]['review_sha256']} for k,v in self.references.items()},
            'changed_ground_material_columns':int(self.l.reference_surface_changed.sum()),
            'new_structure_cells':len(self.blocks),'structure_cells_by_role':{k:len(v) for k,v in self.roles.items()},
            'reserved_air_cells':len(self.air),'model_weights_retrained':False,
            'physical_geometry_independently_verified':False}


def apply(layers,manifest_file):
    scene=ReferenceScene(layers,manifest_file);scene.apply();return scene
