"""Audit classified survey returns near comparison outlines, without placement."""
import collections

import laspy
import numpy as np
from shapely import intersects_xy

from .point_cloud import is_bng


def audit_returns(path, references, margin_m=3, max_points=15_000_000):
    """Count native returns and eligible class-6 support inside/near each outline.

    Comparison outlines do not establish building identity. Even class-6 returns
    are classification evidence, not surveyed wall corners or accepted controls.
    """
    if not np.isfinite(margin_m) or not 0 < margin_m <= 30:
        raise ValueError('Positive bounded comparison margin required')
    if not 1 <= len(references) <= 32 or len({r['id'] for r in references}) != len(references):
        raise ValueError('Unique bounded comparison outlines required')
    for r in references:
        g=r['geometry']
        if g.geom_type not in ('Polygon','MultiPolygon') or g.is_empty or not g.is_valid or not np.isfinite(g.bounds).all():
            raise ValueError('Valid finite polygon comparison outline required')
    whole=collections.Counter();eligible=collections.Counter();scanned=0;invalid=0
    stats=[{'inside':collections.Counter(),'nearby':collections.Counter(),
            'eligible_building_inside':0,'eligible_building_nearby':0} for _ in references]
    with laspy.open(path) as reader:
        if not is_bng(reader.header.parse_crs()) or reader.header.point_count > max_points:
            raise ValueError('Native BNG crop within point budget required')
        for chunk in reader.chunk_iterator(500_000):
            scanned+=len(chunk)
            if scanned>max_points:raise ValueError('Point budget exceeded')
            x,y,z=np.asarray(chunk.x),np.asarray(chunk.y),np.asarray(chunk.z)
            finite=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
            invalid+=int(np.count_nonzero(~finite))
            labels=np.asarray(chunk.classification)
            accepted=finite&(~np.asarray(chunk.withheld,dtype=bool))&(~np.asarray(chunk.synthetic,dtype=bool))
            for target,mask in ((whole,finite),(eligible,accepted)):
                keys,counts=np.unique(labels[mask],return_counts=True)
                target.update({int(k):int(v) for k,v in zip(keys,counts)})
            for ref,row in zip(references,stats):
                inner=finite&intersects_xy(ref['geometry'],x,y)
                nearby=finite&intersects_xy(ref['geometry'].buffer(margin_m),x,y)&~inner
                for key,mask in (('inside',inner),('nearby',nearby)):
                    keys,counts=np.unique(labels[mask],return_counts=True)
                    row[key].update({int(k):int(v) for k,v in zip(keys,counts)})
                    row['eligible_building_'+key]+=int(np.count_nonzero(mask&accepted&(labels==6)))
        if scanned!=reader.header.point_count:raise ValueError('Truncated point cloud')
    landmarks=[]
    for ref,row in zip(references,stats):
        landmarks.append({'reference_id':ref['id'],'name':ref['name'],
            'inside_classifications':dict(sorted(row['inside'].items())),
            'surrounding_margin_classifications':dict(sorted(row['nearby'].items())),
            'eligible_class_6_inside':row['eligible_building_inside'],
            'eligible_class_6_in_margin':row['eligible_building_nearby'],
            'physical_identity_verified':False,'accepted_checkpoints':0})
    return {'status':'classification_evidence_only','scanned_points':scanned,
        'invalid_xyz_points':invalid,'classifications':dict(sorted(whole.items())),
        'nonwithheld_nonsynthetic_classifications':dict(sorted(eligible.items())),
        'comparison_margin_m':margin_m,'landmarks':landmarks,
        'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
        'limitations':['Mapped outlines are comparison windows, not accepted footprints',
            'Classification does not establish physical wall corners or roof-to-wall offsets',
            'Unclassified returns are not automatically treated as buildings, trees or ride supports']}
