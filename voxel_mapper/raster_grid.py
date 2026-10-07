"""OCR border-label layout checks, separate from geographic registration."""
import csv
import io
import math
import re

import numpy as np

LABEL = re.compile(r'^(\d{6})([EN])$', re.I)


def provisional_word_boxes(tsv, edge, crop_box, rotation):
    """Find coordinate-shaped words for rereading, never accepted controls."""
    if len(tsv.encode()) > 8_000_000 or edge not in ('top','bottom','left','right') or rotation not in (0,90):
        raise ValueError('Invalid provisional OCR budget or orientation')
    left,top,right,bottom = map(float,crop_box)
    if not all(math.isfinite(v) for v in (left,top,right,bottom)) or right<=left or bottom<=top:
        raise ValueError('Invalid provisional crop')
    width,height = right-left,bottom-top
    output=[]
    for i,row in enumerate(csv.DictReader(io.StringIO(tsv),delimiter='\t',quoting=csv.QUOTE_NONE)):
        if i>20_000:
            raise ValueError('Provisional OCR word budget exceeded')
        if row.get('level')!='5' or not re.fullmatch(r'\d{6}[A-Za-z0-9]?',row.get('text','').strip()):
            continue
        x,y,w,h = (float(row[k]) for k in ('left','top','width','height'))
        rw,rh = (height,width) if rotation==90 else (width,height)
        if not all(math.isfinite(v) for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0 or x+w>rw or y+h>rh:
            raise ValueError('Provisional word outside crop')
        box = (left+width-y-h,top+x,left+width-y,top+x+w) if rotation==90 else (left+x,top+y,left+x+w,top+y+h)
        output.append({'page_pixel_box':box,'first_pass_text':row['text']})
        if len(output)>64:
            raise ValueError('Provisional coordinate budget exceeded')
    return output


def edge_labels(tsv, edge, crop_box, rotation, scale=3, min_confidence=70):
    """Invert crop/quarter-turn coordinates; never repair misread digits."""
    if edge not in ('top', 'bottom', 'left', 'right') or rotation not in (0, 90):
        raise ValueError('Unsupported OCR edge or rotation')
    if not 1 <= scale <= 3 or len(tsv.encode()) > 8_000_000:
        raise ValueError('Edge OCR size budget exceeded')
    left, top, right, bottom = map(float, crop_box)
    if not all(math.isfinite(v) for v in (left, top, right, bottom)) or right <= left or bottom <= top:
        raise ValueError('Invalid edge crop')
    image_width, image_height = (right-left)*scale, (bottom-top)*scale
    if rotation == 90:
        image_width, image_height = image_height, image_width
    labels = []
    words = 0
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row.get('level') != '5':
            continue
        words += 1
        if words > 20_000:
            raise ValueError('Edge OCR word budget exceeded')
        match = LABEL.fullmatch(row.get('text', '').strip())
        if not match:
            continue
        confidence = float(row['conf'])
        if not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError('Invalid coordinate OCR confidence')
        if confidence < min_confidence:
            continue
        axis = match[2].upper()
        if (axis == 'E') != (edge in ('top', 'bottom')):
            continue
        x, y, width, height = (float(row[k]) for k in ('left', 'top', 'width', 'height'))
        if not all(math.isfinite(v) for v in (x,y,width,height)) or min(x,y) < 0 or min(width,height) <= 0 or x+width > image_width or y+height > image_height:
            raise ValueError('Coordinate label outside rendered edge')
        x, y = (x+width/2)/scale, (y+height/2)/scale
        if rotation == 90:
            x, y = right-left-y, x
        labels.append({'axis': axis, 'value': int(match[1]),
                       'pixel_position': left+x if axis == 'E' else top+y,
                       'confidence': confidence, 'edge': edge})
        if len(labels) > 64:
            raise ValueError('Coordinate label budget exceeded')
    return labels


def inspect_label_layout(labels, max_error=0.5):
    """Fit held-out labels only; constant text offsets remain untestable."""
    result = {'status': 'insufficient_axis_labels', 'world_geometry_additions': 0,
              'geographic_registration': 'not_established', 'axis_checks': {},
              'limitations': ['OCR label centres are not surveyed grid intersections',
                             'Axis fit does not verify CRS, datum, label attachment or absolute position',
                             'No coordinates, controls, transforms or polygons exported']}
    if len(labels) > 64 or not math.isfinite(max_error) or max_error <= 0:
        raise ValueError('Invalid grid label budget/tolerance')
    for label in labels:
        if label.get('axis') not in ('E','N') or not all(math.isfinite(float(label[k])) for k in ('value','pixel_position')):
            raise ValueError('Invalid coordinate label')
    for axis in ('E', 'N'):
        group = [label for label in labels if label['axis'] == axis]
        values = {label['value'] for label in group}
        check = {'label_count':len(group), 'distinct_coordinate_count':len(values),
                 'status':'insufficient_distinct_coordinates'}
        result['axis_checks'][axis] = check
        if len(values) < 3:
            continue
        # Duplicate values on opposite borders do not add independent controls.
        positions = np.array([np.mean([label['pixel_position'] for label in group if label['value']==value])
                              for value in sorted(values)])
        coordinates = np.array(sorted(values), dtype=float)
        if not np.all(np.isfinite(positions)) or np.ptp(positions) < 50 or np.ptp(coordinates) > 20_000:
            check['status'] = 'rejected_extent'; continue
        design = np.column_stack([positions-positions.mean(), np.ones(len(positions))])
        errors = []
        for i in range(len(positions)):
            training = np.delete(design,i,axis=0)
            if np.linalg.matrix_rank(training) != 2:
                break
            fit = np.linalg.lstsq(training,np.delete(coordinates,i),rcond=None)[0]
            errors.append(abs(float(design[i]@fit-coordinates[i])))
        fit = np.linalg.lstsq(design, coordinates, rcond=None)[0]
        duplicate_error = max(abs(float((label['pixel_position']-positions.mean())*fit[0]+fit[1]-label['value'])) for label in group)
        orientation = fit[0] > 0 if axis == 'E' else fit[0] < 0
        check.update(max_withheld_error_coordinate_units=max(errors,default=None),
                     max_individual_error_coordinate_units=duplicate_error)
        check['status'] = ('consistent_label_layout_unverified' if len(errors)==len(positions) and
                           orientation and max(errors)<=max_error and duplicate_error<=max_error
                           else 'rejected_label_layout')
    if all(c['status']=='consistent_label_layout_unverified' for c in result['axis_checks'].values()):
        result['status'] = 'consistent_label_layout_unverified'
    elif any(c['status'].startswith('rejected') for c in result['axis_checks'].values()):
        result['status'] = 'rejected_label_layout'
    return result
