import unittest
from voxel_mapper.wicker_reconstruction import connected_paving


class PlazaConnectionTests(unittest.TestCase):
    def test_sloping_paving_connects(self):
        cells = {(0,0):180,(1,0):181,(2,0):181,(2,1):180}
        self.assertEqual(connected_paving(cells,(0,0)),set(cells))

    def test_gap_and_diagonal_contact_do_not_connect(self):
        cells = {(0,0):180,(1,1):180,(2,0):180}
        self.assertEqual(connected_paving(cells,(0,0)),{(0,0)})

    def test_cliff_blocks_connection(self):
        cells = {(0,0):180,(1,0):182,(2,0):182}
        self.assertEqual(connected_paving(cells,(0,0)),{(0,0)})

    def test_missing_start_is_not_connected(self):
        self.assertEqual(connected_paving({(0,0):180},(1,0)),set())
