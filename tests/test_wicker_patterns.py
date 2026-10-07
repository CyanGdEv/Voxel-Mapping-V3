import unittest

import numpy as np

from voxel_mapper.wicker_patterns import pattern_identity, painted_patterns, flatten_cubic


class PDFObject(dict):
    def __init__(self,data=b'',**values):
        super().__init__(values);self.data=data
    def get_object(self):return self
    def get_data(self):return self.data


class PatternTests(unittest.TestCase):
    def tile(self,data=b'one',palette='brown'):
        image=PDFObject(data,**{'/Subtype':'/Image','/Width':8,'/Height':8,'/ColorSpace':palette})
        return PDFObject(b'/Im0 Do',**{'/PatternType':1,'/PaintType':1,'/BBox':[0,0,8,8],
                                    '/XStep':8,'/YStep':8,'/Resources':{'/XObject':{'/Im0':image}}})

    def test_identical_operators_with_different_image_or_palette_are_not_same_hatch(self):
        identity=pattern_identity(self.tile())
        self.assertEqual(identity,pattern_identity(self.tile()))
        self.assertNotEqual(identity,pattern_identity(self.tile(b'two')))
        self.assertNotEqual(identity,pattern_identity(self.tile(palette='green')))

    def test_even_odd_pattern_holes_and_graphics_scope_are_preserved(self):
        ops=[([],b'q'),(['/Pattern'],b'cs'),(['/P1'],b'scn'),
             ([0,0,10,10],b're'),([2,2,5,5],b're'),([],b'f*'),([],b'Q'),
             ([20,20,10,10],b're'),([],b'f*')]
        paths=painted_patterns(ops,{'/P1':'new-paving'},100)
        self.assertEqual(len(paths),1)
        self.assertEqual(paths[0]['polygon'].area,75)
        self.assertEqual(len(paths[0]['polygon'].interiors),1)
        self.assertEqual(paths[0]['polygon'].bounds,(0,90,10,100))

    def test_pattern_respects_clip_instead_of_painting_entire_bounds(self):
        ops=[([0,0,5,5],b're'),([],b'W*'),([],b'n'),
             (['/Pattern'],b'cs'),(['/P1'],b'scn'),([0,0,10,10],b're'),([],b'f*')]
        paths=painted_patterns(ops,{'/P1':'new-paving'},100)
        self.assertEqual(paths[0]['polygon'].area,25)
        with self.assertRaises(ValueError):painted_patterns(ops,{'/P1':'new-paving'},100,max_operations=1)

    def test_curve_footprint_does_not_collapse_to_a_straight_chord(self):
        points=flatten_cubic(np.array([0.,0]),np.array([0.,10]),np.array([10.,10]),np.array([10.,0]))
        self.assertGreater(len(points),4)
        self.assertGreater(max(p[1] for p in points),7)
        self.assertEqual(points[-1],[10,0])


if __name__=='__main__':unittest.main()
