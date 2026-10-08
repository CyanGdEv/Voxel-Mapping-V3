import unittest
from shapely.geometry import box,mapping
from voxel_mapper.park_details import detail_semantics,labelled_faces,raster_cells,emit_detail,building_material
from voxel_mapper.park_paving_plans import surface_boundaries

class ConstantTerrain:
    def __init__(self,height=100):self.height=height
    def sample(self,x,z):return self.height

class DetailTests(unittest.TestCase):
    def test_split_building_material_phrase_is_spatially_bound(self):
        labels=[{'text':'steel','origin':[1,1],'bbox':[1,.8,2,1.2]},
                {'text':' clad','origin':[2,1],'bbox':[2,.8,3,1.2]}]
        self.assertEqual(building_material(labels,box(0,0,4,2)),'gray_concrete')
        self.assertIsNone(building_material(labels[:1],box(0,0,4,2)))
        self.assertIsNone(building_material(labels,box(20,20,24,22)))
        self.assertIsNone(building_material(labels+[{'text':'brick','origin':[1,1.5],'bbox':[1,1.4,2,1.6]}],box(0,0,4,2)))

    def test_floor_and_roof_material_words_do_not_become_objects(self):
        for text in ('brick paving','concrete','rocks legend','building height unknown','roof','stone wall to'):
            self.assertIsNone(detail_semantics(text))
        self.assertEqual(detail_semantics('brick wall 0.80ht')['height_m'],.8)
        self.assertEqual(detail_semantics('stone retaining wall')['kind'],'retaining_wall')
        self.assertEqual(detail_semantics('timber building')['material'],'oak_planks')

    def test_containment_uses_smallest_bounded_face_and_withholds_unbound_label(self):
        polygons=[{'geometry':mapping(box(0,0,20,20))},{'geometry':mapping(box(2,2,4,4))}]
        labels=[{'text':'rocks','origin':[3,3],'bbox':[2.9,2.9,3.1,3.1]},
                {'text':'planter','origin':[50,50],'bbox':[49,49,51,51]}]
        found,withheld=labelled_faces(polygons,labels,1)
        self.assertEqual([f['face_index'] for f in found],[1])
        self.assertEqual(len(withheld),1)

    def test_planter_adjacent_label_requires_unique_drawn_footprint(self):
        label={'text':'planter','origin':[0,0],'bbox':[0,0,.1,.1]}
        found,_=labelled_faces([{'geometry':mapping(box(0,.6,1,1.6))}],[label],1)
        self.assertEqual(found[0]['association'],'unique_adjacent_native_label')
        found,_=labelled_faces([{'geometry':mapping(box(0,.6,1,1.6))},
                               {'geometry':mapping(box(-1,.6,0,1.6))}],[label],1)
        self.assertEqual(found,[])

    def test_subblock_raster_stays_near_measured_object(self):
        self.assertEqual(raster_cells(box(.05,.05,.45,.45)),[(0,0)])
        self.assertEqual(raster_cells(box(0,0,.1,.1)),[])

    def test_printed_wall_height_and_estimated_rock_height_are_distinct(self):
        props={'kind':'wall','material':'bricks','material_status':'printed_wall_material',
               'height_m':1.4,'height_status':'printed_annotation','document_id':'source','page':1,'source_url':'official'}
        f={'id':'wall','geometry':mapping(box(0,0,1,1)),'properties':props}
        rows,report=emit_detail(f,ConstantTerrain())
        self.assertEqual([r['y'] for r in rows],[101,102])
        self.assertEqual(report['height_status'],'printed_annotation')
        rows,report=emit_detail({**f,'properties':{**props,'kind':'rock','height_status':'low_relief_preview_not_printed_height'}},ConstantTerrain())
        self.assertEqual(report['height_status'],'low_relief_preview_not_printed_height')
        self.assertTrue(all(r['y']>100 for r in rows))

    def test_missing_building_height_never_creates_default_box(self):
        f={'id':'building','geometry':mapping(box(0,0,3,3)),'properties':{
           'kind':'building','material':'stone_bricks','material_status':'unknown','document_id':'source','page':1,'source_url':'official'}}
        rows,report=emit_detail(f,ConstantTerrain())
        self.assertEqual(rows,[]);self.assertEqual(report['status'],'withheld')

    def test_detail_face_budget_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):surface_boundaries([],1,min_area=-1)
        self.assertEqual(surface_boundaries([],1,min_area=.15,max_area=1500),[])

if __name__=='__main__':unittest.main()
