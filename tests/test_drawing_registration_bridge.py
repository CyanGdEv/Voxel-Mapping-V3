from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from shapely.geometry import box
from voxel_mapper.drawing_registration_bridge import bridge_page,run
from voxel_mapper.reconstruction.model import Source
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.park_generators import park_registry


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.pdf=self.root/'source.pdf'
        self.make_pdf()
        metadata={'reuse_allowed':True,'drawing_state':'as_built','drawing_state_verified':True,
                  'state_verification_reference':'fixture record','semantic_annotation_contract':'explicit_object_leader_v1',
                  'semantic_annotation_identity_verified':True,'vertical_datum_verified':True}
        self.source=Source('drawing','cad','https://example.test/drawing','test','EPSG:27700','ODN',sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest(),metadata=metadata)
        control=Source('control','survey','https://example.test/control','test','EPSG:27700','ODN','accepted','1'*64,{'physical_landmarks_verified':True})
        checkpoint=Source('check','survey','https://example.test/check','test','EPSG:27700','ODN','accepted','2'*64,{'physical_landmarks_verified':True})
        self.sources={s.id:s for s in [self.source,control,checkpoint]}
        self.refs=[{'id':name,'target':[x*100*.0254/72,y*100*.0254/72],'source_id':'control' if i<3 else 'check','role':'control' if i<3 else 'checkpoint','accuracy_m':.1}
                   for i,(name,x,y) in enumerate([('A',50,50),('B',550,50),('C',50,550),('D',550,550),('E',300,300)])]

    def tearDown(self):self.tmp.cleanup()

    def make_pdf(self,extra='',leader=True):
        writer=PdfWriter();p=writer.add_blank_page(600,600)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        lines=['BT /F1 8 Tf 1 0 0 1 10 10 Tm (Scale 1:100) Tj ET']
        def label(text,x,y,mx,my):
            lines.append(f'BT /F1 8 Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET')
            if leader:lines.append(f'{x} {y} m {mx} {my} l S')
            lines.extend([f'{mx-3} {my} m {mx+3} {my} l S',f'{mx} {my-3} m {mx} {my+3} l S'])
        for name,x,y in [('A',50,50),('B',550,50),('C',50,550),('D',550,550),('E',300,300)]: label('CP:'+name,x+10,y+10,x,y)
        lines.extend(['200 200 60 40 re S','350 350 40 40 re S','400 100 40 40 re S'])
        label('PATH:P1 surface=asphalt',200,180,230,220)
        label('WALL:W1 height_m=2 material=stone_bricks',350,320,370,370)
        label('ROOF:R1 elevation_m=4 slope_x=0.5 slope_y=0 thickness_m=0.5 material=stone',300,80,420,120)
        if extra:lines.append(extra)
        stream=DecodedStreamObject();stream.set_data('\n'.join(lines).encode());p[NameObject('/Contents')]=writer._add_object(stream)
        with self.pdf.open('wb') as out:writer.write(out)

    def test_native_pdf_auto_pairs_and_builds_path_wall_and_sloped_roof(self):
        source,features,report=bridge_page(self.pdf,1,self.source,self.refs,self.sources)
        self.assertEqual(report['registration']['status'],'accepted_horizontal_fit')
        self.assertEqual({f.family for f in features},{'path','wall','roof_surface'})
        ctx=Context({**self.sources,source.id:source},lambda *p:0,box(0,0,24,24),'ODN')
        rows,compiled=ReconstructionEngine(park_registry()).plan(features,ctx)
        self.assertTrue(all(d['status']=='planned' for d in compiled['decisions']),compiled)
        roof=next(f for f in features if f.family=='roof_surface')
        roof_rows=[r for r in rows if r['feature']==roof.id]
        self.assertGreater(len({r['y'] for r in roof_rows}),1)
        self.assertEqual(report['world_geometry_additions'],0)

    def test_missing_and_reused_checkpoint_sources_withheld(self):
        with self.assertRaisesRegex(ValueError,'two separately sourced'):
            bridge_page(self.pdf,1,self.source,self.refs[:3],self.sources)
        refs=[{**r,'source_id':'control'} for r in self.refs]
        with self.assertRaisesRegex(ValueError,'reuse control source'):
            bridge_page(self.pdf,1,self.source,refs,self.sources)
        aliases={**self.sources,'check':replace(self.sources['check'],sha256='1'*64)}
        with self.assertRaisesRegex(ValueError,'reuse control source'):
            bridge_page(self.pdf,1,self.source,self.refs,aliases)

    def test_proposal_semantics_not_promoted(self):
        source=replace(self.source,metadata={**self.source.metadata,'drawing_state':'proposed'})
        with self.assertRaisesRegex(ValueError,'existing/as-built'):bridge_page(self.pdf,1,source,self.refs,self.sources)

    def test_unverified_vertical_datum_withholds_roof_only(self):
        source=replace(self.source,metadata={**self.source.metadata,'vertical_datum_verified':False})
        _,features,report=bridge_page(self.pdf,1,source,self.refs,self.sources)
        self.assertEqual({f.family for f in features},{'path','wall'})
        self.assertTrue(any(d['status']=='withheld' and 'vertical datum' in d['reason'] for d in report['semantic_decisions']))

    def test_wrong_crs_and_poor_reference_accuracy_rejected(self):
        sources={**self.sources,'check':replace(self.sources['check'],crs='EPSG:32630')}
        with self.assertRaisesRegex(ValueError,'CRS mismatch'):bridge_page(self.pdf,1,self.source,self.refs,sources)
        refs=[{**r,'accuracy_m':.6} for r in self.refs]
        with self.assertRaisesRegex(ValueError,'error.*budget'):bridge_page(self.pdf,1,self.source,refs,self.sources)

    def test_disagreement_scale_and_ambiguous_geometry_rejected(self):
        refs=[{**r,'target':[r['target'][0]+(2 if r['id']=='D' else 0),r['target'][1]]} for r in self.refs]
        with self.assertRaisesRegex(ValueError,'registration failed'):bridge_page(self.pdf,1,self.source,refs,self.sources)
        self.make_pdf('BT /F1 8 Tf 1 0 0 1 10 20 Tm (Scale 1:200) Tj ET')
        source=replace(self.source,sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError,'unambiguous printed scale'):bridge_page(self.pdf,1,source,self.refs,self.sources)

    def test_no_nearest_mark_snapping(self):
        self.make_pdf(leader=False);source=replace(self.source,sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError,'unique explicit leader'):bridge_page(self.pdf,1,source,self.refs,self.sources)

    def test_missing_registration_writes_auditable_empty_bridge(self):
        manifest={'crs':'EPSG:27700','vertical_datum':'ODN','sources':[s.__dict__ for s in self.sources.values()]}
        (self.root/'manifest.json').write_text(json.dumps(manifest));(self.root/'refs.json').write_text(json.dumps({'landmarks':self.refs[:3]}))
        report=run(self.pdf,1,self.root/'manifest.json',self.root/'refs.json','drawing',self.root/'bridge')
        self.assertEqual(report['status'],'withheld');self.assertEqual((self.root/'bridge/features.jsonl').read_text(),'')
        self.assertEqual(report['feature_count'],0)

    def batch_inputs(self,refs=None):
        (self.root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','vertical_datum':'ODN','boundary':box(0,0,24,24).__geo_interface__,'sources':[s.__dict__ for s in self.sources.values()]}))
        (self.root/'refs.json').write_text(json.dumps({'landmarks':self.refs if refs is None else refs}))
        (self.root/'documents.json').write_text(json.dumps([{'file':'source.pdf','source_id':'drawing'}]))
        return self.root/'documents.json',self.root/'manifest.json',self.root/'refs.json'

    def test_batch_page_sources_cache_and_tamper_detection(self):
        from voxel_mapper.drawing_registration_bridge import run_batch
        inputs=self.batch_inputs();output=self.root/'batch'
        report=run_batch(*inputs,output)
        self.assertEqual(report['feature_count'],3)
        manifest=json.loads((output/'manifest.json').read_text())
        self.assertEqual(manifest['sources'][-1]['id'],'drawing/page-1')
        self.assertEqual(manifest['sources'][0]['registration_status'],self.source.registration_status)
        features=[json.loads(line) for line in (output/'features.jsonl').read_text().splitlines()]
        self.assertTrue(all(f['geometry_source']=='drawing/page-1' for f in features))
        self.assertEqual(run_batch(*inputs,output),report)
        (output/'features.jsonl').write_text('')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):run_batch(*inputs,output)

    def test_batch_changed_inputs_and_manifest_crs_rejected(self):
        from voxel_mapper.drawing_registration_bridge import run_batch
        inputs=self.batch_inputs();output=self.root/'batch';run_batch(*inputs,output)
        inputs[2].write_text(json.dumps({'landmarks':self.refs[:3]}))
        with self.assertRaisesRegex(ValueError,'inputs changed'):run_batch(*inputs,output)
        manifest=json.loads(inputs[1].read_text());manifest['crs']='EPSG:32630';inputs[1].write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'manifest CRS'):run_batch(*inputs,self.root/'wrong-crs')

    def test_pipeline_withheld_bridge_does_not_compile(self):
        from voxel_mapper.park_pipeline import run as pipeline
        self.batch_inputs(self.refs[:3])
        job={'manifest':'manifest.json','work_directory':'job','registration_bridge':{'enabled':True,'documents':'documents.json','references':'refs.json'}}
        (self.root/'job.json').write_text(json.dumps(job))
        state=pipeline(self.root/'job.json','compile')
        self.assertEqual(state['stages']['reconstruction']['status'],'awaiting_normalized_geometry')
        self.assertFalse((self.root/'job/geometry.sqlite').exists())

    def test_pdf_through_pipeline_and_cumulative_native_cycles(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        import amulet,zipfile
        from voxel_mapper.bedrock import export_world,material_block
        from voxel_mapper.park_pipeline import run as pipeline
        from voxel_mapper.generation_cycles import CyclePlan
        from voxel_mapper.generation_cycle_export import run as generate
        self.batch_inputs()
        raster=self.root/'terrain.tif'
        with rasterio.open(raster,'w',driver='GTiff',height=32,width=32,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,32,1,1)) as dst:dst.write(np.zeros((32,32),dtype=np.float32),1)
        manifest=json.loads((self.root/'manifest.json').read_text());manifest['terrain_sha256']=hashlib.sha256(raster.read_bytes()).hexdigest()
        (self.root/'manifest.json').write_text(json.dumps(manifest))
        (self.root/'terrain.json').write_text(json.dumps({'terrain':{'path':str(raster),'vertical_datum':'ODN','units':'m','source_id':'terrain'},'sources':[{'id':'terrain'}]}))
        base=self.root/'base';base.mkdir();data=base/'voxels.jsonl'
        data.write_text(''.join(json.dumps({'x':x,'y':0,'z':z,'kind':'structure','material':'stone'})+'\n' for x in [0,16] for z in [1,17]))
        quality={'voxel_size_m':1,'sources':[],'crs':'EPSG:27700','axis':{},'limitations':[]}
        quality['world']=export_world(data,base,quality);(base/'quality-report.json').write_text(json.dumps(quality))
        job={'manifest':'manifest.json','terrain_config':'terrain.json','base_world':'base','work_directory':'job',
             'registration_bridge':{'enabled':True,'documents':'documents.json','references':'refs.json'}}
        (self.root/'job.json').write_text(json.dumps(job))
        state=pipeline(self.root/'job.json','compile')
        self.assertGreater(state['stages']['reconstruction']['unique_voxel_cells'],0)
        self.assertEqual(state['stages']['registration_bridge']['feature_count'],3)
        geometry=self.root/'job/geometry.sqlite'
        plan=CyclePlan.create(self.root/'cycles.sqlite',geometry,base,[[x,z] for x in range(2) for z in [-2,-1]],sections=1,batch_chunks=1,workers=2,terrain_config=self.root/'terrain.json')
        try:result=generate(plan,geometry,base,self.root/'world',max_cycles=4,terrain_config=self.root/'terrain.json')
        finally:plan.close()
        self.assertEqual(result['progress']['status'],'complete')
        package=self.root/'world'/result['previews'][-1]['file'];target=self.root/'read'
        with zipfile.ZipFile(package) as archive:archive.extractall(target)
        world=amulet.load_level(str(target))
        try:
            offset=quality['world']['vertical_offset_blocks']
            self.assertEqual(world.get_block(8,offset,-7,'minecraft:overworld'),material_block('gray_concrete'))
            self.assertEqual(world.get_block(12,offset+1,-13,'minecraft:overworld'),material_block('stone_bricks'))
            self.assertEqual(world.get_block(14,offset+3,-4,'minecraft:overworld'),material_block('stone'))
            self.assertEqual(world.get_block(15,offset+4,-4,'minecraft:overworld'),material_block('stone'))
        finally:world.close()

    def test_invisible_or_layered_labels_are_not_registration_evidence(self):
        for extra in ['3 Tr','/Hidden BMC EMC']:
            self.make_pdf(extra);source=replace(self.source,sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError,'Invisible or layered'):
                bridge_page(self.pdf,1,source,self.refs,self.sources)
