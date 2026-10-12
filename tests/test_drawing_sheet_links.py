import unittest
from shapely.affinity import scale,translate
from shapely.geometry import box,mapping,shape
from voxel_mapper.drawing_sheet_links import link


class SheetLinkTests(unittest.TestCase):
    def fixture(self):
        a=[];b=[]
        for i,(x,y) in enumerate([(0,0),(100,0),(0,100),(100,100),(45,60)]):
            polygon=box(x,y,x+10+i,y+12+i)
            row={'id':str(i),'document_sha256':'a'*64,'page':1,'coordinate_frame':'pdf_native_points_y_up',
                 'geometry':mapping(polygon),'rendering_status':'supported_straight_unclipped_polygon'}
            a.append(row);b.append({**row,'document_sha256':'b'*64,
                'geometry':mapping(translate(scale(polygon,.5,.5,origin=(0,0)),30,50))})
        ar={'status':'one_visible_printed_scale','expected_metres_per_pdf_point':.1,'document_sha256':'a'*64,'page':1}
        br={**ar,'expected_metres_per_pdf_point':.2,'document_sha256':'b'*64}
        return a,b,ar,br

    def test_different_printed_scales_recover_native_sheet_transform(self):
        result=link(*self.fixture())
        self.assertEqual(result['status'],'cross_sheet_consistent_candidate')
        fit=result['native_sheet_transforms'][0]
        self.assertAlmostEqual(fit['matrix'][0][0],.5)
        self.assertAlmostEqual(fit['translation_pdf_points'][0],30)
        self.assertAlmostEqual(fit['translation_pdf_points'][1],50)
        self.assertFalse(result['registration_verified']);self.assertEqual(result['world_geometry_additions'],0)

    def test_source_scale_cannot_be_copied_from_another_sheet(self):
        a,b,ar,br=self.fixture()
        for changes in [{'document_sha256':'c'*64},{'page':2},{'status':'unverified'}]:
            with self.assertRaises(ValueError):link(a,b,{**ar,**changes},br)
        with self.assertRaisesRegex(ValueError,'different source'):link(a,a,ar,ar)

    def test_competing_sheet_patterns_are_not_silently_selected(self):
        a,b,ar,br=self.fixture()
        second=[{**r,'id':'other'+r['id'],'geometry':mapping(translate(shape(r['geometry']),500,0))} for r in b]
        result=link(a,b+second,ar,br)
        self.assertEqual(result['status'],'withheld')
        self.assertGreater(len(result['proposal']['hypotheses']),1)

    def test_insufficient_or_shifted_correspondences_do_not_qualify(self):
        a,b,ar,br=self.fixture()
        self.assertEqual(link(a[:3],b[:3],ar,br)['status'],'withheld')
        b[-1]['geometry']=mapping(translate(shape(b[-1]['geometry']),20,0))
        self.assertEqual(link(a,b,ar,br)['status'],'withheld')
