"""Survey reference notes are evidence candidates, never registration authority."""
import re


def inspect_reference_notes(text):
    if len(text.encode('utf-8')) > 8_000_000:
        raise ValueError('Survey reference text budget exceeded')
    # A blank line is a withheld OCR line. Never join across it.
    passages = [re.sub(r'\s+', ' ', part).upper()
                for part in re.split(r'\n\s*\n', text)]
    epsgs = sorted({int(code) for part in passages
                    for code in re.findall(r'\bEPSG\s*[:=]?\s*(\d{4,6})\b', part)})
    national = any(re.search(r'\bSURVEY GRID (?:IS )?RELATED TO (?:THE )?NATIONAL GRID\b', p)
                   for p in passages)
    resection = national and any('RESECTION' in p and 'NATIONAL GRID' in p for p in passages)
    no_scale = any(re.search(r'NO ADJUSTMENTS? FOR SCALE FACTOR (?:HAVE|HAS) BEEN APPLIED', p)
                   for p in passages)
    metres = any(re.search(r'\bALL LEVELS ARE IN METRES\b', p) for p in passages)
    benchmark = any(re.search(r'\bLEVELS ARE IN METRES RELATED TO AN? O\.?\s*S\.?\s*B\.?\s*M\.?', p)
                    for p in passages)
    explicit_odn = any(re.search(r'\b(?:LEVELS|HEIGHTS) (?:ARE )?(?:IN METRES )?(?:RELATED|REFERENCED) TO ORDNANCE DATUM NEWLYN\b', p)
                       for p in passages)
    external = sorted({(m[1], m[2]) for p in passages for m in re.finditer(
        r'\bSURVEYS? DRAWING\s*:?\s*(\d{3,8})\s+(MASTER LAND SURVEY)\b', p)})
    return {'status': 'reference_notes_candidates_only',
            'explicit_epsg_candidates': epsgs,
            'national_grid_claim': national,
            'mapping_resection_claim': resection,
            'scale_factor_not_applied_claim': no_scale,
            'height_units_candidate': 'metres' if metres else None,
            'os_benchmark_reference_claim': benchmark,
            'height_datum_candidate': 'ODN' if explicit_odn else None,
            'external_drawing_references': [{'drawing_number': number, 'title': title,
                                             'status': 'referenced_not_acquired'} for number, title in external],
            'registration_verified': False, 'vertical_datum_verified': False,
            'world_geometry_additions': 0,
            'limitations': ['National Grid wording alone does not establish EPSG:27700',
                           'An OS benchmark reference alone does not establish ODN or its current value',
                           'Printed statements require source and independent alignment verification']}
