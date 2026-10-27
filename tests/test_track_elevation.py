"""Regression coverage for banks missed by the previous centre-only check."""
import unittest
from shapely.geometry import LineString,Polygon,mapping
from voxel_mapper import track_elevation as elevation, full_track_world as world


class TrackElevationTests(unittest.TestCase):
    def settings(self):
        return {'shoulder_half_width_m':3,'minimum_deck_top_over_ground_m':1,'maximum_smoothing_grade':1,'covered_zones':[],'clearance_blocks':2,'maximum_covered_cut_m':4,'protected_building_height_m':186}

    def ground(self):
        return {(x,y):{'x':x,'y':10,'z':y+1,'kind':'terrain','material':'grass_block'} for x in range(-5,46) for y in range(-5,6)}

    def test_bank_raises_outdoor_profile_without_changing_terrain(self):
        line=LineString([(0,0),(40,0)]);ground=self.ground();ground[20,2]['y']=17
        original={k:dict(v) for k,v in ground.items()}
        controls=[{'label':'LP','station_m':0,'height_m':14},{'label':'HP','station_m':40,'height_m':14}]
        fitted,review=elevation.fit_profile(line,controls,ground,self.settings())
        self.assertGreaterEqual(world.timber.height_at(20,fitted),19)
        self.assertEqual(ground,original)
        blocks,core,head,samples,_=world.sample_route(line,fitted,clearance_blocks=2)
        self.assertEqual(elevation.check_terrain(ground,blocks,core,samples,self.settings())['buried_outdoor_slabs'],0)
        self.assertTrue(review['outdoor_profile_never_below_shoulder_requirement'])

    def test_retained_fence_top_is_part_of_clearance_envelope(self):
        line=LineString([(0,0),(40,0)]);ground=self.ground()
        controls=[{'station_m':0,'height_m':14},{'station_m':40,'height_m':14}]
        fitted,_=elevation.fit_profile(line,controls,ground,self.settings(),{(20,15,0):'oak_fence'})
        self.assertGreaterEqual(world.timber.height_at(20,fitted),17.5)

    def test_explicit_underpass_slot_is_not_raised_through_upper_floor(self):
        line=LineString([(0,0),(40,0)]);ground=self.ground()
        settings=self.settings();settings['covered_zones']=[{'id':'preshow','start_m':10,'end_m':30,'top_m':12}]
        controls=[{'station_m':0,'height_m':16},{'station_m':10,'height_m':12},{'station_m':30,'height_m':12},{'station_m':40,'height_m':16}]
        ground[20,2]['y']=14
        fitted,review=elevation.fit_profile(line,controls,ground,settings)
        self.assertEqual(world.timber.height_at(20,fitted),12)
        blocks,core,head,_,_=world.sample_route(line,fitted,clearance_blocks=2)
        self.assertNotIn((20,14,0),head)  # underside of an upper floor at 14
        self.assertNotIn((20,14,0),blocks)

    def test_actual_adjacent_bank_is_rejected_even_when_track_cell_is_clear(self):
        ground=self.ground();ground[20,1]['y']=14
        with self.assertRaisesRegex(ValueError,'clearance failed'):
            elevation.check_terrain(ground,{(20,13,0):'oak_slab_top'},{(20,13,0):'oak_slab_top'},[{'station_m':20,'cells_xy':[(20,0)]}],self.settings())

    def test_outdoor_cut_and_roof_removal_are_forbidden(self):
        poly=mapping(Polygon([(-2,-2),(2,-2),(2,2),(-2,2)]))
        base={'parts':[],'maintenance':{'wall_geometry_nominal_local':poly}}
        profile={'max_terrain_cut_m':6,'max_structure_removals':250,'height_fit':self.settings()}
        ground={(0,0):{'x':0,'y':20,'z':1,'kind':'terrain','material':'grass_block'}}
        with self.assertRaisesRegex(ValueError,'Outdoor terrain excavation forbidden'):
            world.prepare_park(ground,{}, {(0,18,0):'oak_slab_top'}, {(0,18,0):'oak_slab_top'},set(),profile,base)
        ground[0,0]['y']=180
        with self.assertRaisesRegex(ValueError,'protected roof'):
            world.prepare_park(ground,{(0,186,0):'oak_slab'}, {(0,185,0):'oak_slab_top'}, {(0,185,0):'oak_slab_top'},{(0,186,0)},profile,base)


if __name__=='__main__':unittest.main()
