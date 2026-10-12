import unittest
from pypdf.generic import DecodedStreamObject, NameObject
from tests.test_drawing_controls import fixture
from voxel_mapper.drawing_marks import extract_marks, mark_for_label
from voxel_mapper.drawing_controls import inspect_coordinate_labels


def marked_fixture(ambiguous=False):
    page=fixture()
    commands=['BT /F1 8 Tf 1 0 0 1 10 10 Tm (EPSG: 32630) Tj ET']
    for i,(x,y) in enumerate([(100,100),(100,500),(500,500),(500,100)]):
        tx,ty=x+20+i*5,y+20
        commands.extend([f'{x-4} {y} m {x+4} {y} l S',f'{x} {y-4} m {x} {y+4} l S',
            f'{tx} {ty} m {x} {y} l S',
            f'BT /F1 8 Tf 1 0 0 1 {tx} {ty} Tm (E: {500000+x}; N: {5700000+y}) Tj ET'])
    if ambiguous:
        commands.append('120 120 m 100 500 l S')
    stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode())
    page[NameObject('/Contents')]=stream
    return page


class MarkTests(unittest.TestCase):
    def test_crosshairs_not_text_origins_drive_candidate_fit(self):
        page=marked_fixture()
        marks=extract_marks(page,reuse_allowed=True)
        self.assertEqual(len(marks['marks']),4)
        self.assertEqual(mark_for_label(marks,[120,120]),[100,100])
        self.assertIsNone(mark_for_label(marks,[101,101]))
        result=inspect_coordinate_labels(page,reuse_allowed=True,require_marks=True)
        self.assertEqual(result['status'],'candidate_alignment')
        self.assertLess(result['viewports'][0]['max_withheld_error_m'],.1)
        self.assertEqual(result['registration_method'],'leader_connected_crosshair_candidates')
        self.assertEqual(result['independent_accuracy'],'not_verified')
        self.assertEqual(inspect_coordinate_labels(page,reuse_allowed=True)['status'],'rejected')

    def test_ambiguous_missing_and_unsupported_marks_have_no_fallback(self):
        for page in (marked_fixture(True),fixture()):
            result=inspect_coordinate_labels(page,reuse_allowed=True,require_marks=True)
            self.assertEqual(result['status'],'rejected')
            self.assertEqual(result['viewports'],[])
        self.assertEqual(extract_marks(marked_fixture())['status'],'blocked_reuse')
        self.assertNotEqual(extract_marks(marked_fixture(),reuse_allowed=True,max_segments=1)['status'],'crosshair_candidates')
        page=marked_fixture()
        stream=DecodedStreamObject();stream.set_data(page.get_contents().get_data()+b'\n0 0 m 1 1 2 2 3 3 c S')
        page[NameObject('/Contents')]=stream
        self.assertEqual(inspect_coordinate_labels(page,reuse_allowed=True,require_marks=True)['status'],'rejected')
