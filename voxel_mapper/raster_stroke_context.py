"""Retain repeated narrow-stroke layouts before a residual jamb search.

A repeated layout can be hatch, cladding or real mullions. No material or
opening identity follows from this screen, and original pixels stay unchanged.
"""
from collections import defaultdict
import hashlib
import numpy as np

VERSION = 'repeated-raster-stroke-context-v1'
THRESHOLDS = (220, 235)


def review(gray, *, max_checks=100000, max_groups=4096):
    gray = np.asarray(gray)
    if gray.dtype != np.uint8 or gray.ndim != 2 or gray.size > 6000000 or max(gray.shape) > 3000:
        raise ValueError('Bounded uint8 stroke raster required')
    if type(max_checks) is not int or not 1 <= max_checks <= 100000 or type(max_groups) is not int or not 1 <= max_groups <= 4096:
        raise ValueError('Bounded stroke-context work required')
    base = {'version': VERSION, 'source_gray_sha256': hashlib.sha256(gray.tobytes()).hexdigest(),
        'recipe': {'thresholds': list(THRESHOLDS), 'min_height_pixels': 24, 'max_height_pixels': 700,
            'max_stroke_width_pixels': 3, 'min_strokes': 6, 'pitch_range_pixels': [2, 16],
            'pitch_spread_from_first_pixels': 1, 'endpoint_spread_pixels': 2,
            'max_groups_per_threshold': max_groups, 'max_checks': max_checks},
        'physical_identity_verified': False, 'training_labels_generated': 0, 'world_geometry_additions': 0}
    checks = 0; variants = []
    def charge():
        nonlocal checks
        checks += 1
        if checks > max_checks: raise OverflowError('stroke_context_check_budget')
    try:
        for threshold in THRESHOLDS:
            dark = gray < threshold; groups = []; previous = []
            for x in range(gray.shape[1]):
                changes = np.flatnonzero(np.diff(np.r_[False, dark[:, x], False].astype('int8'))); current = []
                for top, bottom in zip(changes[::2], changes[1::2]):
                    if not 24 <= bottom-top <= 700 or top == 0 or bottom == gray.shape[0]: continue
                    charge(); same = [i for i in previous if groups[i][1] == top and groups[i][3] == bottom]
                    if same: i = same[0]; groups[i][2] = x+1
                    else:
                        if len(groups) >= max_groups: raise OverflowError('stroke_context_group_budget')
                        i = len(groups); groups.append([x, int(top), x+1, int(bottom)])
                    current.append(i)
                previous = current
            sequences = set()
            # Nine overlapping integer phase partitions retain endpoint spreads
            # of at most two without transitive clustering or moved endpoints.
            for top_shift in range(3):
                for bottom_shift in range(3):
                    cohorts = defaultdict(list)
                    for i, (left, top, right, bottom) in enumerate(groups):
                        charge()
                        if right-left <= 3: cohorts[(top-top_shift)//3, (bottom-bottom_shift)//3].append(i)
                    for ids in cohorts.values():
                        ids.sort(key=lambda i: (groups[i][0], i)); sequence = []; pitch = None
                        for i in ids:
                            charge(); difference = groups[i][0]-groups[sequence[-1]][0] if sequence else None
                            if sequence and (not 2 <= difference <= 16 or groups[i][0] <= groups[sequence[-1]][2]
                                    or pitch is not None and abs(difference-pitch) > 1):
                                if len(sequence) >= 6: sequences.add(tuple(sequence))
                                sequence = []; pitch = None
                            if sequence and pitch is None: pitch = difference
                            sequence.append(i)
                        if len(sequence) >= 6: sequences.add(tuple(sequence))
            if len(sequences) > 4096: raise OverflowError('stroke_context_lattice_budget')
            excluded = sorted({i for seq in sequences for i in seq})
            variants.append({'threshold': threshold, 'original_vertical_groups': groups,
                'lattices': [{'group_indices': list(seq), 'first_pitch_pixels': groups[seq[1]][0]-groups[seq[0]][0],
                    'semantic_status': 'hatch_or_repeated_mullion_identity_unresolved'} for seq in sorted(sequences)],
                'residual_excluded_group_indices': excluded})
        return {**base, 'status': 'repeated_stroke_layout_context_only', 'checks': checks, 'variants': variants,
            'excluded_groups': {str(v['threshold']): [v['original_vertical_groups'][i] for i in v['residual_excluded_group_indices']] for v in variants},
            'limitations': ['Threshold-specific layout hypotheses are not independent evidence of physical role.',
                'Excluded groups remain in the evidence; real repeated mullions can satisfy this pattern.',
                'The residual search excludes these groups only as jamb proposals; heads use original pixels.']}
    except OverflowError as exc:
        return {**base, 'status': 'stroke_context_budget_withheld', 'reason': str(exc),
                'checks': checks, 'variants': [], 'excluded_groups': {}}
