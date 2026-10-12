"""Legend-bound landscape and acoustic preview details; registration is provisional."""
import gzip
import json
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from .wicker_patterns import flatten_cubic, extract_pattern_surfaces
from .wicker_surfaces import painted_polygon, visible_fills
from .wicker_registration import apply_candidate
from .wicker_track import REVIEW_DOCUMENT


def straightened(path):
    items = []
    for item in path.get('items',[]):
        if item[0] in ('l','re'):
            items.append(item)
        elif item[0] == 'c':
            current = item[1]
            for end in flatten_cubic(*(np.asarray(p,dtype=float) for p in item[1:])):
                items.append(['l',current,end]);current=end
        elif item[0] == 'qu':
            a,b,c,d = item[1]
            ring = [a,b,d,c,a]
            items.extend(['l',a,b] for a,b in zip(ring,ring[1:]))
        else:
            return {**path,'items':[['unsupported']]}
    return {**path,'items':items}


def legend_fills(vectors, annotations, label_text, scale, circular=False):
    """Match an adjacent legend swatch's paint and shape, with clipped paths."""
    label = next(a for a in annotations if a['text'] == label_text)
    x0,y0,x1,y1 = label['bbox']
    swatches = [p for p in vectors if p.get('fill') and p.get('rect') and
                0 <= x0-p['rect'][2] <= 100 and max(p['rect'][1],y0)<min(p['rect'][3],y1)
                and 20 <= p['rect'][2]-p['rect'][0] <= 120 and 10 <= p['rect'][3]-p['rect'][1] <= 60]
    if len(swatches) != 1:
        raise ValueError('Unique landscape legend swatch required: '+label_text)
    swatch = swatches[0]
    # Opacity belongs to the drawing symbol, not to a transparent world block.
    converted = [straightened(p) for p in vectors]
    for p in converted:
        if p.get('fill') == swatch['fill']:
            p['fill_opacity'] = 1
    fills,_ = visible_fills(converted)
    found = []
    for f in fills:
        polygon = f['polygon'];source = vectors[f['vector_index']]
        if (source.get('fill') != swatch['fill']
                or polygon.bounds[2] >= swatch['rect'][0] or not 2 <= polygon.area*scale**2 <= 10000):
            continue
        if circular and (polygon.geom_type != 'Polygon' or 4*math.pi*polygon.area/polygon.length**2 < .95):
            continue
        found.append({'polygon':polygon,'vector_index':f['vector_index'],'legend_text':label_text})
    return found


