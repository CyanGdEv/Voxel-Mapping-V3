import unittest
from types import SimpleNamespace

import numpy as np

from tests.test_alton_aligned_world import layers
from voxel_mapper.alton_aligned_world import ChunkRenderer
from voxel_mapper.ride_adjacent_foliage import nearby_cells,apply
from voxel_mapper.wicker_track_interactions import fit_figure,anchor_opening_frames


class RideAdjacentFoliageTests(unittest.TestCase):
    def test_two_block_boundary_is_three_dimensional(self):
        deck={(5,64,-5):'oak_slab'}
        d=nearby_cells(np.array([[8,64,-5],[9,64,-5],[5,67,-5],[5,66,-5]]),deck)
        np.testing.assert_allclose(d[[0,2,3]],[2,2.5,1.5])
        self.assertGreater(d[1],2)

    def test_top_half_slab_changes_the_vertical_distance(self):
        d=nearby_cells(np.array([[5,67,-5]]),{(5,64,-5):'oak_slab_top'})
        self.assertEqual(d[0],2)

    def test_stacked_tracks_use_the_nearest_vertical_section(self):
        d=nearby_cells(np.array([[5,68,-5]]),{(5,64,-5):'oak_slab',(5,70,-5):'oak_slab'})
        self.assertEqual(d[0],1)

    def context(self):
        l=layers();l.audit={};l.wicker_track_native_decks={(5,70,-5):'oak_slab'}
        l.detail={(0,-1):[(5,70,11,'oak_slab')]};l.clear={(0,-1):[(5,72,11)]}
        points=[(8,70,-5),(9,70,-5),(5,74,-5),(5,72,-5)]
        leaf=np.array([((z+16)*16+x)|((y+512)<<22) for x,y,z in points],np.uint64)
        l.cloud.update(leaf_voxels=leaf,leaf_chunk_offsets=np.array([0,len(leaf)]))
        for x,y,z in points:l.cloud['vegetation'][z+16,x]=max(y,l.cloud['vegetation'][z+16,x])
        return l

    def test_native_replacements_preserve_far_canopy_and_clear_running_air(self):
        l=self.context();apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        r=ChunkRenderer(l);a,bottom=r.chunk(0,-1)
        def material(x,y,z):return r.materials[int(a[x,y-bottom,z%16])]
        self.assertEqual(material(8,70,-5),'dark_oak_fence')
        self.assertEqual(material(9,70,-5),'oak_leaves')
        self.assertEqual(material(5,74,-5),'oak_leaves')
        self.assertEqual(material(5,72,-5),'air')
        self.assertEqual(set(l.ride_wood_source_cells),{(8,70,-5)})

    def test_existing_architecture_is_not_replaced_by_source_leaf_interpretation(self):
        l=self.context();l.reference_detail={(0,-1):[(8,70,11,'stone_bricks')]}
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        self.assertNotIn((8,70,-5),l.ride_wood_source_cells)
        self.assertEqual(l.audit['ride_adjacent_foliage']['withheld']['existing_structure'],1)

    def test_full_fence_height_is_checked_against_a_ceiling(self):
        l=self.context();l.reference_detail={(0,-1):[(8,71,11,'stone_bricks')]}
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        self.assertNotIn((8,70,-5),l.ride_wood_source_cells)
        self.assertIn((8,70,11),l.ride_wood_clear[0,-1])

    def test_paving_headroom_does_not_gain_fences_from_previously_hidden_leaf_points(self):
        l=self.context();l.family[11,5]=1
        extra=np.uint64((11*16+5)|((67+512)<<22))
        l.cloud['leaf_voxels']=np.r_[l.cloud['leaf_voxels'],extra]
        l.cloud['leaf_chunk_offsets']=np.array([0,len(l.cloud['leaf_voxels'])])
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        self.assertNotIn((5,67,-5),l.ride_wood_source_cells)
        self.assertEqual(l.audit['ride_adjacent_foliage']['withheld']['walking_surface_headroom'],1)

    def test_fence_collision_height_keeps_riding_space_clear_beyond_legacy_air_mask(self):
        l=self.context();l.clear={}
        l.wicker_native_samples=[{'xyz':[5.5,70.5,-4.5]}]
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        self.assertNotIn((5,72,-5),l.ride_wood_source_cells)
        self.assertIn((5,72,11),l.ride_wood_clear[0,-1])

    def test_same_xy_visits_keep_separate_vertical_openings(self):
        samples=[]
        for station,height,x in ((10,70,5.5),(50,76,5.5),(90,70,11.5)):
            for delta in (0,1):samples.append({'station_m':station+delta,'xyz':[x,height,-5.5-delta],'normal_xz':[1,0]})
        l=SimpleNamespace(wicker_native_samples=samples,e0=0,n0=0,offset=0)
        class Scene:
            def __init__(self):self.l=l;self.records=[];self.air=set()
            def clearance(self,*key):self.air.add(tuple(key))
        scene=Scene()
        profile={'big_bob':{'front_bng_direction':[0,-1],'body_center_bng_en':[5,5],
                           'base_odn_m':68,'body_sections_height_half_width_half_depth_m':[[0,20,20],[20,20,20]]},
                 'track_interactions':{'opening_clear_height_m':3,'opening_half_width_m':1.75,
                                       'figure_station_windows_m':[[10,11],[50,51],[90,91]]}}
        proposed={(5,y,-6):'spruce_planks' for y in (71,74,77)}
        result=fit_figure(scene,proposed,profile)
        self.assertNotIn((5,71,-6),result);self.assertNotIn((5,77,-6),result)
        self.assertIn((5,74,-6),result)
        self.assertEqual(len(scene.records[0]['visits']),3)

    def test_clipped_frame_and_shoulder_fire_connect_above_the_passage(self):
        scene=SimpleNamespace(l=SimpleNamespace(),air={(0,0,0)},old_air=set(),old_solid=set())
        proposal={(0,1,0):'campfire',(3,1,0):'spruce_planks',(3,2,0):'spruce_planks',
                  (3,3,0):'spruce_planks'}
        result,audit=anchor_opening_frames(scene,proposal,lambda k:k in scene.air)
        self.assertEqual(result[0,1,0],'spruce_planks')
        self.assertEqual(result[0,2,0],'campfire')
        self.assertNotIn((0,0,0),result)
        self.assertEqual(audit['raised_shoulder_emitters'],1)
        # Every saved piece has a six-neighbour route to the main timber.
        reached={(3,1,0)}
        while True:
            extra={k for k in result if any(sum(abs(a-b) for a,b in zip(k,p))==1 for p in reached)}-reached
            if not extra:break
            reached.update(extra)
        self.assertEqual(reached,set(result))

    def test_member_rule_recovers_support_leaves_well_below_the_deck(self):
        l=self.context();l.detail[0,-1].append((8,65,11,'dark_oak_fence'))
        points=[(8,66,-5),(12,66,-5)]
        extra=np.array([((z+16)*16+x)|((y+512)<<22) for x,y,z in points],np.uint64)
        l.cloud['leaf_voxels']=np.r_[l.cloud['leaf_voxels'],extra]
        l.cloud['leaf_chunk_offsets']=np.array([0,len(l.cloud['leaf_voxels'])])
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence'})
        self.assertNotIn((8,66,-5),l.ride_wood_source_cells)
        apply(l,{'distance_blocks':2,'material':'dark_oak_fence','include_retained_support_members':True})
        self.assertIn((8,66,-5),l.ride_wood_source_cells)
        self.assertNotIn((12,66,-5),l.ride_wood_source_cells)
        r=ChunkRenderer(l);a,bottom=r.chunk(0,-1)
        self.assertEqual(r.materials[int(a[8,66-bottom,11])],'dark_oak_fence')
        self.assertEqual(r.materials[int(a[12,66-bottom,11])],'oak_leaves')


if __name__=='__main__':unittest.main()
