import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import amulet
from voxel_mapper.wicker_reconstruction import preview_profile, verify_preview
from voxel_mapper.bedrock import export_world


class ReconstructionTests(unittest.TestCase):
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
