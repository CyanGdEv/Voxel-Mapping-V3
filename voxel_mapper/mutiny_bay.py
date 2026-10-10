"""Mutiny Bay planning evidence, separate from registered world geometry."""
import json
from pathlib import Path

REFERENCES = {
    'SMD/2017/0472': 'courtyard', 'SMD/2017/0473': 'courtyard',
    'SMD/2007/1172': 'battle_galleons',
    'SMD/2008/0940': 'sharkbait_replacement', 'SMD/2008/0988': 'cinema_demolition',
    'SMD/2013/0012': 'lake_fencing', 'SMD/2013/0013': 'lake_fencing',
    'SMD/2013/0419': 'lake_fencing', 'SMD/2013/0420': 'lake_fencing',
}


def source_inventory(documents=None, source=None):
    """Expose all retained sources and inspected subset without approving geometry.

    Application area is not a sheet's physical boundary. Unknown drawing titles,
    dates, grid systems and proposed revisions never authorize replacement.
    """
    if source is None:
        source = json.loads((Path(__file__).parent/'data/alton-mutiny-bay-sources.json').read_text())
    retained = source['documents']
    inspected = list(documents or [])
    groups = {}
    for ref, area in REFERENCES.items():
        group = groups.setdefault(area, {'applications': [], 'documents': [],
                                         'inspected_document_urls': [], 'geometry_emitted': False})
        group['applications'].append(ref)
        group['documents'].extend(d for d in retained if d['applicationReference'] == ref)
        group['inspected_document_urls'].extend(d['url'] for d in inspected
               if d.get('applicationReference') == ref and d.get('status') == 'inspected')
    return {'area': 'Mutiny Bay', 'source_acquired_at': source['acquired_at'],
            'groups': groups, 'world_geometry_additions': 0,
            'registration_verified': False, 'as_built_verified': False,
            'alignment_status': 'awaiting_independent_existing_layout_controls',
            'correction_targets': ['courtyard footprint and entrances', 'lake edge and island/ride layout',
                                   'path widths, ramps and ground levels', 'walls, fences and material labels'],
            'limits': source['limitations'],
            'courtyard_proposal_status': 'Reported unbuilt restaurant scheme; proposed drawings are not current-state evidence',
            'courtyard_proposal_status_source': 'https://www.towerstimes.co.uk/history/the-drawing-board/mutiny-bay-courtyard-restaurant/'}