def inspect_details(output):
    output = Path(output)
    evidence = json.loads((output/'wicker-man-planning-evidence.json').read_text())
    alignment = json.loads((output/'wicker-man-registration.json').read_text())
    document = next(d for d in evidence['documents'] if d.get('sha256') == REVIEW_DOCUMENT)
    page = document['pages'][0]
    with gzip.open(output/page['vector_file'],'rt') as stream:
        vectors = json.load(stream)
    if len(vectors)>150000:
        raise ValueError('Detail vector budget exceeded')
    scale = alignment['printed_scale_m_per_pdf_point']
    inverse = Transformer.from_crs(27700,4326,always_xy=True)
    def project(x,y,z=None):
        xy = apply_candidate(list(zip(x,y)),alignment['candidate'])
        return inverse.transform(xy[:,0],xy[:,1])
    features = []
    failures = []
    def append(candidate,kind,**properties):
        polygon = candidate['polygon']
        features.append({'type':'Feature','geometry':mapping(transform(project,polygon)),
                         'properties':{'kind':kind,'document_id':REVIEW_DOCUMENT,
                                       'registration_verified':False,'as_built_verified':False,
                                       **{k:v for k,v in candidate.items() if k!='polygon'},**properties}})
    for kind,label,circular in [
        ('new_tree','New indigenous and park canopy trees ',True),
        ('understorey','New mainly indigenous understorey ',False)]:
        try:
            matches = legend_fills(vectors,page['annotations'],label,scale,circular)
            if not matches:
                failures.append({'kind':kind,'reason':'No valid clipped plan fills match this legend paint; withheld'})
            for candidate in matches:
                append(candidate,kind)
        except (ValueError,StopIteration) as error:
            failures.append({'kind':kind,'reason':str(error)})
    try:
        candidates,_ = extract_pattern_surfaces(Path(document['local_pdf']),page['annotations'],scale,REVIEW_DOCUMENT,
                                                label_text='New mainly indigenous ground cover ')
        for candidate in candidates:
            append(candidate,'ground_cover')
    except (ValueError,StopIteration) as error:
        failures.append({'kind':'ground_cover','reason':str(error)})
    # The legend uses the same brown stroke and line weight as four thin closed strips.
    label = next(a for a in page['annotations'] if a['text'].startswith('1.4m high Sound screens'))
    x0,y0,x1,y1 = label['bbox']
    swatches = [p for p in vectors if p.get('type')=='s' and p.get('rect') and
                0<=x0-p['rect'][2]<=100 and abs(p['rect'][1]-y0)<20 and (p.get('width') or 0)>1
                and p['rect'][3]-p['rect'][1]<=5 and 20<=p['rect'][2]-p['rect'][0]<=120]
    if len(swatches)!=1:
        raise ValueError('Unique acoustic screen legend stroke required')
    swatch = swatches[0]
    for index,path in enumerate(vectors):
        if (path.get('type') in ('s','fs') and path.get('color')==swatch['color'] and path.get('width')==swatch['width']
                and path['rect'][2]<swatch['rect'][0] and not path.get('layer')):
            polygon = painted_polygon(straightened(path))
            if polygon is not None and 2<=polygon.area*scale**2<=1000:
                append({'polygon':polygon,'vector_index':index},'sound_screen',height_m=1.4,
                       material='dark_stained_timber',height_status='printed_legend')
    components=json.loads((output/'wicker-man-component-candidates.geojson').read_text())
    for feature in components['features']:
        if feature['properties']['kind']=='sound_tunnel_footprint_candidate':
            features.append({**feature,'properties':{**feature['properties'],'kind':'sound_tunnel',
                             'shell_height_status':'unknown_section; preview_clearance_estimate_required'}})
    inventory = []
    for a in page['annotations']:
        if any(w in a['text'].lower() for w in ('fence','wall','graded','lowered')):
            inventory.append({**a,'status':'annotation_only_not_bound_to_verified_geometry'})
    report = {'status':'recovered_provisional_details','features_by_kind':{},'failures':failures,
              'unbound_wall_fence_and_grading_annotations':inventory,
              'blocked_sections':'Missing elevation/section PDFs currently unavailable from council endpoint',
              'roof_profiles':'Retained site plan/report establishes pitched roofs/materials, not exact roof geometry',
              'theming':'Envelopes do not define the finished effigy sculpture',
              'tree_species':'Approximate 50 percent evergreen palette; individual species positions not bound',
              'planting_heights':'Generic preview vegetation; schedule stock size is not mature canopy height'}
    for f in features:
        k=f['properties']['kind'];report['features_by_kind'][k]=report['features_by_kind'].get(k,0)+1
    (output/'wicker-man-detail-candidates.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},indent=2))
    (output/'wicker-man-details.json').write_text(json.dumps(report,indent=2))
    return features,report


def emit_details(features, project, terrain, route_line, rail_height, add, occupied):
    """Render bounded provisional acoustic shells and landscape symbols."""
    report = {'emitted_features':{},'withheld_planting_cells':0,
              'tunnel_clearance_above_rail_m':4,'tunnel_height_status':'estimate_not_printed_section',
              'screen_height_m':1.4,'screen_rasterisation':'ceil height at one metre blocks; minimum one cell thickness',
              'vegetation_status':'Generic palette and height; source symbol centres/areas only'}
    for index,feature in enumerate(features):
        kind = feature['properties']['kind']
        polygon = transform(project,shape(feature['geometry']))
        if polygon.is_empty or not polygon.is_valid or polygon.area>10000:
            continue
        generated = 0
        if kind == 'new_tree':
            centre = polygon.centroid;x,z = math.floor(centre.x),math.floor(centre.y)
            ground = terrain.sample(x+.5,z+.5)
            if ground is None:continue
            base = math.floor(ground)
            # Use generic young tree shapes, never mature heights from a planting stock schedule.
            evergreen = index%2 == 0
            cells=[]
            for y in range(base+1,base+5):cells.append((x,y,z,'spruce_log' if evergreen else 'oak_log'))
            for y in range(base+3,base+7):
                radius = 1 if y>=base+5 else 2
                for dx in range(-radius,radius+1):
                    for dz in range(-radius,radius+1):
                        if abs(dx)+abs(dz)<=radius+1 and (dx or dz):
                            cells.append((x+dx,y,z+dz,'spruce_leaves' if evergreen else 'oak_leaves'))
            # Prevent new vegetation from obstructing track clearance, buildings or paving.
            if any(k[:3] in occupied for k in cells) or any(
                    occupied.get((tx,base,tz),{}).get('feature','').endswith(('paving','paving_preview'))
                    for tx,_,tz,_ in cells):
                report['withheld_planting_cells']+=len(cells);continue
            for tx,y,tz,material in cells:add(tx,y,tz,material,'new_trees');generated+=1
        else:
            # Thin screen outlines would disappear with centre-only rasterisation.
            raster = polygon.buffer(.45) if kind=='sound_screen' else polygon
            x0,z0,x1,z1 = raster.bounds
            for x in range(math.floor(x0),math.ceil(x1)):
                for z in range(math.floor(z0),math.ceil(z1)):
                    point=Point(x+.5,z+.5)
                    if not raster.covers(point):continue
                    ground=terrain.sample(point.x,point.y)
                    if ground is None:continue
                    base=math.floor(ground)
                    if kind in ('understorey','ground_cover'):
                        height=2 if kind=='understorey' else 1
                        if any((x,base+d,z) in occupied for d in range(height+1)):
                            report['withheld_planting_cells']+=height;continue
                        for y in range(base+1,base+height+1):
                            add(x,y,z,'oak_leaves',kind);generated+=1
                    elif kind=='sound_screen':
                        rail=math.floor(rail_height(route_line.project(point)))
                        for y in range(rail,rail+math.ceil(feature['properties']['height_m'])):
                            add(x,y,z,'dark_oak_planks','sound_screens');generated+=1
                        if (x+z)%4==0:
                            for y in range(base+1,rail):add(x,y,z,'dark_oak_planks','sound_screen_posts')
                    elif kind=='sound_tunnel':
                        rail=math.floor(rail_height(route_line.project(point)));roof=rail+4
                        on_edge=polygon.boundary.distance(point)<.55
                        for y in range(min(base+1,rail),roof):
                            add(x,y,z,'dark_oak_planks' if on_edge else 'air',
                                'sound_tunnel_walls' if on_edge else 'sound_tunnel_clearance',not on_edge)
                        add(x,roof,z,'dark_oak_planks','sound_tunnel_roof');generated+=1
        if generated:report['emitted_features'][kind]=report['emitted_features'].get(kind,0)+1
    return report


def pitched_roof(polygon, point, observed_ridge, floor, pitch_degrees=30):
    """Generic gable profile; only pitched form is established by retained reports."""
    ring = list(polygon.minimum_rotated_rectangle.exterior.coords)
    edges = [(Point(a).distance(Point(b)),np.asarray(b)-np.asarray(a)) for a,b in zip(ring,ring[1:])]
    length,axis = max(edges,key=lambda item:item[0])
    width = min(item[0] for item in edges)
    normal = np.array([-axis[1],axis[0]])/length
    offset = abs(float(np.dot(np.asarray([point.x-polygon.centroid.x,point.y-polygon.centroid.y]),normal)))
    rise = min(5,width/2*math.tan(math.radians(pitch_degrees)))
    eaves = max(floor+4,observed_ridge-math.ceil(rise))
    return math.floor(eaves+max(0,1-offset/(width/2))*rise)
