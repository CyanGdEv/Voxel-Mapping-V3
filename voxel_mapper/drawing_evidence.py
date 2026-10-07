"""Bounded textual evidence candidates; never infer placement or construction."""
import re

LEVEL = re.compile(r'\b(?P<label>FFL|finished floor level|lake\s*bed level|bed level|water level|ground level|ridge level|eaves level)\s*[:=]?\s*(?P<value>[+-]?\d{1,3}(?:\.\d{1,3})?)(?![\d.:eE])(?!\s*(?:ft|feet|inches|in)\b)\s*(?P<unit>m\b)?\s*(?P<datum>AOD|ODN|mOD)?',re.I)
MATERIALS = {'resin bound gravel':'resin_bound_gravel','block paving':'paving_stones',
             'paving stones':'paving_stones','asphalt':'asphalt','concrete':'concrete',
             'brick':'brick','timber':'wood','wood':'wood','steel':'steel','gravel':'gravel'}
COLOURS = re.compile(r'\b(white|orange|magenta|light blue|yellow|lime|pink|light gr[ae]y|gr[ae]y|cyan|purple|blue|brown|green|red|black)\b',re.I)


def evidence_candidates(text, max_candidates=100, *, material_context=False):
    if len(text)>500_000 or max_candidates<1:
        raise ValueError('Drawing text/candidate budget exceeded')
    levels,materials=[],[]
    seen=set()
    truncated=False
    for index,line in enumerate(text.splitlines(),1):
        if len(line)>2000:
            truncated=True
            continue
        state='proposed' if re.search(r'\bproposed\b',line,re.I) else 'existing_label_unverified' if re.search(r'\bexisting\b',line,re.I) else 'unknown'
        candidates=[]
        for match in LEVEL.finditer(line):
            candidates.append(('level',{'label':match['label'].lower(),'value_candidate':float(match['value']),
                                      'unit_label_candidate':match['unit'],
                                      'datum_label_candidate':match['datum'].upper() if match['datum'] else None}))
        if material_context or re.search(r'\b(surface|paving|path|walkway|plaza|finish|material|boardwalk|deck)\b',line,re.I):
            for phrase,material in MATERIALS.items():
                if re.search(r'\b'+re.escape(phrase)+r'\b',line,re.I):
                    # Do not collapse a mixed specification into one block choice.
                    candidates.append(('material',{'material_candidate':material,
                        'colour_candidates':sorted(set(c.lower().replace('grey','gray') for c in COLOURS.findall(line)))}))
        for kind,candidate in candidates:
            key=(kind,str(candidate),state)
            if key in seen:
                continue
            if len(levels)+len(materials)>=max_candidates:
                truncated=True
                continue
            seen.add(key)
            (levels if kind=='level' else materials).append({**candidate,'line_number':index,
                'construction_label':state,'association_status':'unplaced_unverified'})
    return {'status':'text_candidates_only','levels':levels,'materials':materials,'truncated':truncated,
            'limitations':['Text labels are not verified measurements, polygon associations or as-built evidence',
                           'AOD/mOD labels do not establish a specific vertical datum',
                           'Materials/colours are candidates; mixed specifications remain separate',
                           'No raw text, coordinates or reconstructed geometry exported']}


def document_category(title):
    if re.search(r'material|finish|surface|paving',title,re.I):
        return 'materials'
    if re.search(r'bathym|flood|water|drainage',title,re.I):
        return 'water_and_levels'
    if re.search(r'elevation|section',title,re.I):
        return 'elevations'
    if re.search(r'survey|topograph',title,re.I):
        return 'surveys'
    return 'plans'


def inspection_order(documents):
    groups={key:[] for key in ('plans','elevations','materials','surveys','water_and_levels')}
    for document in sorted(documents,key=lambda d:(not bool(re.search(r'site|location',d['title'],re.I)),d['application_reference'],d['id'])):
        groups[document_category(document['title'])].append(document)
    ordered=[]
    for i in range(max((len(g) for g in groups.values()),default=0)):
        ordered.extend(g[i] for g in groups.values() if i<len(g))
    return ordered
