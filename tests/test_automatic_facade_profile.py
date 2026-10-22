import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw
import pymupdf

from voxel_mapper import automatic_facade_profile as profile
from voxel_mapper import automatic_facade_preview
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from tests import test_automatic_facade_preview as preview_tests


class FacadeProfileTests(unittest.TestCase):
    def gray(self):
        image=Image.new('L',(300,240),255);d=ImageDraw.Draw(image)
        d.rectangle([45,30,155,80],outline=0);d.rectangle([50,80,150,150],outline=0)
        d.rectangle([0,151,299,179],fill=192)
        return np.asarray(image).copy()

    def fixture(self,root):
        c,v,corpus,_=preview_tests.FacadePreviewTests().fixture(root)
        report=json.loads((c/'component-report.json').read_text());source=json.loads((v/'view-candidates.json').read_text())['pages'][0]
        gray=self.gray();stream=io.BytesIO();Image.fromarray(gray).save(stream,format='PNG');png=stream.getvalue()
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=240);page.insert_image(page.rect,stream=png);raw=doc.tobytes()
        sha=hashlib.sha256(raw).hexdigest();(corpus/'files'/(sha+'.pdf')).write_bytes(raw)
        source['document_sha256']=sha;view=next(x for x in source['views'] if x['id']=='elevation')
        view['render']={'png':'elevation.png','receipt':'elevation-receipt.json','png_sha256':hashlib.sha256(png).hexdigest()}
        (v/'elevation.png').write_bytes(png);atomic_json(v/'elevation-receipt.json',{'png_sha256':view['render']['png_sha256'],'size_pixels':[300,240]})
        invs={r['view_id']:json.loads((c/r['file']).read_text()) for r in report['results']}
        for key,inv in invs.items():
            inv['source_view_sha256']=digest(next(x for x in source['views'] if x['id']==key))
            inv['plan_gap_review']['gaps'][0]['gap_endpoints_pdf_native']=[[70.,50.],[80.,50.]]
        invs['elevation'].update(source_png_sha256=view['render']['png_sha256'],raster_coordinate_receipt={'quarter_turns_counterclockwise':0})
        ipins={k:digest(x) for k,x in invs.items()}
        reviews={k:json.loads((c/report[k]['file']).read_text()) for k in ('building_facade_links','elevation_level_context','facade_alignment','sheet_scale_evidence','wall_return_corners','door_symbol_evidence','artwork_scale_controls')}
        for review in reviews.values():review['source_inventory_sha256']=ipins
        level=reviews['elevation_level_context'];level['source_building_links_sha256']=digest(reviews['building_facade_links'])
        row=level['views'][0];row['relative_reference']['datum_y_display_points']=150.
        row['families'][0]['witnesses'][0]['source_bounds_pixels']=[50,80,150,180]
        row['families'][1]['witnesses'][0]['source_bounds_pixels']=[70,100,80,180]
        old=reviews['wall_return_corners']['diagnostics'][0];old['position_comparisons'][0]['source_gap_projection']['source_gap_sha256']=digest(invs['floor']['plan_gap_review']['gaps'][0])
        reviews['door_symbol_evidence']['conditional_position_links'][0]['source_position_comparison_sha256']=digest(old['position_comparisons'][0])
        artwork=reviews['artwork_scale_controls'];artwork['pages'][0].update(document_sha256=sha,source_page_views_sha256=digest(source))
        artwork['pairs'][0].update(subject_page_key=[sha,1],reference_page_key=[sha,1])
        artwork['diagnostics'][0].update(source_return_diagnostic_sha256=digest(old),source_points_pdf_native=[[50.,50.],[150.,50.]])
        for r in report['results']:atomic_json(c/r['file'],invs[r['view_id']])
        for key,review in reviews.items():atomic_json(c/report[key]['file'],review)
        report['output_sha256']={name:file_hash(c/name) for name in report['output_sha256']}
        atomic_json(v/'view-candidates.json',{'pages':[source]});atomic_json(v/'view-report.json',{'contract':{'source_sha256':[sha]},
            'output_sha256':{name:file_hash(v/name) for name in ['view-candidates.json','elevation.png','elevation-receipt.json']}})
        report['contract'].update(view_report_sha256=file_hash(v/'view-report.json'),view_candidates_sha256=file_hash(v/'view-candidates.json'))
        atomic_json(c/'component-report.json',report)
        prior=automatic_facade_preview.build(c,v,corpus,root/'previews')
        return Path(prior['directory']),c,v,corpus,root/'profiles'

    def test_closed_roof_and_observed_ground_profile_retain_original_grid(self):
        g=self.gray();before=g.copy();rows=profile.profiles(g,[50,80,150,180],lambda:None)
        np.testing.assert_array_equal(g,before)
        for r in rows:
            self.assertEqual(r['status'],'source_profile_masks_only');self.assertEqual(r['source_upper_span_pixels'],[45,156])
            self.assertTrue(r['full_ground_column_support']);self.assertTrue(all(c['shade_row_interval']==[151,180] for c in r['ground_columns']))
            self.assertTrue(r['roof_mask'][30,80]);self.assertFalse(r['roof_mask'][30,45]);self.assertFalse(r['wall_mask'][151,80]);self.assertTrue(r['wall_mask'][150,80])
            self.assertGreater(r['source_roof_wall_overlap_cells'],0);self.assertFalse(r['source_roof_wall_overlap_repaired'])

    def test_steps_and_missing_shade_columns_stay_explicit_without_interpolation(self):
        g=self.gray();g[155:180,60:70]=192;g[151:155,60:70]=255;g[151:180,90]=255
        rows=profile.profiles(g,[50,80,150,180],lambda:None)
        for row in rows:
            self.assertFalse(row['full_ground_column_support']);self.assertFalse(row['ground_columns'][40]['supported'])
            self.assertFalse(row['wall_mask'][:,90].any());self.assertEqual(row['ground_columns'][10]['shade_row_interval'][0],155)

    def test_open_white_exterior_and_fragmented_or_gabled_roof_are_withheld(self):
        for mode in ('empty','open','gable','callout'):
            g=self.gray()
            if mode=='empty':g[:80,:]=255
            elif mode=='open':g[30,45:156]=255
            elif mode=='gable':
                g[:80,:]=255;im=Image.fromarray(g);ImageDraw.Draw(im).polygon([(45,80),(100,25),(155,80)],outline=0);g=np.array(im)
            else:g[10,45:156]=0
            rows=profile.profiles(g,[50,80,150,180],lambda:None)
            self.assertTrue(all(r['status']!='source_profile_masks_only' for r in rows),mode)
            self.assertTrue(all('roof_mask' not in r for r in rows))

    def test_surface_losslessly_preserves_holes_steps_and_disconnected_cells(self):
        mask=np.zeros((30,40),bool);mask[3:20,4:25]=True;mask[8:12,10:17]=False;mask[22:24,30:35]=True
        mesh=profile.surface(mask,[4,3,25,20],.2,16.,lambda:None);copy=np.zeros_like(mask)
        for x0,y0,x1,y1 in mesh['source_rectangles_pixels']:
            self.assertFalse(copy[y0:y1,x0:x1].any());copy[y0:y1,x0:x1]=True
        np.testing.assert_array_equal(copy,mask);self.assertEqual(mesh['source_hole_count'],1)
        self.assertEqual(len(mesh['triangles']),2*len(mesh['source_rectangles_pixels']));self.assertFalse(mesh['holes_are_verified_apertures'])
        self.assertIsNone(mesh['roof_pitch_degrees']);self.assertIsNone(mesh['wall_thickness_m'])
        area=0.
        for a,b,c in mesh['triangles']:
            points=np.array(mesh['vertices_nominal_local_m'])[[a,b,c]][:,[0,2]]
            area+=abs(float(np.linalg.det(np.array([points[1]-points[0],points[2]-points[0]]))))/2
        self.assertAlmostEqual(area,mask.sum()*.04)

    def test_original_threshold_variants_are_separate_and_input_validation_is_bounded(self):
        g=self.gray();g[45:47,80:85]=225
        rows=profile.profiles(g,[50,80,150,180],lambda:None)
        self.assertEqual([r['threshold'] for r in rows],[220,235]);self.assertIsNot(rows[0]['roof_mask'],rows[1]['roof_mask'])
        for bad in (np.ones((20,20),float),np.ones((3001,2),np.uint8)):
            with self.assertRaises(ValueError):profile.profiles(bad,[1,1,10,10],lambda:None)
        for bounds in ([-1,80,150,180],[50.,80,150,180],[50,80,350,180]):
            with self.assertRaises(ValueError):profile.profiles(g,bounds,lambda:None)
        with self.assertRaises(ValueError):profile.surface(np.zeros((2,2),bool),[0,0,2,2],float('nan'),2.,lambda:None)

    def test_source_region_and_rectangle_caps_raise_before_partial_mesh_output(self):
        g=self.gray()
        with patch.object(profile.ndimage,'label',return_value=(np.zeros_like(g,dtype=int),8193)):
            with self.assertRaisesRegex(OverflowError,'source_region'):profile.profiles(g,[50,80,150,180],lambda:None)
        mask=np.indices((100,200)).sum(axis=0)%2==0
        with self.assertRaisesRegex(OverflowError,'rectangle'):profile.rectangles(mask,lambda:None)

    def test_original_pdf_end_to_end_and_deterministic_cached_masks(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=profile.build(*args)
            self.assertEqual(r['counts']['supported_profile_variants'],2);self.assertEqual(r['counts']['source_masks'],4)
            self.assertEqual(r['counts']['source_opening_alternatives'],1);self.assertEqual(r['profiles'][0]['threshold_comparison']['wall']['different_cells'],0)
            self.assertEqual(r,profile.build(*args));self.assertFalse(r['world_placement_eligible']);self.assertEqual(r['world_geometry_additions'],0)

    def test_early_and_late_budget_holds_publish_no_partial_geometry_or_masks(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=profile.build(*args,max_checks=1)
            self.assertEqual(r['status'],'facade_profile_budget_withheld');self.assertEqual(r['profiles'],[]);self.assertEqual(r['source_raster_receipts'],[])
            self.assertFalse(list(Path(r['directory']).rglob('*.png')))
            original=profile.surface;calls=[]
            def late(*a,**kw):
                calls.append(1)
                if len(calls)==2:raise OverflowError('late_mesh_budget')
                return original(*a,**kw)
            with patch.object(profile,'surface',side_effect=late):r=profile.build(*args)
            self.assertEqual(r['profiles'],[]);self.assertFalse(list(Path(r['directory']).rglob('*.png')))
        for value in (0,True,100001):
            with self.assertRaises(ValueError):profile.build('','','','','',max_checks=value)

    def test_changed_preview_source_crop_or_original_pdf_fails_before_output(self):
        for mode in ('preview','crop','pdf'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));p,c,v,corpus,out=args
                if mode=='preview':
                    r=json.loads((p/'facade-preview.json').read_text());r['previews'][0]['source_child_bounds_pixels'][0]+=1;atomic_json(p/'facade-preview.json',r)
                elif mode=='crop':next((p/'crops').glob('*.png')).write_bytes(b'changed')
                else:
                    r=json.loads((p/'facade-preview.json').read_text());sha=r['contract']['source_pdf_sha256'][0];f=corpus/'files'/(sha+'.pdf');f.write_bytes(f.read_bytes()+b' ')
                with self.assertRaises(ValueError):profile.build(*args)
                self.assertFalse(out.exists())

    def test_independent_saved_profile_audit_recomputes_source_masks_and_meshes(self):
        from scripts.audit_automatic_facade_profile import audit
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=profile.build(*args)
            p,c,v,corpus,_=args
            report=audit(r['directory'],p,c,v,corpus,Path(tmp)/'audit.json')
            self.assertEqual(report['status'],'passed');self.assertEqual(report['checked']['independent_source_masks'],4)
            self.assertEqual(report['checked']['original_ground_column_runs'],200)

    def test_tampered_saved_json_or_mask_is_rejected(self):
        for mode in ('json','mask'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));r=profile.build(*args);root=Path(r['directory'])
                if mode=='json':(root/'facade-profile.json').write_text('{}')
                else:next((root/'masks').glob('*.png')).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'Saved'):profile.build(*args)


if __name__=='__main__':unittest.main()
