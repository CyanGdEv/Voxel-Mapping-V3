"""Original numeric leaders and closed section roof outlines; no inferred joins."""
import itertools
import math

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

from . import colored_source_glyphs, glyph_visibility
from .reconstruction_evidence_queue import digest

VERSION = 'section-roof-leaders-v1'


def numeric_words(page, target, charge):
    traces = page.get_texttrace(); words = page.get_text('words')
    if len(traces) > 10000 or len(words) > 20000 or sum(len(t['chars']) for t in traces) > 500000:
        raise OverflowError('section_text_budget')
    result = []; screens = {}
    for index, word in enumerate(words):
        charge()
        if word[4] != target: continue
        box = pymupdf.Rect(word[:4]); chars = []
        for ti, trace in enumerate(traces):
            charge()
            if not box.intersects(pymupdf.Rect(trace['bbox'])): continue
            for ci, char in enumerate(trace['chars']):
                center = (pymupdf.Rect(char[3]).tl + pymupdf.Rect(char[3]).br) * .5
                if box.contains(center): chars.append((char[2][0], ti, ci, char))
        chars.sort(key=lambda c: (c[0], c[1], c[2]))
        ids = sorted({c[1] for c in chars})
        text_matches = ''.join(chr(c[3][0]) for c in chars) == target
        for ti in ids:
            if ti not in screens:
                charge(); span = traces[ti]
                screens[ti] = colored_source_glyphs.screen(page, span) if len(span['color']) == 3 and max(span['color'])-min(span['color']) >= .1 else glyph_visibility.screen_span(page, span)
        row = {'word_index': index, 'text': target, 'source_bbox_pdf_unrotated': list(box),
               'trace_character_indices': [[c[1], c[2]] for c in chars], 'trace_indices': ids,
               'trace_glyphs_match_original_word': text_matches,
               'source_colors_rgb': [list(traces[i]['color']) for i in ids],
               'status': 'source_numeric_glyph_candidate' if text_matches and ids and all(screens[i]['status'] == 'raster_consistent_candidate' for i in ids) else 'numeric_source_glyphs_held',
               'physical_level_identity_verified': False, 'vertical_datum_verified': False}
        row['id'] = digest([VERSION, row]); result.append(row)
        if len(result) > 100: raise OverflowError('section_numeric_word_budget')
    return result, screens


def strokes(page, sha, words, charge):
    paths = page.get_cdrawings(extended=True)
    if len(paths) > 500000: raise OverflowError('section_original_path_budget')
    regions = [pymupdf.Rect(w['source_bbox_pdf_unrotated']) + (-180, 0, 180, 260) for w in words]
    result = []
    for pi, path in enumerate(paths):
        charge()
        if path['type'] != 's' or path.get('layer') or path.get('stroke_opacity') != 1 or path.get('dashes') != '[] 0': continue
        rect = pymupdf.Rect(path['rect'])
        if not any(rect.x0 <= r.x1 and rect.x1 >= r.x0 and rect.y0 <= r.y1 and rect.y1 >= r.y0 for r in regions): continue
        if len(path['items']) > 10000: raise OverflowError('section_path_item_budget')
        path_pin = digest(path)
        for ii, item in enumerate(path['items']):
            charge()
            if item[0] != 'l': continue
            points = [list(p) for p in item[1:3]]
            if not np.isfinite(points).all(): raise ValueError('Finite original section lines required')
            length = math.dist(*points)
            if not 2 <= length <= 250: continue
            row = {'document_sha256': sha, 'page': page.number+1, 'path_index': pi, 'item_index': ii,
                   'path_record_sha256': path_pin, 'source_endpoints_pdf_unrotated': points,
                   'color_rgb': list(path['color']), 'stroke_width_pdf_points': path['width'], 'paint_seqno': path['seqno'],
                   'length_pdf_points': length, 'source_line_clipped_or_extended': False}
            row['id'] = digest([VERSION, row]); result.append(row)
            if len(result) > 30000: raise OverflowError('section_local_line_budget')
    return result


