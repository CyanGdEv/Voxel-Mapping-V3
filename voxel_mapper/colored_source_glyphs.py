"""Complementary RGB glyph screen using copied original CID font resources.

The existing black-text recipe and all of its holds remain unchanged.
"""
import hashlib
import math
import re

import numpy as np
import pymupdf

from .glyph_visibility import cff_glyph_codes, grow

VERSION = 'original-cid-rgb-glyph-screen-v1'


def screen(page, span, *, zoom=6):
    failure = {'version': VERSION, 'status': 'withheld', 'visibility_verified': False}
    color = span.get('color', ())
    if (zoom != 6 or span.get('type') != 0 or span.get('opacity') != 1 or span.get('layer')
            or tuple(span.get('dir', ())) != (1., 0.) or len(color) != 3
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in color)
            or max(color) - min(color) < .1 or not 1 <= span.get('size', 0) <= 40
            or not 1 <= len(span.get('chars', ())) <= 100
            or any(not 32 <= c[0] <= 126 for c in span['chars'])
            or page.cropbox.x0 != 0 or page.cropbox.y0 != 0):
        return {**failure, 'reason': 'unsupported_original_color_or_text_convention'}
    fonts = [f for f in page.get_fonts(full=True) if f[3].split('+')[-1] == span.get('font')]
    if not 1 <= len(fonts) <= 4:
        return {**failure, 'reason': 'original_font_resource_ambiguous_or_missing'}
    candidates = []
    rotation = page.rotation
    try:
        page.set_rotation(0)
        clip = pymupdf.Rect(span['bbox']) + (-.5, -.5, .5, .5)
        if clip.width * clip.height * zoom * zoom > 1000000:
            return {**failure, 'reason': 'glyph_pixel_budget'}
        source = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, colorspace=pymupdf.csRGB, alpha=False)
        original = np.frombuffer(source.samples, np.uint8).reshape(source.height, source.width, 3)
        paint = np.array(color) * 255
        source_ink = np.max(np.abs(original.astype(float) - paint), axis=2) <= 16
        for font in fonts:
            buffer = page.parent.extract_font(font[0])[3]
            if not 0 < len(buffer) <= 2000000 or buffer[:1] != b'\x01':
                return {**failure, 'reason': 'original_embedded_cid_cff_required'}
            kind, children = page.parent.xref_get_key(font[0], 'DescendantFonts')
            child = re.fullmatch(r'\[\s*(\d+)\s+0\s+R\s*\]', children) if kind == 'array' else None
            if (not child or font[2] != 'Type0' or font[5] != 'Identity-H'
                    or page.parent.xref_get_key(int(child[1]), 'Subtype') != ('name', '/CIDFontType0')):
                return {**failure, 'reason': 'original_identity_h_cid_font_required'}
            try:
                codes = cff_glyph_codes(buffer, span['chars'])
            except (ValueError, KeyError, IndexError, AssertionError) as error:
                return {**failure, 'reason': str(error)}
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', font[4]):
                return {**failure, 'reason': 'unsupported_source_font_resource_name'}
            with pymupdf.open() as doc:
                doc.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
                reference = doc[0]; reference.set_rotation(0)
                commands = [' '.join(format(v, '.12g') for v in color) + ' rg']
                for char, code in zip(span['chars'], codes):
                    x, y = char[2]
                    commands.append(f'BT /{font[4]} {span["size"]:.12g} Tf 1 0 0 1 {x:.12g} {reference.rect.height-y:.12g} Tm <{code:04x}> Tj ET')
                content = doc.get_new_xref(); doc.update_object(content, '<<>>')
                doc.update_stream(content, '\n'.join(commands).encode('ascii'))
                doc.xref_set_key(reference.xref, 'Contents', f'{content} 0 R')
                expected = reference.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, colorspace=pymupdf.csRGB, alpha=False)
            if (source.width, source.height, source.x, source.y) != (expected.width, expected.height, expected.x, expected.y):
                return {**failure, 'reason': 'original_and_reference_frames_differ'}
            reference_rgb = np.frombuffer(expected.samples, np.uint8).reshape(source.height, source.width, 3)
            core = np.max(np.abs(reference_rgb.astype(float) - paint), axis=2) <= 8
            ink = np.max(255 - reference_rgb.astype(int), axis=2) >= 32
            ring = grow(ink, 2) & ~grow(ink)
            support = grow(source_ink); glyphs = []
            for i, char in enumerate(span['chars']):
                if char[0] == 32: continue
                x0, y0, x1, y1 = char[3]
                left, right = max(0, math.floor(x0*zoom-source.x)), min(source.width, math.ceil(x1*zoom-source.x))
                top, bottom = max(0, math.floor(y0*zoom-source.y)), min(source.height, math.ceil(y1*zoom-source.y))
                mask = core[top:bottom, left:right]
                glyphs.append({'character_index': i, 'core_pixels': int(mask.sum()),
                               'unsupported_core_pixels': int(np.count_nonzero(mask & ~support[top:bottom, left:right]))})
            ring_count = int(ring.sum()); unexpected = int(np.count_nonzero(source_ink & ring))
            passed = bool(glyphs) and all(g['core_pixels'] >= 3 and g['unsupported_core_pixels']/g['core_pixels'] <= .01 for g in glyphs)
            passed = passed and ring_count > 0 and unexpected/ring_count <= .01
            candidates.append({'status': 'raster_consistent_candidate' if passed else 'withheld',
                'original_font_xref': font[0], 'original_font_resource': font[4],
                'original_font_sha256': hashlib.sha256(buffer).hexdigest(), 'original_cids': codes,
                'glyphs': glyphs, 'ring_pixels': ring_count, 'unexpected_color_ring_pixels': unexpected,
                'reference_rgb_sha256': hashlib.sha256(expected.samples).hexdigest()})
        passing = [c for c in candidates if c['status'] == 'raster_consistent_candidate']
        distinct = {c['original_font_sha256'] for c in passing}
        return {**failure, 'status': 'raster_consistent_candidate' if len(distinct) == 1 else 'withheld',
                'source_rgb_sha256': hashlib.sha256(source.samples).hexdigest(), 'source_color_rgb': list(color),
                'zoom_pixels_per_pdf_point': zoom, 'source_size_pixels': [source.width, source.height],
                'original_font_candidates': candidates, 'source_pixel_rgb_tolerance': 16,
                'reference_core_rgb_tolerance': 8, 'pixel_position_tolerance': 1,
                'max_unsupported_core_fraction': .01, 'max_unexpected_color_ring_fraction': .01,
                'source_pdf_modified': False, 'font_substitution_used': False,
                'limitations': ['Original RGB glyph consistency is not physical identity, source-state or datum verification.',
                               'Only horizontal ASCII text with embedded Identity-H CID CFF fonts is supported.']}
    finally:
        page.set_rotation(rotation)
