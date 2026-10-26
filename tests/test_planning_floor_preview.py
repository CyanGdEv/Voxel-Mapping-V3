"""Conditional floors keep source levels explicit and grading is bounded."""
from concurrent.futures import CancelledError
import copy
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import box,mapping
from voxel_mapper import planning_floor_preview as floor,planning_surface_audit as audit


class FloorPreviewTests(unittest.TestCase):
    def test_floor_block_top_does_not_add_one_to_printed_ffl(self):
        buildings={'records':[{'id':'shop','geometry_pdf_native':mapping(box(0,0,2,2))}]}
        claims=[{'source_building_ids':['shop'],'printed_level_m':182.5,'building_labels':['Shop']}]
        cells,report=floor.floor_cells(claims,buildings,{(x,y):180 for x in range(2) for y in range(2)},1)
        self.assertEqual(len(cells),4);self.assertEqual({r['base_odn_block_m'] for r in cells.values()},{181})
        self.assertEqual(report[0]['preview_floor_top_odn_assumption_m'],182)
        self.assertEqual(report[0]['quantization_error_m'],-.5);self.assertFalse(report[0]['datum_verified'])

    def test_same_ffl_overlap_keeps_both_sources_and_different_levels_fail(self):
        buildings={'records':[{'id':'a','geometry_pdf_native':mapping(box(0,0,2,2))},{'id':'b','geometry_pdf_native':mapping(box(1,0,3,2))}]}
        claims=[{'source_building_ids':[k],'printed_level_m':183.25,'building_labels':[k]} for k in ['a','b']]
        heights={(x,y):180 for x in range(3) for y in range(2)};cells,report=floor.floor_cells(claims,buildings,heights,1)
        self.assertEqual(len(cells),6);self.assertEqual(cells[1,0]['source_building_ids'],['a','b'])
        self.assertEqual(sum(len(r['source_building_ids'])>1 for r in cells.values()),2)
        changed=copy.deepcopy(claims);changed[1]['printed_level_m']=183.75
        with self.assertRaises(ValueError):floor.floor_cells(changed,buildings,heights,1)

    def test_minimum_cut_fill_proposal_repairs_steps_without_changing_input(self):
        heights={(0,0):180,(1,0):182,(2,0):183,(99,99):185};before=dict(heights);cells={(0,0),(1,0),(2,0)}
        changes=floor.grade_paths(cells,heights)
        self.assertEqual(changes,{(0,0):181});self.assertEqual(heights,before)
        after={**heights,**changes};review=audit.path_steps(cells,after,[1,0,0,1,0,0])
        self.assertEqual(review['multi_block_step_pairs'],0);self.assertNotIn((99,99),changes)
        self.assertEqual(floor.grade_paths(cells,after),{})

    def test_excessive_cuts_missing_coverage_and_cancel_fail_without_mutation(self):
        heights={(0,0):180,(1,0):184};before=dict(heights)
        with self.assertRaises(ValueError):floor.grade_paths(set(heights),heights)
        with self.assertRaises(CancelledError):floor.grade_paths(set(heights),heights,cancelled=lambda:True)
        with self.assertRaises(ValueError):floor.grade_paths({(0,0),(2,0)},heights)
        self.assertEqual(heights,before)

    def test_datum_assumption_is_never_enabled_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'world'
            with self.assertRaises(ValueError):floor.run({},'missing','missing.pdf',output)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
