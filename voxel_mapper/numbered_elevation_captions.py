"""Exact numbered cardinal/intercardinal captions; no bearing registration."""
import re


def parse(text):
    if not isinstance(text, str) or len(text) > 500:
        return None
    value = re.sub(r'\s+', '', text.lower())
    match = re.fullmatch(r'elevation([1-9]\d{0,2})to(?:the)?'
        r'(north|south|east|west|[ns]\.?(?:east|west))'
        r'(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?', value)
    if not match:
        return None
    scale = int(match[4]) if match[4] else None
    if scale is not None and not 1 <= scale <= 10000:
        return None
    direction = match[2].replace('.', '')
    direction = {'neast': 'northeast', 'nwest': 'northwest',
        'seast': 'southeast', 'swest': 'southwest'}.get(direction, direction)
    bearing = {'north': 'N', 'south': 'S', 'east': 'E', 'west': 'W',
        'northeast': 'NE', 'northwest': 'NW', 'southeast': 'SE', 'southwest': 'SW'}[direction]
    return {'view_number': int(match[1]), 'direction': direction, 'bearing': bearing,
        'printed_state': match[3] or 'unspecified', 'printed_scale_denominator': scale}
