import unittest
from unittest.mock import patch
import pymupdf
from shapely.geometry import box,mapping
from voxel_mapper.drawing_views import page_labels,page_references,cross_links,attach_metrics,sheet_identity,resolve_identity


def trace(value,copies=1,offset=.24):
    chars=[]
    for n in range(copies):
        for i,c in enumerate(value):chars.append((ord(c),ord(c),(i+(n%2)*offset,(n//2)*offset),(i,0,i+1,1)))
    return {'chars':chars}


class ViewTests(unittest.TestCase):
    def page(self,doc):
        p=doc.new_page(width=600,height=600)
        p.insert_text((350,500),'2967-26',fontsize=10)
        p.insert_text((50,230),'Elevation 1 to the S.East',fontsize=10)
        p.insert_text((50,250),'1 : 100',fontsize=8)
        return p

    def test_native_title_and_scale_produce_nominal_metric_candidate(self):
        with pymupdf.open() as doc:
            p=self.page(doc);labels=page_labels(p,[{'id':'a','bbox_page_points':[40,40,280,200]}])
            view=labels['views'][0]
            self.assertEqual(view['view_key_candidate'],['2967',26,1])
            self.assertFalse(view['scale_verified']);self.assertFalse(view['view_identity_verified'])
            record={'raster_region_review':{'artwork_review_window_ids':['a']},'raster_contrast_boundary_review':{'status':'unverified_contrast_boundary_candidate','geometry':mapping(box(40,40,140,140))}}
            attach_metrics(p,[record],labels)
            metrics=record['raster_contrast_boundary_review']['nominal_measurements_candidate']
            self.assertAlmostEqual(metrics['width_m'],100*.0254*100/72)
            self.assertFalse(metrics['height_datum_verified'])

    def test_duplicate_artwork_and_scales_withheld(self):
        with pymupdf.open() as doc:
            p=self.page(doc);windows=[{'id':i,'bbox_page_points':[40,40,280,200]} for i in ('a','b')]
            self.assertEqual(page_labels(p,windows)['views'][0]['status'],'withheld_view_artwork_assignment')
            p.insert_text((50,260),'1 : 200',fontsize=8)
            self.assertEqual(page_labels(p,windows[:1])['views'][0]['status'],'withheld_view_scale_assignment')

    def test_sheet_overprints_require_identical_text_and_coherent_origins(self):
        self.assertEqual(sheet_identity([trace('2967-26',4)])['sheet'],26)
        self.assertIsNone(sheet_identity([trace('2967-26',2,offset=20)]))
        self.assertIsNone(sheet_identity([trace('2967-262967-27')]))
        self.assertIsNone(resolve_identity([trace('2967-26')],{'drawing_number':'2967-48'}))

    def test_duplicate_view_targets_withheld_and_unique_reference_remains_unverified(self):
        view={'view_key_candidate':['2967',26,1]};reference={'target_view_key_candidate':['2967',26,1]}
        pages=[('a',1,{'views':[view]},{}),('plan',1,{}, {'references':[reference]})]
        links=cross_links(pages)
        self.assertEqual(links[0]['status'],'unique_unverified_plan_elevation_reference')
        self.assertFalse(links[0]['physical_building_identity_verified'])
        pages.append(('other',1,{'views':[view]},{}))
        self.assertEqual(cross_links(pages)[0]['status'],'withheld_nonunique_or_missing_view_target')

    def test_reference_needs_circle_filled_corner_and_outside_index(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=600,height=600)
            p.insert_text((350,500),'2967-48',fontsize=10)
            p.draw_circle((200,200),17)
            p.draw_rect(pymupdf.Rect(183,200,200,217),color=None,fill=(0,0,0))
            p.insert_text((194,196),'26',fontsize=8)
            p.insert_text((176,227),'1',fontsize=8)
            with patch('voxel_mapper.drawing_views.screen_span',return_value={'status':'raster_consistent_candidate'}):r=page_references(p)
            self.assertEqual(r['references'][0]['target_view_key_candidate'],['2967',26,1])
            self.assertFalse(r['references'][0]['marker_semantics_verified'])
            p.insert_text((174,229),'2',fontsize=8)
            with patch('voxel_mapper.drawing_views.screen_span',return_value={'status':'raster_consistent_candidate'}):self.assertFalse(page_references(p)['references'])

    def test_catalogue_identity_never_clears_title_visibility_hold(self):
        with pymupdf.open() as doc:
            p=self.page(doc)
            with patch('voxel_mapper.drawing_views.screen_span',return_value={'status':'withheld'}):
                labels=page_labels(p,[{'id':'a','bbox_page_points':[40,40,280,200]}],sheet_metadata={'drawing_number':'2967-26'})
            self.assertEqual(labels['views'][0]['status'],'withheld_view_label_visibility')
            self.assertNotIn('view_key_candidate',labels['views'][0])
            self.assertFalse(labels['sheet_identity_candidate']['drawing_identity_verified'])
