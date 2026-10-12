"""Source-line brackets for open passages; no synthesized opening polygons."""
import re
from shapely.geometry import shape
from .drawing_components import split_page

VERSION='archway-source-boundary-brackets-v1'


def review(parents,references,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:
        raise ValueError('Bounded archway boundary checks required')
    if len(references)>1 or sum(len(r['reference_occurrences']) for r in references)>500:
        raise ValueError('Single bounded reference page required')
    components=split_page(parents)
    source={(r['document_sha256'],r['page']) for r in components}
    if any((r['document_sha256'],r['page']) not in source for r in references):
        raise ValueError('References must share the original source page')
    lines=[]
    for row in components:
        if (row['geometry']['type']!='LineString' or len(row['geometry']['coordinates'])!=2
                or row.get('curve_approximation',{}).get('cubic_segments')
                or row.get('paint_reference_truncated') or not row.get('paint_references')
                or any(not isinstance(p['stroke_style'].get('dashes_pdf'),str)
                    or not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf'])
                    for p in row['paint_references'])):continue
        a,b=row['geometry']['coordinates']
        for axis in (0,1):
            if abs(a[axis]-b[axis])<=1e-5 and abs(a[1-axis]-b[1-axis])>1e-5:
                lines.append((row,axis,(a[axis]+b[axis])/2,sorted((a[1-axis],b[1-axis]))))
    checks=0;results=[]
    for reference in references:
        for occurrence,row in enumerate(reference['reference_occurrences']):
            if not row['reference_id'].startswith('archway:') or row['glyph_screen']['status']!='raster_consistent_candidate':continue
            bounds=shape(row['label_geometry']).bounds; pairs=[]
            for axis in (0,1):
                low=[];high=[]
                for line,direction,offset,span in lines:
                    checks+=1
                    if checks>max_checks:return {'version':VERSION,'status':'boundary_budget_withheld','references':[],
                        'checks':checks,'world_geometry_additions':0}
                    if direction!=axis or span[0]>bounds[1-axis] or span[1]<bounds[3-axis]:continue
                    if offset<bounds[axis]:low.append(line)
                    if offset>bounds[axis+2]:high.append(line)
                for first in low:
                    for second in high:
                        checks+=1
                        if checks>max_checks:return {'version':VERSION,'status':'boundary_budget_withheld','references':[],
                            'checks':checks,'world_geometry_additions':0}
                        pairs.append({'normal_axis':'x' if axis==0 else 'y',
                            'source_boundaries':[{'component_id':r['id'],'geometry':r['geometry'],
                                'component_contract':r['extraction_contract'],'parent_references':r['parent_references']}
                                for r in (first,second)]})
            pairs.sort(key=lambda p:(p['normal_axis'],[r['component_id'] for r in p['source_boundaries']]))
            results.append({'reference_id':row['reference_id'],'occurrence_index':occurrence,'boundary_pairs':pairs,
                'status':'source_brackets_only','physical_opening_verified':False,'coordinate_control_verified':False})
    return {'version':VERSION,'status':'source_brackets_only','references':results,'checks':checks,
        'world_geometry_additions':0,'limitations':['Every solid axis-aligned pair spanning and bracketing the full label is retained.',
            'Distant walls and internal details may bracket the label; no pair is selected as a passage boundary.',
            'Dashed ends, rotated boundaries, height, scale and geographic placement remain unresolved.']}
