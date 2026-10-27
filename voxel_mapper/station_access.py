"""Bounded review access to retained paving, and unplaced basement evidence."""
from collections import deque
from concurrent.futures import CancelledError
import math

from shapely.geometry import Point, Polygon, mapping

from .generation_cycles import file_hash

BASEMENT_SHA = 'e442e7fa1ebc1b020cfa1a8254470d541ddb4d51c5448fa252deef5b43eb0a6c'
UNIT = 100 * .0254 / 72


def paving_approach(opening, top, terrain, structures, protected, upper, paving,
                    *, cancelled=lambda: False, max_states=20000):
    """Find an estimated one-column approach; each cardinal rise is <= .5 m.

    End at actual retained source paving, not a coloured building/ride marker.
    No ground excavation, existing-object replacement or automatic queue claim.
    """
    if not 1 <= max_states <= 20000:
        raise ValueError('Bounded access search required')
    starts = sorted(set(map(tuple, opening['columns_xy'])) & upper)
    if not starts:
        raise ValueError('Entry must intersect the upper floor')
    centre = Point(*(sum(k[i] + .5 for k in starts) / len(starts) for i in (0, 1)))
    valid_cache = {}

    def valid(k, half):
        key = (*k, half)
        if key in valid_cache:
            return valid_cache[key]
        if k not in terrain or k in protected or centre.distance(Point(k[0]+.5, k[1]+.5)) > 12:
            return False
        surface = half / 2
        ground = terrain[k]['y'] + 1
        if (surface < ground or surface > top or (k not in upper and surface-ground > 4) or
                (k in upper and surface != top)):
            return False
        # Existing upper floor is already a valid support. Everywhere else
        # every proposed bearing block must fit without touching old objects.
        if k not in upper and any((k[0], h, k[1]) in structures
                                  for h in range(ground, math.ceil(surface))):
            return False
        clear = all((k[0], h, k[1]) not in structures
                    for h in (math.ceil(surface), math.ceil(surface)+1))
        valid_cache[key] = clear
        return clear

    queue = deque(); previous = {}
    for k in starts:
        state = (*k, 2*top)
        if valid(k, 2*top):
            queue.append(state); previous[state] = None
    end = None
    while queue:
        if cancelled():
            raise CancelledError('Station access search cancelled')
        state = queue.popleft(); x, y, half = state; k = (x, y)
        if k not in upper and k in paving and half == 2*(terrain[k]['y']+1):
            end = state; break
        for q in ((x-1,y), (x,y-1), (x,y+1), (x+1,y)):
            for nh in (half-1, half, half+1):
                candidate = (*q, nh)
                if candidate in previous or not valid(q, nh):
                    continue
                # A single column cannot have two walking heights in one path.
                if q in upper and q not in starts:
                    continue
                if len(previous) >= max_states:
                    return {}, {'status':'withheld_access_search_budget', 'states_examined':len(previous), 'surfaces':[]}
                previous[candidate] = state; queue.append(candidate)
    if end is None:
        return {}, {'status':'withheld_no_preserved_paving_connection', 'states_examined':len(previous), 'surfaces':[]}
    path = []; state = end
    while state is not None:
        path.append(state); state = previous[state]
    path.reverse()
    if len({(x,y) for x,y,h in path}) != len(path):
        return {}, {'status':'withheld_repeated_access_column', 'surfaces':[]}
    surfaces = {(x,y):h/2 for x,y,h in path}; added = {}
    for (x,y), surface in surfaces.items():
        if (x,y) in upper:
            continue
        for h in range(terrain[x,y]['y']+1, math.ceil(surface)):
            added[x,h,y] = 'stone_brick_slab' if h == math.ceil(surface)-1 and surface % 1 else 'stone_bricks'
    # Fence rails are outside all walking columns. Endpoints remain open.
    rails = set(); skipped = 0
    for x,y,_ in path[1:-1]:
        for q in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if q in surfaces or q in upper or q in protected or q not in terrain:
                continue
            adjacent = [v for k,v in surfaces.items() if abs(k[0]-q[0])+abs(k[1]-q[1]) == 1]
            rail = math.ceil(max(adjacent))
            # Do not fence off retained ground-level paths or the end landing.
            if terrain[q]['y']+1 >= rail or abs(q[0]-end[0])+abs(q[1]-end[1]) <= 1:
                continue
            proposal = {(q[0],h,q[1]):'stone_bricks' for h in range(terrain[q]['y']+1,rail)}
            proposal[q[0],rail,q[1]] = 'oak_fence'
            if any(k in structures for k in proposal) or (q[0],rail+1,q[1]) in structures:
                skipped += 1; continue
            added.update(proposal); rails.add(q)
    rises = [abs(h-surfaces[q]) for k,h in surfaces.items()
             for q in ((k[0]+1,k[1]),(k[0],k[1]+1)) if q in surfaces]
    # A path may pass beside an earlier segment: those cardinal contacts count.
    if max(rises, default=0) > .5:
        return {}, {'status':'withheld_access_side_contact_height_conflict', 'surfaces':[]}
    return added, {
        'status':'estimated_half_step_paving_connection',
        'ground_to_upper_floor_connected':True, 'retained_source_paving_endpoint_xy':list(end[:2]),
        'endpoint_ground_walking_top_m':end[2]/2, 'width_m':1, 'run_m':len(path)-1,
        'columns':len(path), 'maximum_neighbour_rise_m':max(rises,default=0),
        'source_opening_id':opening['id'], 'source_stair_dimensions_verified':False,
        'queue_alignment_verified':False, 'terrain_excavations':0,
        'oak_fence_rail_columns':len(rails), 'rail_gaps_due_to_preserved_geometry':skipped,
        'rail_policy':'oak fences for a path narrower than four blocks',
        'states_examined':len(previous), 'headroom_policy':'two whole air cells above rounded-up walking surface',
        'surfaces':[{'source_cell_xy':list(k),'walking_top_m':h} for k,h in sorted(surfaces.items())],
        'ordered_route_xy':[list(s[:2]) for s in path],
        'basis':'bounded display approach between review aperture and retained source paving; not a traced queue or architectural stair',
    }


