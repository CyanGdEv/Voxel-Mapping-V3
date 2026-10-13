"""Unseeded jamb/head raster correspondences, never certified physical openings."""
import hashlib
import numpy as np

VERSION = 'raster-opening-scan-v1'
THRESHOLDS = (220, 235)


def scan(gray, *, min_height=24, min_width=20, max_width=600, max_groups=512, max_checks=100000):
    gray=np.asarray(gray)
    if gray.ndim!=2 or gray.dtype!=np.uint8 or gray.size>6000000 or max(gray.shape)>3000:
        raise ValueError('Bounded uint8 opening raster required')
    for value,limit in ((min_height,400),(min_width,600),(max_width,600),(max_groups,512),(max_checks,100000)):
        if type(value) is not int or not 1<=value<=limit:raise ValueError('Bounded opening scan options required')
    if min_width>max_width:raise ValueError('Ordered opening discovery widths required')
    base={'version':VERSION,'source_gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),
          'size_pixels':[gray.shape[1],gray.shape[0]],
          'recipe':{'thresholds':list(THRESHOLDS),'min_height_pixels':min_height,
                    'min_width_pixels':min_width,'max_groups':max_groups,'max_checks':max_checks,
                    'max_endpoint_spread_pixels':2,'minimum_head_dark_fraction':.9,
                    'maximum_width_pixels':max_width,'maximum_height_pixels':700},
          'physical_opening_verified':False,'world_geometry_additions':0}
    checks=0;variants=[]
    def withheld(reason):return {**base,'status':'scan_budget_withheld','reason':reason,'candidates':[],'checks':checks}
    for threshold in THRESHOLDS:
        dark=gray<threshold;groups=[];previous=[]
        for x in range(gray.shape[1]):
            changes=np.flatnonzero(np.diff(np.r_[False,dark[:,x],False].astype('int8')))
            current=[]
            for top,bottom in zip(changes[::2],changes[1::2]):
                if not min_height<=bottom-top<=700 or top==0 or bottom==gray.shape[0]:continue
                # Merge only adjacent columns with identical full run extents.
                # No gaps, diagonal snapping or partial-jamb extension.
                same=[g for g in previous if g['top']==top and g['bottom']==bottom]
                if len(same)==1:group=same[0];group['right']=x+1
                else:
                    group={'left':x,'right':x+1,'top':int(top),'bottom':int(bottom)};groups.append(group)
                    if len(groups)>max_groups:return withheld('vertical_run_group_budget')
                current.append(group)
            previous=current
        pairs=[];buckets={}
        for group in groups:buckets.setdefault((group['top']//3,group['bottom']//3),[]).append(group)
        for left in groups:
            nearby=[]
            for top_bin in range((left['top']-2)//3,(left['top']+2)//3+1):
                for bottom_bin in range((left['bottom']-2)//3,(left['bottom']+2)//3+1):
                    nearby.extend(buckets.get((top_bin,bottom_bin),[]))
            for right in nearby:
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
                if heads:pairs.append({'left_jamb':left.copy(),'right_jamb':right.copy(),
                    'head_support':heads,'threshold':threshold,
                    'bounds_pixels':[left['right'],top,right['left'],bottom]})
                if len(pairs)>512:return withheld('opening_pair_count_budget')
        variants.append(pairs)
    candidates=[]
    for a in variants[0]:
        for b in variants[1]:
            checks+=1
            if checks>max_checks:return withheld('threshold_consensus_budget')
            if max(abs(x-y) for x,y in zip(a['bounds_pixels'],b['bounds_pixels']))>2:continue
            bounds=a['bounds_pixels']
            candidates.append({'bounds_pixels':bounds,'threshold_candidates':[a,b],
                'pixel_sampling_bound':2,'status':'unverified_jamb_head_correspondence',
                'physical_opening_verified':False,'opening_type':None,
                'floor_datum_verified':False})
            if len(candidates)>512:return withheld('opening_consensus_count_budget')
    return {**base,'status':'jamb_head_correspondence_candidates_only','candidates':candidates,'checks':checks,
        'limitations':['Rails, textures and unrelated rectangular drafting objects may produce candidates.',
                       'No seed trace, physical role, sill/floor datum, reveal depth or door/window type is inferred.',
                       'Threshold agreement is not confidence calibration; all competing candidates are retained.']}
