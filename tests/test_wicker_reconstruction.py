import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import amulet
from voxel_mapper.wicker_reconstruction import preview_profile, verify_preview, local_height_bindings
from voxel_mapper.bedrock import export_world


class ReconstructionTests(unittest.TestCase):
    def test_profile_preserves_reviewed_extrema_without_overshoot_or_seam(self):
        bindings = [{'status':'reviewed_plan_marker_binding','nearest_candidate':{'station_m':s},'printed_level_m':h}
                    for s,h in [(2,180),(12,201),(22,185)]]
        route={'route_length_m':30}
        np.testing.assert_allclose(preview_profile(route,bindings,[2,12,22]),[180,201,185])
        values=preview_profile(route,bindings,np.arange(0,30,.01))
        self.assertGreaterEqual(values.min(),180)
        self.assertLessEqual(values.max(),201)
        for s in [0,2,12,22,30]:
            left,centre,right=preview_profile(route,bindings,[s-.0001,s,s+.0001])
            self.assertLess(abs(left-right),.001)
            if s in [2,12,22]:
                self.assertLess(abs(right-centre)/.0001,.001)
        with self.assertRaises(ValueError):preview_profile(route,bindings,[float('nan')])

    def test_height_station_uses_corresponding_local_segment_fraction(self):
        association={'bindings':[{'nearest_candidate':{'segment_index':1,'segment_fraction':.25,'station_m':999}}]}
        route={'segments':[{}, {'station_start_m':12,'station_end_m':20}]}
        self.assertEqual(local_height_bindings(association,route)[0]['nearest_candidate']['station_m'],14)
        self.assertEqual(association['bindings'][0]['nearest_candidate']['station_m'],999)

    def test_ambiguous_heights_excluded_and_preview_closes_periodically(self):
        bindings = [{'status':'provisional_annotation_binding','nearest_candidate':{'station_m':s},'printed_level_m':h}
                    for s,h in [(0,10),(10,20),(20,10)]]
        bindings.append({'status':'ambiguous_route_section','nearest_candidate':{'station_m':5},'printed_level_m':99})
        heights=preview_profile({'route_length_m':30},bindings,[0,5,30])
        np.testing.assert_allclose(heights,[10,15,10])
        with self.assertRaises(ValueError): preview_profile({'route_length_m':30},bindings[:2],[0])

    def test_estimated_shell_and_clearance_survive_roof_overlap_after_export(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory); rows=[{'x':0,'y':y,'z':0,'kind':'roof','material':'stone'} for y in (10,11)]
            rows += [{'x':0,'y':10,'z':0,'kind':'structure','material':'iron_block','material_origin':'estimated_reconstruction_shell'},
                     {'x':0,'y':11,'z':0,'kind':'structure','material':'air','material_origin':'estimated_reconstruction_void'}]
            for row in rows[-2:]: row.update(source='wicker-estimated-reconstruction',feature='reconstruction/rails')
            (p/'voxels.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            r=export_world(p/'voxels.jsonl',p,{'voxel_size_m':1,'sources':[], 'spawn_local_xyz_m':[0,13,0]})
            self.assertEqual(r['spawn'],[0,13+r['vertical_offset_blocks'],0])
            level=amulet.load_level(str(p/'bedrock-world'))
            try:
                chunk=level.get_chunk(0,0,'minecraft:overworld')
                self.assertEqual(chunk.block_palette[int(chunk.blocks[0,10+r['vertical_offset_blocks'],0])].base_name,'iron_block')
                self.assertEqual(chunk.block_palette[int(chunk.blocks[0,11+r['vertical_offset_blocks'],0])].base_name,'air')
            finally: level.close()
            check=verify_preview(p,r,{'verified':False})
            self.assertEqual(check['world_component_blocks'],{'reconstruction/rails':1})
            self.assertFalse(check['verified'])