def discover(words, lines, charge):
    if not lines: return []
    points = [p for line in lines for p in line['source_endpoints_pdf_unrotated']]; tree = cKDTree(points)
    by_endpoints = {}
    for line in lines:
        key = tuple(sorted(tuple(p) for p in line['source_endpoints_pdf_unrotated']))
        by_endpoints.setdefault(key, []).append(line)

    def incident(point):
        return [(lines[i//2], i % 2) for i in sorted(tree.query_ball_point(point, .25))]

    result = []
    for word in words:
        x0, y0, x1, y1 = word['source_bbox_pdf_unrotated']; height = y1-y0
        for leader in lines:
            charge(); a, b = sorted(leader['source_endpoints_pdf_unrotated'], key=lambda p: p[1])
            if not (x0 <= a[0] <= x1 and 0 <= a[1]-y1 <= height and 16 <= b[1]-a[1] <= 240
                    and abs(b[0]-a[0]) <= .03*(b[1]-a[1])): continue
            heads = []; slopes = []
            for line, end in incident(b):
                charge(); near = line['source_endpoints_pdf_unrotated'][end]; far = line['source_endpoints_pdf_unrotated'][1-end]
                dx, dy = far[0]-b[0], far[1]-b[1]
                if (2 <= line['length_pdf_points'] <= 12 and dy < 0
                        and .3 <= abs(dx/dy) <= 3): heads.append((line, end))
                if dy > 2 and abs(dx) > 2 and .1 <= dy/abs(dx) <= 3 and line['length_pdf_points'] >= 12:
                    slopes.append((line, end))
            head_pairs = [[a[0]['id'], c[0]['id']] for a, c in itertools.combinations(heads, 2)
                          if (a[0]['source_endpoints_pdf_unrotated'][1-a[1]][0]-b[0]) *
                             (c[0]['source_endpoints_pdf_unrotated'][1-c[1]][0]-b[0]) < 0]
            roof_pairs = []
            for left, right in itertools.combinations(slopes, 2):
                charge(); l, li = left; r, ri = right
                le = l['source_endpoints_pdf_unrotated'][1-li]; re = r['source_endpoints_pdf_unrotated'][1-ri]
                if (le[0]-b[0])*(re[0]-b[0]) >= 0: continue
                cap = by_endpoints.get(tuple(sorted((tuple(le), tuple(re)))), [])
                exact_apex = l['source_endpoints_pdf_unrotated'][li] == b == r['source_endpoints_pdf_unrotated'][ri]
                row = {'slope_source_ids': [l['id'], r['id']], 'source_apex_pdf_unrotated': b,
                       'source_slope_far_endpoints': [le, re], 'cap_source_ids': [c['id'] for c in cap],
                       'source_apex_endpoint_gaps_pdf_points': [math.dist(l['source_endpoints_pdf_unrotated'][li], b), math.dist(r['source_endpoints_pdf_unrotated'][ri], b)],
                       'status': 'closed_original_section_triangle_candidate' if exact_apex and cap and head_pairs and word['status'] == 'source_numeric_glyph_candidate' else 'section_roof_boundary_or_visibility_held',
                       'nominal_metres_per_pdf_point': None, 'scale_application_verified': False,
                       'physical_roof_correspondence_verified': False, 'geometry_export_authorized': False}
                row['id'] = digest([VERSION, row]); roof_pairs.append(row)
            record = {'word_id': word['id'], 'leader_source_id': leader['id'], 'source_label_gap_pdf_points': a[1]-y1,
                      'source_arrow_head_pairs': head_pairs, 'roof_pairs': roof_pairs,
                      'source_line_clipped_or_extended': False, 'physical_level_identity_verified': False}
            record['id'] = digest([VERSION, record]); result.append(record)
            if len(result) > 1000: raise OverflowError('section_leader_candidate_budget')
    return result


def line_pixels(page, line, displaylist=None):
    """Original RGB neighbourhoods at fixed whole-segment sample fractions."""
    a, b = line['source_endpoints_pdf_unrotated']; clip = pymupdf.Rect(min(a[0],b[0]), min(a[1],b[1]), max(a[0],b[0]), max(a[1],b[1])) + (-1,-1,1,1)
    rotation = page.rotation
    try:
        page.set_rotation(0); pix = (displaylist or page.get_displaylist()).get_pixmap(matrix=pymupdf.Matrix(6,6), clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    finally: page.set_rotation(rotation)
    if pix.width*pix.height > 3000000: raise OverflowError('section_stroke_pixel_budget')
    rgb = np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3); color = np.array(line['color_rgb'])*255; witnesses=[]
    for i in range(1,32):
        t=i/32; p=[a[j]+t*(b[j]-a[j]) for j in (0,1)]; x=math.floor(p[0]*6)-pix.x; y=math.floor(p[1]*6)-pix.y
        window=rgb[max(0,y-1):y+2,max(0,x-1):x+2]; difference=np.max(np.abs(window.astype(float)-color),axis=2)
        witnesses.append({'fraction':t,'source_neighbourhood_rgb':window.tolist(),'matching_source_color_present':bool(np.any(difference<=24))})
    return {'line_id':line['id'],'source_rgb_sha256':__import__('hashlib').sha256(pix.samples).hexdigest(),
            'source_raster_origin_pixels':[pix.x,pix.y],'source_raster_size_pixels':[pix.width,pix.height],
            'source_samples':witnesses,'rgb_tolerance':24,'all_samples_supported':all(w['matching_source_color_present'] for w in witnesses),
            'visibility_verified':False}
