"""Unseeded jamb/head raster correspondences, never certified physical openings."""
import hashlib
import numpy as np

VERSION = 'raster-opening-scan-v5'
MAX_INDEX_PAIRS = 8192
THRESHOLDS = (220, 235)


def scan(gray, *, min_height=24, min_width=20, max_width=600, max_groups=512, max_checks=100000, pair_scope="all", representation="expanded", excluded_groups=None, partition_groups=False):
    if type(partition_groups) is not bool or partition_groups and pair_scope!='all':
        raise ValueError('Boolean group partitioning supports all-pair scope only')
    if pair_scope not in ("all","adjacent_compatible_jambs"):
        raise ValueError("Declared opening pair scope required")
    if representation not in ("expanded","indexed"):
        raise ValueError("Declared opening evidence representation required")
    gray=np.asarray(gray)
    if gray.ndim!=2 or gray.dtype!=np.uint8 or gray.size>6000000 or max(gray.shape)>3000:
        raise ValueError('Bounded uint8 opening raster required')
    for value,limit in ((min_height,400),(min_width,600),(max_width,600),(max_groups,512),(max_checks,100000)):
        if type(value) is not int or not 1<=value<=limit:raise ValueError('Bounded opening scan options required')
    if min_width>max_width:raise ValueError('Ordered opening discovery widths required')
    exclusions={t:set() for t in THRESHOLDS}
    if excluded_groups is not None:
        if not isinstance(excluded_groups,dict) or set(excluded_groups)!={str(t) for t in THRESHOLDS}:
            raise ValueError('Both threshold-specific source group lists required')
        h,w=gray.shape
        for threshold in THRESHOLDS:
            rows=excluded_groups[str(threshold)];seen=set()
            if not isinstance(rows,list) or len(rows)>4096:raise ValueError('Bounded source group exclusions required')
            dark=gray<threshold
            for row in rows:
                if not isinstance(row,list) or len(row)!=4 or any(type(v) is not int for v in row):
                    raise ValueError('Integer original group bounds required')
                left,top,right,bottom=row;key=tuple(row)
                if (key in seen or not 0<=left<right<=w or not 1<=right-left<=3 or not 0<top<bottom<h
                        or not min_height<=bottom-top<=700):raise ValueError('Unique bounded original groups required')
                seen.add(key)
                if (not dark[top:bottom,left:right].all() or dark[top-1,left:right].any() or dark[bottom,left:right].any()):
                    raise ValueError('Excluded group differs from original complete vertical runs')
                for x in (left-1,right):
                    if (0<=x<w and dark[top:bottom,x].all() and not dark[top-1,x] and not dark[bottom,x]):
                        raise ValueError('Whole original group width required')
                exclusions[threshold].update((x,top,bottom) for x in range(left,right))
    base={'version':VERSION,'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),
          'size_pixels':[gray.shape[1],gray.shape[0]],
          'recipe':{'representation':representation,'pair_scope':pair_scope,'thresholds':list(THRESHOLDS),'min_height_pixels':min_height,
                    'min_width_pixels':min_width,'max_groups':max_groups,'max_checks':max_checks,
                    'max_endpoint_spread_pixels':2,'minimum_head_dark_fraction':.9,
                    'maximum_width_pixels':max_width,'maximum_height_pixels':700},
          'physical_opening_verified':False,'world_geometry_additions':0}
    if excluded_groups is not None:
        base.update(search_scope='residual_jamb_groups_only',excluded_group_bounds=excluded_groups,
                    complete_unscreened_inventory=False)
    checks=0;variants=[];group_tables=[];partition_reports=[]
    if partition_groups:
        base['recipe'].update(group_partitioning='exact_compatibility_components',max_retained_groups=4096,
                              max_groups_per_component=max_groups)
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise OverflowError('compatible_group_partition_work_budget')
    def withheld(reason):return {**{k:v for k,v in base.items() if k!='group_partition_proofs'},'status':'scan_budget_withheld','reason':reason,'candidates':[],
        'index':None,'checks':checks}
    for threshold in THRESHOLDS:
        dark=gray<threshold;groups=[];previous=[]
        for x in range(gray.shape[1]):
            changes=np.flatnonzero(np.diff(np.r_[False,dark[:,x],False].astype('int8')))
            current=[]
            for top,bottom in zip(changes[::2],changes[1::2]):
                if not min_height<=bottom-top<=700 or top==0 or bottom==gray.shape[0]:continue
                if (x,int(top),int(bottom)) in exclusions[threshold]:continue
                # Merge only adjacent columns with identical full run extents.
                # No gaps, diagonal snapping or partial-jamb extension.
                same=[g for g in previous if g['top']==top and g['bottom']==bottom]
                if len(same)==1:group=same[0];group['right']=x+1
                else:
                    group={'left':x,'right':x+1,'top':int(top),'bottom':int(bottom)};groups.append(group)
                    if len(groups)>(4096 if partition_groups else max_groups):return withheld('retained_group_budget' if partition_groups else 'vertical_run_group_budget')
                current.append(group)
            previous=current
        group_tables.append(groups)
        group_indices={id(g):i for i,g in enumerate(groups)}
        pairs=[];buckets={}
        owners=None
        if partition_groups:
            from .jamb_group_partitions import partition
            try:proof=partition(groups,min_width,max_width,max_groups,charge)
            except OverflowError as exc:return withheld(str(exc))
            partition_reports.append({'threshold':threshold,**proof});owners={i:k for k,c in enumerate(proof['components']) for i in c['group_indices']}
        for group in groups:buckets.setdefault((group['top']//3,group['bottom']//3),[]).append(group)
        for left in groups:
            nearby=[]
            for top_bin in range((left['top']-2)//3,(left['top']+2)//3+1):
                for bottom_bin in range((left['bottom']-2)//3,(left['bottom']+2)//3+1):
                    nearby.extend(buckets.get((top_bin,bottom_bin),[]))
            if pair_scope=='adjacent_compatible_jambs':
                compatible=[]
                for right in nearby:
                    checks+=1
                    if checks>max_checks:return withheld('adjacency_search_budget')
                    if right['left']>=left['right'] and max(abs(left[k]-right[k]) for k in ('top','bottom'))<=2:
                        compatible.append(right)
                nearest=min((r['left'] for r in compatible),default=None)
                nearby=[r for r in compatible if r['left']==nearest]
            for right in nearby:
                if owners is not None and owners[group_indices[id(left)]]!=owners[group_indices[id(right)]]:continue
                width=right['left']-left['right']
                if not min_width<=width<=max_width:continue
                checks+=1
                if checks>max_checks:return withheld('jamb_pair_budget')
                if max(abs(left[k]-right[k]) for k in ('top','bottom'))>2:continue
                top=min(left['top'],right['top']);bottom=min(left['bottom'],right['bottom'])
                if not min_height<=bottom-top<=700:continue
                heads=[]
                for y in range(max(0,top-2),min(gray.shape[0],top+3)):
                    support=float(dark[y,left['left']:right['right']].mean())
                    if support>=.9:heads.append({'row':y,'dark_fraction':support})
                if heads:
                    pair={'head_support':heads,'threshold':threshold,
                        'bounds_pixels':[left['right'],top,right['left'],bottom]}
                    if representation=='indexed':
                        pair['jamb_group_indices']=[group_indices[id(left)],group_indices[id(right)]]
                    else:pair.update(left_jamb=left.copy(),right_jamb=right.copy())
                    pairs.append(pair)
                if len(pairs)>(MAX_INDEX_PAIRS if representation=='indexed' else 512):
                    return withheld('indexed_pair_count_budget' if representation=='indexed' else 'opening_pair_count_budget')
        variants.append(pairs)
    if partition_groups:base['group_partition_proofs']=partition_reports
    if representation=='indexed':
        # Endpoint bins avoid a Cartesian threshold-consensus scan. Every
        # nearby pair still receives the original four-coordinate test.
        buckets={}
        for i,pair in enumerate(variants[1]):
            bounds=pair['bounds_pixels']
            buckets.setdefault((bounds[0]//3,bounds[2]//3),[]).append(i)
        families=[];edges=0;width_bins={}
        for i,a in enumerate(variants[0]):
            bounds=a['bounds_pixels'];nearby=[]
            for left_bin in range((bounds[0]-2)//3,(bounds[0]+2)//3+1):
                for right_bin in range((bounds[2]-2)//3,(bounds[2]+2)//3+1):
                    checks+=1
                    if checks>max_checks:return withheld('consensus_index_lookup_budget')
                    nearby.extend(buckets.get((left_bin,right_bin),[]))
            matches=[]
            for j in sorted(nearby):
                checks+=1
                if checks>max_checks:return withheld('threshold_consensus_budget')
                if max(abs(x-y) for x,y in zip(bounds,variants[1][j]['bounds_pixels']))<=2:
                    matches.append(j)
            if not matches:continue
            family={'bounds_pixels':bounds,'first_pair_index':i,'second_pair_indices':matches}
            width_bins.setdefault(str(bounds[2]-bounds[0]),[]).append(len(families))
            families.append(family);edges+=len(matches)
        return {**base,'status':'indexed_jamb_head_correspondence_candidates_only','candidates':[],
            'checks':checks,'index':{'version':'raster-opening-index-v1',
                'variants':[{'threshold':threshold,'jamb_groups':groups,'pairs':pairs}
                    for threshold,groups,pairs in zip(THRESHOLDS,group_tables,variants)],
                'consensus_families':families,'width_bins':width_bins,'consensus_edge_count':edges,
                'expanded_consensus_preserved':True,'pixel_sampling_bound':2},
            'limitations':['Indexed families retain every supported threshold-pair correspondence within the scan recipe.',
                'Rails, textures and unrelated drafting objects can satisfy jamb/head tests; physical opening identity remains unverified.']}
    candidates=[]
    for a in variants[0]:
        for b in variants[1]:
            checks+=1
            if checks>max_checks:return withheld('threshold_consensus_budget')
            if max(abs(x-y) for x,y in zip(a['bounds_pixels'],b['bounds_pixels']))>2:continue
            bounds=a['bounds_pixels']
            candidates.append({'pair_scope':pair_scope,'bounds_pixels':bounds,'threshold_candidates':[a,b],
                'pixel_sampling_bound':2,'status':'unverified_jamb_head_correspondence',
                'physical_opening_verified':False,'opening_type':None,
                'floor_datum_verified':False})
            if len(candidates)>512:return withheld('opening_consensus_count_budget')
    return {**base,'status':'jamb_head_correspondence_candidates_only','candidates':candidates,'checks':checks,
        'limitations':['Rails, textures and unrelated rectangular drafting objects may produce candidates.',
                       'No seed trace, physical role, sill/floor datum, reveal depth or door/window type is inferred.',
                       'Threshold agreement is not confidence calibration; all competing candidates within the declared pair scope are retained.',
                       'Adjacent-compatible-jamb scope describes atomic drafting bays; it excludes spans across intermediate jambs and cannot establish full opening extent.']}


def width_candidates(scan_result,width_pixels,tolerance_pixels,charge):
    """Retrieve every consensus family in the requested width interval."""
    import math
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (width_pixels,tolerance_pixels)) or width_pixels<=0 or tolerance_pixels<0:
        raise ValueError('Finite positive indexed width and nonnegative tolerance required')
    if scan_result.get('status')!='indexed_jamb_head_correspondence_candidates_only':return []
    index=scan_result['index'];families=index['consensus_families'];bins=index['width_bins']
    if len(families)>MAX_INDEX_PAIRS or len(bins)>600:
        raise ValueError('Bounded opening index required')
    matches=[];seen=set()
    for width,indices in bins.items():
        charge();value=int(width)
        if str(value)!=width or not 1<=value<=600 or len(indices)>MAX_INDEX_PAIRS:
            raise ValueError('Valid bounded opening width bin required')
        if abs(value-width_pixels)>tolerance_pixels:continue
        for identity in indices:
            charge()
            if type(identity) is not int or not 0<=identity<len(families) or identity in seen:
                raise ValueError('Unique opening family reference required')
            family=families[identity];bounds=family['bounds_pixels']
            if bounds[2]-bounds[0]!=value:raise ValueError('Opening index width differs from source bounds')
            seen.add(identity);matches.append((identity,family))
    return sorted(matches)
