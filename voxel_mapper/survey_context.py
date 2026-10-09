"""Survey coordinate restrictions; OS-related wording alone is not a CRS proof."""
import re

VERSION='survey-context-v1'
RULES={
    'arbitrary_coordinates':r'\bcoordinates\s+(?:shown\s+)?are\s+arbitrary\b',
    'not_true_os_coordinates':r'\bnot\s+true\s+(?:OS|Ordnance\s+Survey)\s+coordinates\b',
    'no_scale_factor_applied':r'\bno\s+scale\s+factor\s+has\s+been\s+applied\b',
    'local_grid':r'\b(?:local|on[- ]site|arbitrary)\s+(?:coordinate\s+)?grid\b',
}


def inspect_survey_context(text):
    if not isinstance(text,str) or len(text)>500000:raise ValueError('Bounded native survey text required')
    normalized=re.sub(r'\s+',' ',text)
    flags=[name for name,pattern in RULES.items() if re.search(pattern,normalized,re.I)]
    declared=bool(re.search(r'\b(?:OSGB\s*36|OSTN15|OS\s+national\s+grid|EPSG\s*[:=]?\s*27700)\b',normalized,re.I))
    return {'version':VERSION,'restriction_flags':flags,'national_grid_mentioned':declared,'coordinate_use':'local_or_restricted_grid' if flags else 'national_grid_declaration_only' if declared else 'coordinate_system_unestablished','direct_national_grid_registration_eligible':False,'registration_verified':False,'world_geometry_additions':0}
