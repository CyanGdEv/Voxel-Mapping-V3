import copy
import unittest
from voxel_mapper.sheet_layout_audit import fit,diagnostic_lengths


class SheetLayoutTests(unittest.TestCase):
    def inputs(self):
        terms=[{'text':f'furniture {i}','role':'fit' if i<8 else 'holdout'} for i in range(12)]
        subject={};reference={}
        for i,term in enumerate(terms):
            x,y=(i%4)*100+20,(i//4)*60+20
            common={'within_declared_furniture_scope':True,'glyph_screen':{'status':'raster_consistent_candidate'}}
            reference[term['text']]=[{**common,'origin_pdf_native':[x,y],'font_size_points':10}]
            subject[term['text']]=[{**common,'origin_pdf_native':[x*.9+30,y*.9+40],'font_size_points':9}]
        return subject,reference,terms

    def test_heldout_correspondence_and_diagnostic_lengths_do_not_modify_source(self):
        subject,reference,terms=self.inputs();before=copy.deepcopy(subject);r=fit(subject,reference,terms)
        self.assertEqual(r['status'],'supported_furniture_layout_correspondence_only')
        self.assertAlmostEqual(r['apparent_subject_layout_scale'],.9)
        self.assertLess(r['holdout_max_residual_pdf_points'],1e-8)
        self.assertFalse(r['geometry_correction_applied']);self.assertFalse(r['physical_scale_verified'])
        self.assertEqual(subject,before)
        edges=[{'id':'source','points':[[0,0],[90,0]],'coordinate_frame':'unrotated_mupdf_points_y_down'}]
        before=copy.deepcopy(edges);matches=diagnostic_lengths(edges,r,.1,10)
        self.assertAlmostEqual(matches[0]['raw_nominal_length_m'],9)
        self.assertAlmostEqual(matches[0]['inverse_layout_nominal_length_candidate_m'],10)
        self.assertEqual(edges,before);self.assertFalse(matches[0]['physical_correspondence_verified'])

    def test_duplicate_hidden_missing_or_out_of_scope_required_terms_withhold_whole_fit(self):
        for mode in ('duplicate','hidden','missing','outside'):
            subject,reference,terms=self.inputs();key=terms[0]['text']
            if mode=='duplicate':subject[key]*=2
            elif mode=='hidden':subject[key][0]['glyph_screen']['status']='withheld'
            elif mode=='missing':subject[key]=[]
            else:subject[key][0]['within_declared_furniture_scope']=False
            r=fit(subject,reference,terms);self.assertEqual(r['status'],'withheld_layout_correspondence')
            self.assertEqual(diagnostic_lengths([],r,.1,10),[])

    def test_holdouts_font_ratios_anisotropy_and_collinearity_cannot_be_discarded(self):
        for mode in ('holdout','font','anisotropic','collinear'):
            subject,reference,terms=self.inputs()
            if mode=='holdout':subject[terms[-1]['text']][0]['origin_pdf_native'][0]+=1
            elif mode=='font':subject[terms[-1]['text']][0]['font_size_points']=12
            elif mode=='anisotropic':
                for term in terms:
                    x,y=reference[term['text']][0]['origin_pdf_native'];subject[term['text']][0]['origin_pdf_native']=[x*.8+30,y+40]
            else:
                for term in terms:reference[term['text']][0]['origin_pdf_native'][1]=20
            self.assertEqual(fit(subject,reference,terms)['status'],'withheld_layout_correspondence')
        subject,reference,terms=self.inputs()
        with self.assertRaises(ValueError):fit(subject,reference,terms[:8])
        terms[-1]['text']=terms[0]['text']
        with self.assertRaises(ValueError):fit(subject,reference,terms)


if __name__=='__main__':unittest.main()
