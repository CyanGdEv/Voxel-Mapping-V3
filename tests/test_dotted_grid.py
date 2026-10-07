import unittest
from voxel_mapper.dotted_grid import reconstruct_dotted_lines, inspect_dotted_grid
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject


class DottedGridTests(unittest.TestCase):
    def test_actual_pdf_transform_and_private_inspection(self):
        page=PdfWriter().add_blank_page(500,500)
        commands=['q 1 0 0 1 10 10 cm']
        for i in range(40):
            commands.extend([f'20 {4*i} m 20 {4*i+1} l S',f'{4*i} 30 m {4*i+1} 30 l S'])
        commands.append('Q')
        stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode())
        page[NameObject('/Contents')]=stream
        result=inspect_dotted_grid(page)
        self.assertEqual(result['candidate_count'],2)
        self.assertFalse(result['controls_exported'])
        self.assertFalse(result['registration_verified'])
        self.assertNotIn('lines',result)

    def segments(self):
        return [[(20,4*i),(20,4*i+1)] for i in range(40)]

    def test_periodic_strokes_reconstruct_bounded_hypothesis(self):
        result=reconstruct_dotted_lines(self.segments())
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['extent'],[0,157])
        self.assertEqual(result[0]['axis'],'vertical')

    def test_missing_irregular_overlapping_and_slanted_strokes_are_withheld(self):
        self.assertEqual(reconstruct_dotted_lines(self.segments()[:20]+self.segments()[21:]),[])
        self.assertEqual(reconstruct_dotted_lines([[(i,4*i),(i+.5,4*i+1)] for i in range(40)]),[])
        self.assertEqual(reconstruct_dotted_lines([[(0,i),(0,i+2)] for i in range(120)]),[])

    def test_budgets_and_nonfinite_input(self):
        with self.assertRaisesRegex(ValueError,'budget'):reconstruct_dotted_lines(self.segments(),max_segments=2)
        with self.assertRaisesRegex(ValueError,'Finite'):reconstruct_dotted_lines([[(0,0),(0,float('nan'))]])

    def test_missing_dash_splits_long_runs_without_bridging(self):
        segments=[[(0,4*i),(0,4*i+1)] for i in range(81) if i!=40]
        result=reconstruct_dotted_lines(segments)
        self.assertEqual([r['extent'] for r in result],[[0,157],[164,321]])
