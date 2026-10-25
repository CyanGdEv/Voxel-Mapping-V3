"""Independent original-PDF shared positions, exact source geometry and honest graph."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import shape

from voxel_mapper import architectural_graph, architectural_view_layout, ordinary_surfaces
from voxel_mapper import planning_outline_semantics as semantics
from voxel_mapper import planning_component_footprints as components
from voxel_mapper import planning_area_layout as area
from voxel_mapper import planning_surface_footprints as surfaces
from voxel_mapper.building_spec import digest


def fixture(*, second_caption=False, hidden_caption=False, caption='Proposed Ground Floor Plan | 1:100',
            rotation=0, unit=None, crop=False, paper=False, container=False):
    doc = pymupdf.open(); page = doc.new_page(width=700, height=500)
    for bounds, label, point in [((100,100,180,180), 'Container' if container else 'Building', (110,125)),
        ((180,130,300,160), 'Path', (210,150)), ((300,100,400,190), 'Plaza', (325,130)),
        ((460,100,540,180), 'Shop', (480,125))]:
        page.draw_rect(bounds)
        page.insert_text(point, label, fontsize=8)
    page.insert_text((70,400), caption, fontsize=10)
    if second_caption: page.insert_text((70,440), 'Proposed Roof Plan | 1:100', fontsize=10)
    if hidden_caption: page.draw_rect((65,385,360,410), fill=(1,1,1), color=None)
    if paper: page.insert_text((70,470), '1:100 @ A1', fontsize=8)
    if unit: doc.xref_set_key(page.xref, 'UserUnit', str(unit))
    if crop: page.set_cropbox(pymupdf.Rect(0,0,690,500))
    page.set_rotation(rotation)
    sha = hashlib.sha256(doc.tobytes()).hexdigest()
    graph = architectural_graph.build([]); graph.update(document_sha256=sha, page=1)
    layout = architectural_view_layout.review(page, sha, 1, graph)
    _, _, report = ordinary_surfaces.page_candidates(page, sha, 1)
    inventory = report['source_outline_inventory']
    assoc = semantics.page_candidates(page, sha, 1, inventory)
    fine = components.page_candidates(page, sha, 1, inventory, assoc)
    records = {r['candidate_id']:r for r in inventory['records']}
    labels = {r['id']:r for r in assoc['labels']}
    pack = {'version':surfaces.VERSION, 'document_sha256':sha, 'page':1,
        'source_inventory_sha256':digest(inventory), 'source_associations_sha256':digest(assoc),
        'analysis_complete':True, 'candidates':[]}
    for a in assoc['outlines']:
        if a['status']=='visible_label_enclosure_hint' and a['source_role_hint'] in ('path','plaza'):
            record = records[a['candidate_id']]
            pack['candidates'].append({'id':digest([surfaces.VERSION,sha,1,record['candidate_id'],sorted(a['label_ids'])]), 'document_sha256':sha, 'page':1,
                'coordinate_frame':area.FRAME, 'geometry_pdf_native':record['candidate']['geometry'],
                'source_outline':record, 'labels':[labels[k] for k in a['label_ids']],
                'source_role_hint':a['source_role_hint'], 'surface':'stone', 'material_basis':'user stone default on labelled surface'})
    return doc, page, sha, 1, layout, inventory, assoc, fine, pack


def signed(result):
    result['id']=digest({k:v for k,v in result.items() if k!='id'})
    return result


class AreaLayoutTests(unittest.TestCase):
    def source(self, **kwargs):
        doc, *rest=fixture(**kwargs); self.addCleanup(doc.close)
        return rest

    def run_page(self, **kwargs):
        args=self.source(**kwargs)
        return area.page_layout(*args), args

    def test_shared_frame_preserves_distinct_building_path_plaza_positions_and_contacts(self):
        result,args=self.run_page()
        self.assertEqual(result['summary']['nominal_area_building_candidates'],2)
        self.assertEqual(result['summary']['nominal_area_path_plaza_candidates'],2)
        self.assertEqual(result['summary']['nominal_area_boundary_contacts'],2)
        rows=result['candidates']; factor=100*.0254/72
        buildings=sorted((r for r in rows if r['role']=='building'),key=lambda r:r['nominal_bounds_m'][0])
        self.assertAlmostEqual(buildings[0]['nominal_bounds_m'][0],100*factor)
        self.assertAlmostEqual(buildings[1]['nominal_bounds_m'][0],460*factor)
        self.assertAlmostEqual(buildings[1]['nominal_bounds_m'][0]-buildings[0]['nominal_bounds_m'][0],360*factor)
        self.assertEqual(result['shared_frame']['origin_pdf_native'],[0.,0.])
        self.assertEqual(area.validate_layout(result),result)
        self.assertFalse(result['world_placement_eligible'])
        self.assertIsNone(result['physical_traversability'])
        self.assertTrue(all(r['height_m'] is None for r in rows))
        self.assertTrue(all(r['traversable'] is None for r in result['relations']))
        self.assertTrue(any(r['gap_m']>0 for r in result['relations']))
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertEqual(result['training_labels_generated'],0)
        self.assertFalse(result['model_weights_updated'])
        # Source geometry and all caller-owned evidence remain unchanged.
        before=copy.deepcopy(args[3:]); area.page_layout(*args)
        self.assertEqual(args[3:],before)

    def test_fine_and_coarse_same_component_boundary_merge_without_duplicate_building(self):
        result,_=self.run_page(container=True)
        self.assertEqual(result['summary']['nominal_area_building_candidates'],2)
        row=next(r for r in result['candidates'] if len(r['source_evidence'])==2)
        self.assertEqual({e['kind'] for e in row['source_evidence']},{'coarse_building','fine_building'})
        area.validate_layout(result)

    def test_rotation_does_not_recentre_individual_objects(self):
        baseline,_=self.run_page()
        for rotation in (90,180,270):
            with self.subTest(rotation=rotation):
                result,_=self.run_page(rotation=rotation)
                self.assertEqual(sorted((r['role'],r['nominal_bounds_m']) for r in result['candidates']),
                    sorted((r['role'],r['nominal_bounds_m']) for r in baseline['candidates']))
                area.validate_layout(result)

    def test_site_plan_title_can_supply_single_inline_nominal_context(self):
        result,_=self.run_page(caption='Proposed Site Plan | 1:100')
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(len(result['candidates']),4)

    def test_multiple_contexts_hidden_missing_scale_roof_or_paper_changes_withhold_geometry(self):
        for kwargs in ({'second_caption':True},{'hidden_caption':True},
            {'caption':'Proposed Ground Floor Plan'}, {'caption':'Proposed Roof Plan | 1:100'},
            {'caption':'Proposed First Floor Plan | 1:100'}, {'unit':2},{'crop':True},{'paper':True}):
            with self.subTest(kwargs=kwargs):
                result,_=self.run_page(**kwargs)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['candidates'],[])
                self.assertIsNone(result['shared_frame'])
                area.validate_layout(result)

    def test_missing_or_incomplete_page_evidence_remains_an_explicit_hold(self):
        args=self.source()
        for index in (3,4,5):
            bad=list(args);bad[index]=None
            r=area.page_layout(*bad);self.assertFalse(r['analysis_complete']);area.validate_layout(r)
        for index,key in ((4,'inventory_complete'),(5,'inventory_complete'),(6,'analysis_complete'),(7,'analysis_complete')):
            bad=copy.deepcopy(args[1:]);bad[index-1][key]=False
            # Refresh dependent hashes to represent legitimate incomplete upstream output.
            bad[4]['source_inventory_sha256']=digest(bad[3])
            for pack in bad[5:]:
                pack['source_inventory_sha256']=digest(bad[3]);pack['source_associations_sha256']=digest(bad[4])
            r=area.page_layout(args[0],*bad);self.assertFalse(r['analysis_complete'])

    def test_nominal_geometry_or_relation_tampering_is_rejected_even_after_resigning(self):
        result,_=self.run_page()
        for change in ('geometry','affine','source','relation','summary','height','identity','scale','status','accuracy','extra'):
            with self.subTest(change=change):
                bad=json.loads(json.dumps(result))
                if change=='geometry':bad['candidates'][0]['geometry_nominal_local']['coordinates'][0][0][0]+=1
                elif change=='affine':bad['shared_frame']['native_to_nominal_local_affine'][4]+=2
                elif change=='source':bad['candidates'][0]['source_evidence'][0]['source_outline']['source_record_sha256']='0'*64
                elif change=='relation':bad['relations'][0]['traversable']=True
                elif change=='summary':bad['summary']['registered_area_layouts']=1
                elif change=='identity':bad['candidates'][0]['physical_identity_verified']=True
                elif change=='scale':bad['candidates'][0]['physical_scale_verified']=True
                elif change=='status':bad['status']='physically_complete_area_reconstruction'
                elif change=='accuracy':bad['geometric_accuracy']=.99
                elif change=='extra':bad['reconstructed_buildings']=20
                else:bad['candidates'][0]['height_m']=3
                with self.assertRaises(ValueError):area.validate_layout(signed(bad))

    def test_resigned_role_surface_and_state_changes_cannot_override_visible_source_labels(self):
        result,_=self.run_page()
        for change in ('role','surface','state'):
            with self.subTest(change=change):
                bad=copy.deepcopy(result)
                row=next(r for r in bad['candidates'] if r['role']=='path')
                if change=='role':row['role']='building'
                elif change=='surface':row['surface']='asphalt'
                else:row['printed_state']='existing'
                row['id']=area._row_id(bad['document_sha256'],bad['page'],row)
                bad['relations']=area._relations(bad['candidates'],8192,lambda:None)
                bad['summary']=area._summary(bad)
                with self.assertRaises(ValueError):area.validate_layout(signed(bad))

    def test_mismatched_source_pack_and_changed_polygon_fail_before_usable_layout(self):
        args=self.source()
        bad=copy.deepcopy(args[1:]);bad[-1]['page']=2
        with self.assertRaises(ValueError):area.page_layout(args[0],*bad)
        bad=json.loads(json.dumps(args[1:]));bad[-1]['candidates'][0]['geometry_pdf_native']['coordinates'][0][0][0]+=1
        with self.assertRaises(ValueError):area.page_layout(args[0],*bad)

    def test_candidate_point_pair_output_budgets_and_cancellation_publish_no_partial_layout(self):
        args=self.source()
        for options in ({'max_candidates':1},{'max_points':1},{'max_pair_checks':1},{'max_output_bytes':16384}):
            with self.subTest(options=options):
                r=area.page_layout(*args,options=options)
                self.assertFalse(r['analysis_complete']);self.assertEqual(r['candidates'],[])
                area.validate_layout(r)
        with self.assertRaises(CancelledError):area.page_layout(*args,cancelled=lambda:True)
        for options in ({'bad':2},{'max_candidates':True},{'max_points':100001}):
            with self.assertRaises(ValueError):area.page_layout(*args,options=options)

    def test_review_json_svg_and_downloadable_geojson_preserve_holes_positions_and_pins(self):
        result,_=self.run_page()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review=area.write_review(root,[result])
            self.assertEqual(review,json.loads((root/'area-layouts.json').read_text()))
            self.assertIn('<svg',(root/'area-layouts.html').read_text())
            self.assertIn('Contacts do not establish traversable entrances',(root/'area-layouts.html').read_text())
            entry=review['page_layout_files'][0]
            self.assertEqual(entry['id'],result['id']);self.assertEqual(entry['candidate_count'],4)
            self.assertEqual(json.loads((root/entry['file']).read_text()),result)
            geo=json.loads((root/entry['geojson_file']).read_text())
            self.assertEqual(len(geo['features']),4)
            self.assertIsNone(geo['geographic_registration'])
            self.assertTrue(all(f['properties']['height_m'] is None for f in geo['features']))
            for name,sha in review['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),sha)
            with self.assertRaises(ValueError):area.write_review(root,[result,result])
            with self.assertRaises(CancelledError):area.write_review(root,[],cancelled=lambda:True)


if __name__=='__main__':unittest.main()
