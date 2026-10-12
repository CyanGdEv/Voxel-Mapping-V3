"""Historical OS archive corroboration candidates; never surveyed control acceptance."""
import csv
from decimal import Decimal
import math
from pathlib import Path
import re
from .generation_cycles import file_hash
from .reconstruction_evidence_queue import digest

VERSION='os-benchmark-archive-matching-v1'
SOURCE_URL='https://www.ordnancesurvey.co.uk/documents/resources/CompleteBenchMarkArchive.zip'


def grid_position(letters,east,north):
    if not re.fullmatch('[A-HJ-Z]{2}',letters) or not re.fullmatch(r'\d{1,5}',east) or not re.fullmatch(r'\d{1,5}',north) or len(east)!=len(north):
        raise ValueError('Bounded original National Grid reference required')
    a,b=[ord(c)-ord('A')-(c>'I') for c in letters]
    e=((a-2)%5)*5+b%5;n=19-(a//5)*5-b//5
    if not 0<=e<=6 or not 0<=n<=12:raise ValueError('British National Grid square required')
    resolution=10**(5-len(east))
    return [e*100000+int(east)*resolution,n*100000+int(north)*resolution],resolution


def review(benchmark_reviews,archive,archive_sha256,search_bounds,*,max_rows=1000000,max_candidates=1000):
    archive=Path(archive)
    if not re.fullmatch('[0-9a-f]{64}',archive_sha256) or file_hash(archive)!=archive_sha256:
        raise ValueError('Pinned official benchmark archive required')
    if (not isinstance(search_bounds,list) or len(search_bounds)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in search_bounds)
            or not search_bounds[0]<search_bounds[2] or not search_bounds[1]<search_bounds[3]):
        raise ValueError('Ordered finite benchmark search bounds required')
    if type(max_rows) is not int or not 1<=max_rows<=1000000 or type(max_candidates) is not int or not 1<=max_candidates<=10000:
        raise ValueError('Bounded benchmark archive budgets required')
    nearby=[];scanned=0;exhausted=False
    with archive.open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        if not {'NG LETTERS','EASTING','NORTHING','HEIGHT','DATUM','DESCRIPTION'}<=set(reader.fieldnames or []):
            raise ValueError('Original benchmark archive columns required')
        for scanned,row in enumerate(reader,1):
            if scanned>max_rows:exhausted=True;break
            # The archive also contains outlying grids and incomplete references.
            try:position,resolution=grid_position(row['NG LETTERS'],row['EASTING'],row['NORTHING'])
            except ValueError:continue
            if not (search_bounds[0]<=position[0]<=search_bounds[2] and search_bounds[1]<=position[1]<=search_bounds[3]):continue
            if len(nearby)>=max_candidates:exhausted=True;break
            height=Decimal(row['HEIGHT'].strip())
            if not height.is_finite():raise ValueError('Finite archive benchmark height required')
            nearby.append({'id':digest(row),'original_archive_row':row,'position_bng':position,
                'grid_reference_resolution_m':resolution,'position_accuracy_verified':False,
                'archive_line_number':scanned+1,'archive_sha256':archive_sha256})
    links=[]
    if not exhausted:
        for source in benchmark_reviews:
            if source['status']!='printed_benchmark_layout_evidence_only':continue
            values={v['id']:v for v in source['printed_values']}
            for layout in source['layout_links']:
                if layout['status']!='one_visible_printed_value_layout_candidate':continue
                value=values[layout['visible_candidate_value_ids'][0]]
                # Recover precision from the literal source value, never from a float.
                match=re.fullmatch(r'\(\s*value\s+([+-]?\d+(?:\.\d+)?)\s*(m|mm)\s*\)',value['text'],re.I)
                if not match:raise ValueError('Original literal benchmark value required')
                printed=Decimal(match[1]);unit=Decimal('.001') if match[2].lower()=='mm' else Decimal(1)
                centre=printed*unit;half=Decimal(5).scaleb(printed.as_tuple().exponent-1)*unit
                matches=[r for r in nearby if abs(Decimal(r['original_archive_row']['HEIGHT'].strip())-centre)<=half]
                links.append({'document_sha256':source['document_sha256'],'page':source['page'],
                    'source_benchmark_review_sha256':digest(source),'marker_id':layout['marker_id'],'value_id':value['id'],
                    'printed_height_m':str(centre),'printed_rounding_half_interval_m':str(half),
                    'candidate_archive_ids':sorted(r['id'] for r in matches),
                    'status':'one_height_consistent_archive_candidate' if len(matches)==1 else 'missing_or_competing_archive_candidates',
                    'physical_benchmark_identity_verified':False,'vertical_datum_verified':False,'coordinate_control_verified':False})
    if exhausted:nearby=[];links=[]
    if file_hash(archive)!=archive_sha256:raise ValueError('Archive changed during benchmark review')
    return {'version':VERSION,'status':'archive_budget_withheld' if exhausted else 'historical_benchmark_corroboration_only',
        'archive_source_url':SOURCE_URL,'archive_sha256':archive_sha256,'source_review_sha256':digest(benchmark_reviews),
        'search_bounds_bng':search_bounds,'nearby_archive_records':sorted(nearby,key=lambda r:r['id']),
        'links':links,'rows_examined':scanned,'world_geometry_additions':0,
        'vertical_datum_verified':False,'coordinate_control_verified':False,
        'limitations':['Equal printed height and nearby location do not establish physical benchmark identity.',
            'Search bounds are a discovery domain, not an accepted area boundary or registration.',
            'Archive grid-reference precision is not survey accuracy; old marks may have moved or been destroyed.',
            'No archive match becomes a control, transforms source geometry or assigns an absolute building level.']}
