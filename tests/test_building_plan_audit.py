import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

import pymupdf
from shapely.geometry import shape
from voxel_mapper.building_plan_audit import VERSION,prepare


class PlanAuditTests(unittest.TestCase):
    def sources(self,root,*,open_plan=False):
        terms=[{'text':f'Furniture {i}','role':'fit' if i<8 else 'holdout'} for i in range(12)]
        sources=[]
        for name,reduction in [('plan',.9),('reference',1)]:
            document=pymupdf.open();page=document.new_page(width=800,height=700)
            for i,term in enumerate(terms):
                x,y=50+(i%4)*170,500+(i//4)*65
                x,y=x*reduction+(20 if name=='plan' else 0),y*reduction+(40 if name=='plan' else 0)
                page.insert_text((x,700-y),term['text'],fontsize=8*reduction)
            page.insert_text((40,300),'1 : 100',fontsize=10)
            if name=='plan':
                native=[(100,100),(300,100),(300,200),(200,200),(200,300),(100,300),(100,100)]
                points=[pymupdf.Point(x,700-y) for x,y in native]
                if open_plan:points=points[:-1]
                page.draw_polyline(points)
                page.insert_text((120,540),'Shop',fontsize=10)
                page.insert_text((120,560),'GIA: 170m2',fontsize=8)
            page.set_rotation(90);data=document.tobytes();document.close()
            path=root/(name+'.pdf');path.write_bytes(data)
            sources.append({'path':path.name,'sha256':hashlib.sha256(data).hexdigest(),'page':1,
                'furniture_bounds_pdf_native':[0,450,800,700]})
        return {'version':VERSION,'building_id':'shop','plan':sources[0],'reference_sheet':sources[1],
            'furniture_anchors':terms,'component_label':'Shop','component_bounds_pdf_native':[50,50,400,350],
            'elevation_width_candidates_m':[7.84]}

    def test_non_rectangular_exact_named_face_holes_and_printed_area_are_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.sources(root);r=prepare(config,lambda p:root/p,root/'out')
            self.assertEqual(r['sheet_layout_audit']['status'],'supported_furniture_layout_correspondence_only')
            self.assertEqual(r['named_enclosure_audit']['closed_source_footprint_candidates'],1)
            face=r['named_enclosure_audit']['label_occurrences'][0]['enclosure_candidates'][0]
            self.assertEqual(shape(face['geometry']).area,30000)
            self.assertEqual(len(shape(face['geometry']).exterior.coords),7)
            self.assertFalse(face['physical_footprint_verified'])
            self.assertEqual(r['named_enclosure_audit']['printed_area_claims'][0]['printed_gia_m2'],170)
            self.assertFalse(r['source_geometry_changed']);self.assertEqual(r['training_labels_generated'],0)
            with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'out')

    def test_open_named_plan_is_not_repaired_and_cli_replay_is_deterministic(self):
        from voxel_mapper.building_pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.sources(root,open_plan=True)
            (root/'config.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()):main(['audit-plan','--config',str(root/'config.json'),'--output',str(root/'out')])
            r=prepare(config,lambda p:root/p,root/'again')
            self.assertEqual(r,json.loads((root/'out/report.json').read_text()))
            self.assertEqual(r['named_enclosure_audit']['closed_source_footprint_candidates'],0)
            self.assertEqual(r['named_enclosure_audit']['label_occurrences'][0]['status'],'no_exact_named_enclosure')
            self.assertFalse(r['named_enclosure_audit']['geometry_snapping_or_gap_bridging'])
            self.assertIsNone(json.loads((root/'out/review-queue.json').read_text())['outcome'])

    def test_checksums_scope_and_changed_source_prevent_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.sources(root)
            bad=json.loads(json.dumps(config));bad['plan']['sha256']='f'*64
            with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')
            bad=json.loads(json.dumps(config));bad['component_bounds_pdf_native']=[0,0,800,700]
            with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')
            import voxel_mapper.building_plan_audit as module
            original=module.recover_endcaps
            def mutate(*args,**kwargs):
                result=original(*args,**kwargs);(root/'plan.pdf').write_bytes(b'changed');return result
            with patch('voxel_mapper.building_plan_audit.recover_endcaps',side_effect=mutate):
                with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'mutated')
            self.assertFalse((root/'mutated').exists())


if __name__=='__main__':unittest.main()
