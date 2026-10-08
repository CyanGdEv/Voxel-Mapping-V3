import unittest
import json
import tempfile
from pathlib import Path
from shapely.geometry import box
from voxel_mapper.xsector import audit_route, station_shell, apply_overlay


def way(points):
    return {'id':1,'nodes':list(range(len(points)-1))+[0],
            'geometry':[{'lon':x,'lat':z} for x,z in points],
            'tags':{'layer':'5'}}


class XSectorTests(unittest.TestCase):
    def test_crossing_needs_vertical_controls_even_with_layer_tags(self):
        route=audit_route([way([(0,0),(10,10),(0,10),(10,0),(0,0)])],lambda x,z:(x,z))
        self.assertEqual(len(route['crossings']),1)
        self.assertEqual(route['crossings'][0]['segment_indices'],[0,2])
        self.assertEqual(route['track_generation'],'withheld_pending_3d_controls')
        self.assertNotIn('route_length_m',route)

    def test_disconnected_route_cannot_be_rendered(self):
        w=way([(0,0),(10,0),(10,10),(0,0)])
        w['nodes'][-1]=100
        with self.assertRaises(ValueError):audit_route([w],lambda x,z:(x,z))

    def test_level_shell_clears_solid_interior_and_keeps_walls(self):
        rows,report=station_shell(box(0,0,6,6),lambda x,z:100+z/10,lambda x,z:106,'test')
        materials={(r['x'],r['y'],r['z']):r['material'] for r in rows}
        self.assertEqual(materials[2,100,2],'black_concrete')
        self.assertEqual(materials[2,103,2],'air')
        self.assertEqual(materials[0,103,2],'black_concrete')
        self.assertEqual(materials[2,106,2],'black_concrete')
        self.assertEqual(report['floor_odn_m'],100)

    def test_missing_or_implausible_elevations_fail_before_world_mutation(self):
        for ground,surface in [(lambda x,z:None,lambda x,z:106),
                               (lambda x,z:100,lambda x,z:150)]:
            with self.assertRaises(ValueError):station_shell(box(0,0,6,6),ground,surface,'test')

    def test_overlay_preserves_other_cells_and_base_world(self):
        import amulet
        from voxel_mapper.bedrock import export_world
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'base'; source.mkdir()
            rows=[{'x':0,'y':100,'z':0,'kind':'terrain'},
                  {'x':1,'y':105,'z':0,'kind':'structure','material':'iron_block'}]
            voxels=source/'voxels.jsonl'
            voxels.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            quality={'voxel_size_m':1,'sources':[]}
            quality['world']=export_world(voxels,source,quality,ground_depth=4)
            (source/'quality-report.json').write_text(json.dumps(quality))
            original=(source/'park.mcworld').read_bytes()
            overlay=[{'x':0,'y':101,'z':0,'material':'black_concrete'}]
            report={'stations':[]}
            apply_overlay(source,root/'updated',overlay,report)
            self.assertEqual(report['world_verification']['composed_block_delta'],1)
            self.assertEqual(original,(source/'park.mcworld').read_bytes())
            level=amulet.load_level(str(root/'updated/bedrock-world'))
            try:
                chunk=level.get_chunk(0,0,'minecraft:overworld')
                offset=quality['world']['vertical_offset_blocks']
                self.assertEqual(chunk.block_palette[int(chunk.blocks[1,105+offset,0])].base_name,'iron_block')
            finally:level.close()
            with self.assertRaises(ValueError):apply_overlay(source,root/'updated',overlay,report)

    def test_station_voxel_budget_is_enforced(self):
        with self.assertRaises(ValueError):
            station_shell(box(0,0,6,6),lambda x,z:100,lambda x,z:106,'test',max_records=10)


if __name__=='__main__':unittest.main()
