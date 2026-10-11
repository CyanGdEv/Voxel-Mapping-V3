"""Exact adjacent-face envelopes for landmark review, never building semantics."""
import copy
import hashlib
import json
from collections import Counter
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

VERSION = 'linework-envelopes-v1'


def contract(parent_contract, recovery_options):
    return hashlib.sha256(json.dumps({'version':VERSION,'parent_contract':parent_contract,
        'recovery_options':recovery_options,'max_faces':4000,'max_pairs':100000},sort_keys=True).encode()).hexdigest()


def combine(records):
    """Remove exact shared dividers without snapping, hulls or filling holes."""
    if len(records) > 20000: raise ValueError('Envelope page budget exceeded')
    faces = [r for r in records if r.get('extraction_kind') == 'linework_boundaries']
    if len(faces) > 4000: raise ValueError('Envelope face budget exceeded')
    if not faces: return [], {'status':'no_enclosed_faces','envelopes':0}
    if len({(r['document_sha256'],r['page'],r['extraction_contract']) for r in faces}) != 1:
        raise ValueError('One retained face page required')
    if len({r['id'] for r in faces}) != len(faces): raise ValueError('Unique envelope face identities required')
    if any(r.get('coordinate_frame') != 'pdf_native_points_y_up' for r in faces):
        raise ValueError('Native envelope coordinate frame required')
    geometries = [shape(r['geometry']) for r in faces]
    if any(g.geom_type != 'Polygon' or not g.is_valid or g.is_empty for g in geometries):
        raise ValueError('Valid envelope face polygons required')
    index = STRtree(geometries); leaders = list(range(len(faces))); counts = Counter(); pairs = 0
    def leader(i):
        while leaders[i] != i: leaders[i] = leaders[leaders[i]]; i = leaders[i]
        return i
    for i,g in enumerate(geometries):
        for j in index.query(g,predicate='intersects'):
            j = int(j)
            if j <= i: continue
            pairs += 1
            if pairs > 100000: return [], {'status':'pair_budget_withheld','envelopes':0}
            other = geometries[j]
            # An interior ring is a protected source boundary. Its nested face
            # is not evidence that a courtyard, shaft or void should be filled.
            if any(Polygon(r).covers(other) for r in g.interiors) or any(Polygon(r).covers(g) for r in other.interiors):
                counts['nested_hole_links_withheld'] += 1; continue
            if g.intersection(other).area > 1e-10:
                counts['overlap_links_withheld'] += 1; continue
            if g.boundary.intersection(other.boundary).length <= 1e-7:
                counts['point_contacts_withheld'] += 1; continue
            a,b = leader(i),leader(j); leaders[max(a,b)] = min(a,b)
    groups = {}
    for i in range(len(faces)): groups.setdefault(leader(i),[]).append(i)
    output = []; seen = {r['id'] for r in records}
    for members in groups.values():
        if len(members) < 2: continue
        if len(records)+len(output) >= 20000: counts['page_budget_withheld'] += 1; continue
        selected = [geometries[i] for i in members]; polygon = unary_union(selected)
        if polygon.geom_type != 'Polygon' or not polygon.is_valid: counts['invalid_unions'] += 1; continue
        if len(polygon.exterior.coords)+sum(len(r.coords) for r in polygon.interiors) > 10000:
            counts['vertex_budget_withheld'] += 1; continue
        # No area may be invented and no source hole may disappear through a
        # chain of adjacent faces rather than a direct nested-face link.
        if abs(polygon.area-sum(g.area for g in selected)) > max(1e-7,polygon.area*1e-10):
            counts['area_conservation_withheld'] += 1; continue
        if any(polygon.intersection(Polygon(r)).area > 1e-7 for g in selected for r in g.interiors):
            counts['hole_filling_withheld'] += 1; continue
        first = faces[members[0]]; digest = hashlib.sha256((first['document_sha256']+'/'+str(first['page'])+'/'+polygon.normalize().wkb_hex).encode()).hexdigest()
        if digest in seen: counts['existing_polygon_duplicates'] += 1; continue
        paints = {}; links = {}
        for i in members:
            for paint in faces[i]['paint_references']: paints[json.dumps(paint,sort_keys=True)] = paint
            for link in faces[i]['line_parent_references']: links[link['candidate_id']] = link
        if len(paints) > 2048 or len(links) > 2048: counts['provenance_budget_withheld'] += 1; continue
        record = copy.deepcopy(first)
        record.pop('line_parent_references',None)
        record.update(id=digest,geometry=json.loads(json.dumps(mapping(polygon))),
            extraction_kind='linework_envelopes',extraction_version=VERSION,
            extraction_contract=contract(first['parent_extraction_contract'],first['recovery_options']),
            face_parent_ids=sorted(faces[i]['id'] for i in members),
            face_parent_references=sorted([{'candidate_id':faces[i]['id'],
                'extraction_contract':faces[i]['extraction_contract']} for i in members],key=lambda p:p['candidate_id']),
            paint_references=[paints[k] for k in sorted(paints)],
            rendering_status='derived_exact_adjacent_face_envelope; visibility_unverified',
            semantic_status='unclassified_region_envelope',physical_identity_verified=False,
            registration_verified=False,world_geometry_additions=0)
        output.append(record); seen.add(digest)
    output.sort(key=lambda r:r['id'])
    return output, {'status':'exact_adjacent_face_envelopes','envelopes':len(output),
                    'face_count':len(faces),'intersection_pairs':pairs,'counts':dict(counts),
                    'world_geometry_additions':0}


def retained_envelopes(corpus,candidate):
    from .drawing_geometry import VERSION as parent_version
    from .linework_boundaries import options, recover_page
    opts = options(candidate.get('recovery_options')); parent = candidate.get('parent_extraction_contract')
    if candidate.get('extraction_version') != VERSION or candidate.get('extraction_contract') != contract(parent,opts):
        raise ValueError('Current source envelope contract required')
    row = corpus.db.execute('SELECT result FROM geometry_pages WHERE sha=? AND page=? AND version=? AND contract=?',
        (candidate['document_sha256'],candidate['page'],parent_version,parent)).fetchone()
    if not row: raise ValueError('Retained envelope geometry parents required')
    records,_ = recover_page(json.loads(row[0])['candidates'],recovery_options=opts)
    envelopes,_ = combine(records)
    return records+envelopes
