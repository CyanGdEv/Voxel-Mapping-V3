"""Exact work components for all-pair jamb compatibility; no drawing geometry edits."""
from collections import defaultdict

VERSION = 'jamb-compatibility-work-components-v1'


def partition(groups, min_width, max_width, max_component_groups, charge):
    """Every potentially eligible pair belongs to one component, before head tests."""
    if (len(groups) > 4096 or type(max_component_groups) is not int or not 1 <= max_component_groups <= 512
            or type(min_width) is not int or type(max_width) is not int or not 1 <= min_width <= max_width <= 600):
        raise ValueError('Bounded original groups and active work components required')
    parent = list(range(len(groups))); buckets = defaultdict(list)
    for i, group in enumerate(groups):
        charge(); buckets[group['top']//3, group['bottom']//3].append(i)
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    pair_counts = [0]*len(groups)
    for i, left in enumerate(groups):
        for top_bin in range((left['top']-2)//3, (left['top']+2)//3+1):
            for bottom_bin in range((left['bottom']-2)//3, (left['bottom']+2)//3+1):
                charge()
                for j in buckets.get((top_bin, bottom_bin), []):
                    charge(); right = groups[j]
                    if not min_width <= right['left']-left['right'] <= max_width: continue
                    if max(abs(left[k]-right[k]) for k in ('top', 'bottom')) > 2: continue
                    a, b = find(i), find(j)
                    if a != b: parent[max(a, b)] = min(a, b)
                    pair_counts[i] += 1
    components = defaultdict(list)
    for i in range(len(groups)): components[find(i)].append(i)
    records = []
    for ids in sorted(components.values(), key=lambda ids: ids[0]):
        charge()
        if len(ids) > max_component_groups: raise OverflowError('compatible_component_group_budget')
        records.append({'group_indices': ids, 'eligible_directed_pairs': sum(pair_counts[i] for i in ids)})
    return {'version': VERSION, 'components': records,
        'max_component_groups': max((len(r['group_indices']) for r in records), default=0),
        'total_original_groups': len(groups), 'eligible_directed_pairs': sum(pair_counts),
        'basis': 'all_original_pairs_with_width_and_endpoint_compatibility_before_head_tests',
        'cross_component_eligible_pairs': 0, 'source_endpoints_changed': False,
        'physical_connectivity_verified': False}