def basement_review(pdf_path):
    """Replay visible outline strokes, keeping the basement in its own frame.

    Purple fill rectangles alone bridge the visible openings in this PDF.
    The outline endpoints are used instead, without assuming door semantics.
    """
    import pymupdf
    if file_hash(pdf_path) != BASEMENT_SHA:
        raise ValueError('Pinned original basement drawing required')
    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        if len(doc) != 1 or page.rotation != 90:
            raise ValueError('Original rotated basement page required')
        paths = page.get_drawings()
        bindings = {
            79:[1068.838134765625,1549.0997314453125,1068.838134765625,1574.89990234375],
            80:[1068.838134765625,1125.620361328125,1068.838134765625,1451.300537109375],
            83:[1055.998046875,1138.340087890625,1055.998046875,1451.300537109375],
            84:[1055.998046875,1549.0997314453125,1055.998046875,1562.1785888671875],
            74:[812.2787475585938,1138.340087890625,812.2787475585938,1562.1785888671875],
            89:[812.2787475585938,1562.1785888671875,1055.998046875,1562.1785888671875],
            122:[981.2382202148438,1125.620361328125,1055.998046875,1125.620361328125],
            123:[812.2787475585938,1125.620361328125,883.4390869140625,1125.620361328125],
            124:[812.2787475585938,1138.340087890625,883.4390869140625,1138.340087890625],
            125:[981.2382202148438,1138.340087890625,1055.998046875,1138.340087890625],
        }
        for index, bounds in bindings.items():
            d = paths[index]
            if d['type'] != 's' or len(d['items']) != 1 or d['items'][0][0] != 'l' or any(abs(a-b)>.02 for a,b in zip(d['rect'],bounds)):
                raise ValueError('Basement source outline stroke changed')
        text = ' '.join(page.get_text().split())
        if not all(s in text for s in ['Undercroft','+178.00','+181.250','+181.50','outline of preshow building above']):
            raise ValueError('Separate basement level roles required')
        # Conversion is native y-up, not rotated display x/y or geographic BNG.
        xy = lambda x,y:[x*UNIT,(page.mediabox.height-y)*UNIT]
        inner = Polygon([xy(x,y) for x,y in [(812.2787476,1138.3400879),(1055.9980469,1138.3400879),(1055.9980469,1562.1785889),(812.2787476,1562.1785889)]])
        gaps = [
            {'id':'undercroft-side-gap','stroke_indices':[122,123,124,125],
             'raw_pdf_endpoints':[[883.4390869140625,1138.340087890625],[981.2382202148438,1138.340087890625]]},
            {'id':'undercroft-end-gap','stroke_indices':[79,80,83,84],
             'raw_pdf_endpoints':[[1055.998046875,1451.300537109375],[1055.998046875,1549.0997314453125]]},
        ]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(.8,.8))
        from PIL import Image,ImageDraw
        image = Image.frombytes('RGB',(pix.width,pix.height),pix.samples); draw = ImageDraw.Draw(image)
        for gap in gaps:
            points = gap['raw_pdf_endpoints']
            gap['width_m'] = math.dist(*points)*UNIT
            gap['source_local_endpoints_m'] = [xy(*p) for p in points]
            gap['door_or_passenger_route_verified'] = False
            display = [pymupdf.Point(p)*page.rotation_matrix for p in points]
            screen = [(p.x*pix.width/page.rect.width,p.y*pix.height/page.rect.height) for p in display]
            draw.line(screen,fill='#df301c',width=7)
            draw.text((screen[0][0]+8,screen[0][1]-16),gap['id']+' %.2f m'%gap['width_m'],fill='#bd1d13')
        result = {
            'version':'basement-visible-outline-review-v1', 'source_sha256':BASEMENT_SHA,
            'page':1, 'scale_metres_per_point':UNIT, 'coordinate_frame':'own-sheet printed-scale metres; native y up',
            'source_stroke_bounds':{str(k):v for k,v in bindings.items()},
            'inner_clear_envelope_geometry':mapping(inner), 'inner_clear_envelope_dimensions_m':[243.7192993*UNIT,423.8385010*UNIT],
            'inner_clear_envelope_area_m2':inner.area, 'visible_wall_gaps':gaps,
            'printed_levels_m':{'undercroft':178.,'station_inspection':181.25,'maintenance':181.5},
            'world_placement_verified':False, 'world_geometry_added':0, 'internal_stair_reconstructed':False,
            'accepted_training_labels':0,
            'limitations':['Two visible wall gaps are not assigned as queue doors without circulation evidence.',
                'Undercroft differs from the upper preshow outline; its own-sheet geometry is not automatically placed using roof-page coordinates.',
                'Printed proposal levels do not establish an ODN or as-built reference.',
                'No internal stair connection is established by this basement sheet.',
                'Visible outline-stroke endpoints are replayed; purple fill rectangles alone incorrectly bridge gaps.'],
        }
    return result,image
