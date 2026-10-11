from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from shapely.geometry import shape
from voxel_mapper.ordinary_surfaces import page_candidates, bridge_page
from voxel_mapper.reconstruction.model import Source
from voxel_mapper.reconstruction.registration import review_registration


class OrdinarySurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.pdf = self.root/'ordinary.pdf'
        self.make_pdf()
        scale = 100*.0254/72
        self.refs = []; groups = [[], []]
        self.surveys = {name: Source(name, 'survey', 'https://example.test/'+name, 'test',
            'EPSG:27700', 'ODN', 'accepted', char*64, {'physical_landmarks_verified': True})
            for name, char in [('control', '1'), ('check', '2')]}
        for i, (x, y) in enumerate([(20,20),(580,20),(20,580),(580,580),(300,300)]):
            role = 'control' if i < 3 else 'checkpoint'; name = 'control' if i < 3 else 'check'
            ref = {'id': 'P'+str(i), 'target': [x*scale,y*scale], 'source_id': name, 'role': role, 'accuracy_m': .1}
            self.refs.append(ref)
            groups[0 if i < 3 else 1].append({**ref, 'local': [x,y], 'source_sha256': self.surveys[name].sha256})
        self.alignment = review_registration(*groups, expected_scale=scale)
        sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.source = Source('drawing', 'planning', 'https://example.test/drawing', 'test',
            'EPSG:27700', 'ODN', sha256=sha, metadata={
                'semantic_annotation_contract': 'ordinary_surface_labels_v1', 'reuse_allowed': True,
                'drawing_state': 'existing', 'drawing_state_verified': True, 'state_verification_reference': 'fixture',
                'view_kind': 'horizontal_surface_plan', 'surface_label_scope_verified': True,
                'registration_document_sha256': sha, 'registration_page': 1,
                'registration_coordinate_frame': 'pdf_native_points_y_up',
                'local_landmark_identity_verified': True, 'horizontal_registration_review': self.alignment})

    def tearDown(self):
        self.tmp.cleanup()

    def make_pdf(self, mode='normal'):
        with pymupdf.open() as d:
            p = d.new_page(width=600, height=600)
            p.insert_text((10,590), 'Scale 1:100', fontsize=8)
            p.draw_rect(pymupdf.Rect(40,40,170,170))
            p.insert_text((65,75), 'stone', fontsize=8)
            p.insert_text((65,95), 'brick paving', fontsize=8)
            p.draw_rect(pymupdf.Rect(220,40,350,170))
            p.insert_text((240,75), 'stone paving', fontsize=8)
            p.insert_text((240,95), 'tarmac', fontsize=8)
            p.draw_rect(pymupdf.Rect(400,40,530,170))
            p.insert_text((420,75), 'Footpath', fontsize=8)
            p.draw_rect(pymupdf.Rect(40,230,170,360))
            p.insert_text((60,260), 'brick wall 0.80ht', fontsize=8)
            # An unlabelled rectangle must stay unclassified.
            p.draw_rect(pymupdf.Rect(220,230,350,360))
            if mode == 'nested':
                p.draw_rect(pymupdf.Rect(55,60,155,110))
            elif mode == 'hidden':
                p.draw_rect(pymupdf.Rect(55,60,155,110), fill=(1,1,1), color=None)
            elif mode == 'boundary_mask':
                p.draw_rect(pymupdf.Rect(38,38,44,172),fill=(1,1,1),color=None)
            elif mode == 'gap':
                p.draw_line((400,230),(500,230)); p.draw_line((500,230),(500,330))
                p.draw_line((500,330),(400,330)); p.draw_line((400,330),(400,240))
                p.insert_text((420,260), 'tarmac', fontsize=8)
            d.save(self.pdf)

    def page(self):
        with pymupdf.open(self.pdf) as d:
            return page_candidates(d[0], hashlib.sha256(self.pdf.read_bytes()).hexdigest(), 1)

    def bridge(self, source=None, refs=None):
        source = source or self.source
        return bridge_page(self.pdf, 1, source, refs or self.refs, {**self.surveys, source.id: source})

    def test_ordinary_labels_apply_polygon_rules_and_default_without_object_ids(self):
        rows, labels, report = self.page()
        self.assertEqual([r['surface'] for r in rows], ['brick', 'asphalt', 'stone'])
        self.assertEqual(len(labels), 5)
        self.assertEqual(report['surface_candidates'], 3)
        _, features, review = self.bridge()
        self.assertEqual(len(features), 3)
        self.assertTrue(all(f.family == 'paving' for f in features))
        self.assertEqual({f.parameters['surface']['value'] for f in features}, {'brick','asphalt','stone'})
        default = next(f for f in features if f.parameters['surface']['value'] == 'stone')
        self.assertEqual(default.metadata['material_origin'], 'user_default_stone_rule')
        self.assertEqual(review['world_geometry_additions'], 0)

    def test_nested_enclosures_are_ambiguous_and_gap_is_not_repaired(self):
        self.make_pdf('nested'); rows, labels, _ = self.page()
        self.assertTrue(any(r['status'] == 'withheld_ambiguous_enclosures' for r in labels))
        self.assertNotIn('brick', [r['surface'] for r in rows])
        self.pdf.unlink(); self.make_pdf('gap'); rows, labels, _ = self.page()
        self.assertTrue(any(r['text'] == 'tarmac' and r['status'] == 'withheld_no_enclosure' for r in labels))
        self.assertEqual(len(rows), 3)

    def test_hidden_labels_do_not_become_material_claims(self):
        self.pdf.unlink(); self.make_pdf('hidden')
        rows, labels, _ = self.page()
        self.assertNotIn('brick', [r['surface'] for r in rows])
        self.assertTrue(any(r['status'] in ('withheld_glyph_visibility','withheld_ambiguous_enclosures') for r in labels))

    def test_later_paint_erasing_boundary_cannot_become_paving(self):
        self.pdf.unlink(); self.make_pdf('boundary_mask')
        rows, _, report=self.page()
        self.assertNotIn('brick',[r['surface'] for r in rows])
        self.assertGreater(report['covered_boundaries_withheld'],0)

    def test_bad_sheet_scope_and_proposals_are_rejected(self):
        for changes in [{'view_kind': 'elevation'}, {'surface_label_scope_verified': False},
                        {'drawing_state': 'proposed'}, {'drawing_state_verified': False}]:
            with self.assertRaisesRegex(ValueError, 'surface-plan'):
                self.bridge(replace(self.source, metadata={**self.source.metadata, **changes}))

    def test_registration_requires_pinned_page_and_independent_references(self):
        for changes in [{'registration_page': 2}, {'registration_document_sha256': 'f'*64},
                        {'registration_coordinate_frame': 'mupdf_y_down'}, {'local_landmark_identity_verified': False}]:
            with self.assertRaisesRegex(ValueError, 'sheet landmark'):
                self.bridge(replace(self.source, metadata={**self.source.metadata, **changes}))
        refs = [{**r, 'target': [999,999]} if r['role'] == 'checkpoint' else r for r in self.refs]
        with self.assertRaisesRegex(ValueError, 'surveyed landmark'):
            self.bridge(refs=refs)

    def test_fit_is_recomputed_and_cannot_use_a_fabricated_accepted_matrix(self):
        alignment = {**self.alignment, 'matrix': [[100,0],[0,100]], 'translation_m': [999,999]}
        source = replace(self.source, metadata={**self.source.metadata, 'horizontal_registration_review': alignment})
        _, features, report = self.bridge(source)
        self.assertAlmostEqual(report['registration']['scale'], 100*.0254/72)
        self.assertLess(shape(features[0].geometry).bounds[2], 24)
        bad = {**self.alignment, 'checkpoint_pairs': [{**p, 'local': [p['local'][0]+100,p['local'][1]]} for p in self.alignment['checkpoint_pairs']]}
        with self.assertRaisesRegex(ValueError, 'registration failed'):
            self.bridge(replace(self.source, metadata={**self.source.metadata, 'horizontal_registration_review': bad}))

    def test_automatic_recipe_routes_ordinary_sheet_without_per_polygon_bindings(self):
        from voxel_mapper.automatic_reconstruction import prepare
        manifest = {'crs': 'EPSG:27700', 'vertical_datum': 'ODN', 'boundary': {'type': 'Polygon', 'coordinates': [[[0,0],[24,0],[24,24],[0,24],[0,0]]]},
                    'sources': [self.source.__dict__]+[s.__dict__ for s in self.surveys.values()]}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        (self.root/'references.json').write_text(json.dumps({'landmarks': self.refs}))
        (self.root/'terrain.json').write_text('{}')
        work = self.root/'area'; files = work/'corpus/files'; files.mkdir(parents=True)
        (files/(self.source.sha256+'.pdf')).write_bytes(self.pdf.read_bytes())
        config = {'automatic_reconstruction': {'manifest': 'manifest.json', 'references': 'references.json', 'terrain_config': 'terrain.json'}}
        recipe, report = prepare(config, {'bounds': [0,0,24,24], 'bounds_crs': 'EPSG:27700'}, lambda p: self.root/p, work, {self.source.sha256})
        self.assertEqual(report['feature_count'], 3)
        self.assertEqual(report['status'], 'recipe_ready')
        self.assertTrue(recipe.exists())
        self.assertEqual(prepare(config, {'bounds': [0,0,24,24], 'bounds_crs': 'EPSG:27700'}, lambda p: self.root/p, work, {self.source.sha256}), (recipe, report))

    def test_ordinary_recipes_publish_native_polygon_materials(self):
        import amulet
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from voxel_mapper.bedrock import export_world, material_block
        from voxel_mapper.paving_palette import palette_block
        from voxel_mapper.generation_cycles import file_hash
        from voxel_mapper.area_cycles import run_local
        raster=self.root/'terrain.tif'
        with rasterio.open(raster,'w',driver='GTiff',height=64,width=64,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(-16,48,1,1)) as dst:
            dst.write(np.zeros((64,64),dtype='float32'),1)
        (self.root/'terrain.json').write_text(json.dumps({'terrain':{'path':str(raster),'units':'m','vertical_datum':'ODN','source_id':'terrain'},'sources':[{'id':'terrain'}]}))
        manifest={'crs':'EPSG:27700','vertical_datum':'ODN','terrain_sha256':file_hash(raster),
                  'boundary':{'type':'Polygon','coordinates':[[[0,0],[24,0],[24,24],[0,24],[0,0]]]},
                  'sources':[self.source.__dict__]+[s.__dict__ for s in self.surveys.values()]}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        (self.root/'refs.json').write_text(json.dumps({'landmarks':self.refs}))
        sources=self.root/'sources'; sources.mkdir()
        (sources/(self.source.sha256+'.pdf')).write_bytes(self.pdf.read_bytes())
        (self.root/'catalogue.json').write_text(json.dumps({'entries':[{'applicationReference':'A','url':self.source.url,'sha256':self.source.sha256}]}))
        base=self.root/'base'; base.mkdir(); cells=base/'voxels.jsonl'
        cells.write_text(''.join(json.dumps({'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'})+'\n' for x in range(24) for z in range(24)))
        quality={'voxel_size_m':1,'sources':[],'crs':'EPSG:27700','axis':{},'limitations':[]}
        quality['world']=export_world(cells,base,quality)
        (base/'quality-report.json').write_text(json.dumps(quality)); offset=quality['world']['vertical_offset_blocks']
        job={'work_directory':'resort','catalogue':'catalogue.json','official_hosts':['example.test'],'offline':True,'source_directories':['sources'],
             'initial_base_world':'base','initial_base_sha256':file_hash(base/'park.mcworld'),
             'automatic_reconstruction':{'enabled':True,'manifest':'manifest.json','references':'refs.json','terrain_config':'terrain.json'},
             'areas':[{'id':'a','name':'A','application_references':['A'],'bounds':[0,0,24,24],'bounds_crs':'EPSG:27700','required_families':['paving']}]}
        path=self.root/'job.json'; path.write_text(json.dumps(job))
        result=run_local(path,max_cycles=2)
        self.assertEqual(result['published_cycles'],1,result)
        self.assertEqual(result['areas']['a']['status'],'partial_area_preview')
        world=amulet.load_level(str(self.root/'resort/a/completed-base/bedrock-world'))
        try:
            for x,surface in [(3,'brick'),(9,'asphalt'),(16,'stone')]:
                self.assertEqual(world.get_block(x,offset,-18,'minecraft:overworld'),material_block(palette_block(surface,x,18)))
                self.assertEqual(world.get_block(x,offset-1,-18,'minecraft:overworld').base_name,'grass_block')
            self.assertEqual(world.get_block(9,offset,-10,'minecraft:overworld').base_name,'air')
        finally: world.close()

    def test_audit_is_pinned_resumable_and_never_claims_world_features(self):
        from voxel_mapper.ordinary_surfaces import audit
        inputs=self.root/'documents.json'
        inputs.write_text(json.dumps([{'file':'ordinary.pdf','sha256':self.source.sha256,'title':'ordinary fixture'}]))
        output=self.root/'audit'
        report=audit(inputs,output,max_pages=1)
        self.assertEqual(report['surface_candidates'],3)
        self.assertEqual(report['registered_features'],0)
        self.assertEqual(report['world_geometry_additions'],0)
        self.assertEqual(audit(inputs,output,max_pages=1),report)
        (output/'labels.jsonl').write_text('changed')
        with self.assertRaisesRegex(ValueError,'output changed'):
            audit(inputs,output,max_pages=1)

    def test_disjoint_labels_in_one_cad_span_keep_separate_glyph_ranges(self):
        from voxel_mapper.ordinary_surfaces import label_runs
        with pymupdf.open(self.pdf) as document:
            spans=document[0].get_texttrace()
            a=next(s for s in spans if ''.join(chr(c[0]) for c in s['chars'])=='stone')
            b=next(s for s in spans if ''.join(chr(c[0]) for c in s['chars'])=='tarmac')
            joined={**a,'chars':list(a['chars'])+list(b['chars'])}
            runs=label_runs([joined])
            self.assertEqual([''.join(chr(c[0]) for c in r['chars']) for r in runs],['stone','tarmac'])
            self.assertTrue(set(runs[0]['character_indices']).isdisjoint(runs[1]['character_indices']))
