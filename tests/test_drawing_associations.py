import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from voxel_mapper.drawing_associations import associate_labels, extract_associations


def polygons(extra=False):
    ring=[[0,0],[100,0],[100,100],[0,100],[0,0]]
    hole=[[40,40],[60,40],[60,60],[40,60],[40,40]]
    items=[{'paint_group':1,'geometry':{'type':'Polygon','coordinates':[ring,hole]}}]
    if extra:
        items.append({'paint_group':2,'geometry':{'type':'Polygon','coordinates':[ring]}})
    return {'status':'unplaced_candidates','layers':[{'viewport':0,'metric_crs':'test','polygons':items}]}


class AssociationTests(unittest.TestCase):
    def test_unique_interior_only_and_viewport_isolation(self):
        labels=[dict(viewport=0,metric_crs='test',metric_anchor=p) for p in ([20,20],[50,50],[0,20])]
        result=associate_labels(polygons(),labels)
        self.assertEqual(len(result['associations']),1)
        self.assertEqual(result['unmatched_labels'],2)
        self.assertEqual(associate_labels(polygons(True),labels[:1])['ambiguous_labels'],1)
        labels[0]['viewport']=1
        self.assertEqual(associate_labels(polygons(),labels[:1])['unmatched_labels'],1)
        self.assertEqual(associate_labels(polygons(),labels,max_labels=1)['status'],'budget_rejected')

    def test_native_pdf_text_evidence_is_unverified_and_gated(self):
        writer=PdfWriter()
        page=writer.add_blank_page(100,100)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject()
        stream.set_data(b'BT /F1 8 Tf 1 0 0 1 20 20 Tm (Proposed plaza surface: red concrete FFL 12 m ODN) Tj ET')
        page[NameObject('/Contents')]=stream
        registration={'viewports':[dict(viewport=0,metric_crs='test',status='internally_consistent_unverified',viewport_bbox=[0,0,100,100],control_hull=[[0,0],[1,0],[1,1],[0,1]],normalised_to_metric=[[100,0],[0,100],[0,0]])]}
        self.assertEqual(extract_associations(page,registration,polygons())['status'],'blocked_reuse')
        result=extract_associations(page,registration,polygons(),reuse_allowed=True)
        self.assertEqual(len(result['associations']),1)
        candidate=result['associations'][0]
        self.assertEqual(candidate['feature_type_candidates'],['plaza'])
        self.assertEqual(candidate['materials'][0]['colour_candidates'],['red'])
        self.assertEqual(candidate['levels'][0]['value_candidate'],12)
        self.assertEqual(candidate['levels'][0]['construction_label'],'proposed')
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertEqual(extract_associations(page,registration,polygons(),reuse_allowed=True,max_text=1)['associations'],[])
