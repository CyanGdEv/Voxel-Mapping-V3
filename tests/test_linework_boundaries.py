import json
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import LineString,box,mapping,shape
from voxel_mapper.linework_boundaries import recover_page,run
from voxel_mapper.drawing_geometry import VERSION as PARENT_VERSION


class LineworkTests(unittest.TestCase):
    def parents(self,rings):
        rows=[]
        import hashlib
        for ring in rings:
            for a,b in zip(ring,ring[1:]):
                g=LineString([a,b]);rows.append({'id':hashlib.sha256(('a'*64+'/1/'+g.normalize().wkb_hex).encode()).hexdigest(),'document_sha256':'a'*64,'page':1,'geometry':mapping(g),'coordinate_frame':'pdf_native_points_y_up','extraction_kind':'drawing_geometry','extraction_version':PARENT_VERSION,'extraction_contract':'b'*64,'paint_references':[{'ordinal':len(rows),'stroke_style':{'dashes_pdf':'[] 0','width_pdf_points':1}}],'curve_approximation':{'cubic_segments':0,'chord_error_bound_pdf_points':0},'rendering_status':'supported_straight_unclipped_polyline'})
        return rows

    def test_separate_strokes_recover_face_and_exact_parent_provenance(self):
        parents=self.parents([list(box(10,10,40,30).exterior.coords)]);records,report=recover_page(parents);faces=[r for r in records if r['extraction_kind']=='linework_boundaries']
        self.assertEqual(report['recovered_faces'],1);self.assertTrue(shape(faces[0]['geometry']).equals(box(10,10,40,30)))
        self.assertEqual({p['candidate_id'] for p in faces[0]['line_parent_references']},{p['id'] for p in parents});self.assertFalse(faces[0]['physical_identity_verified'])
        from voxel_mapper.drawing_footprints import reviewed_feature
        with self.assertRaisesRegex(ValueError,'explicit linework'):reviewed_feature(faces[0],{},None,{},'EPSG:27700')

    def test_nested_rings_preserve_annulus_hole_without_claiming_fill(self):
        p=self.parents([list(box(0,0,100,100).exterior.coords),list(box(20,20,80,80).exterior.coords)]);r,report=recover_page(p);faces=[shape(c['geometry']) for c in r if c['extraction_kind']=='linework_boundaries']
        self.assertEqual(report['recovered_faces'],2);self.assertEqual(sorted(len(g.interiors) for g in faces),[0,1]);self.assertAlmostEqual(sum(g.area for g in faces),10000)

    def test_tiny_gap_dashes_and_curves_do_not_invent_closure(self):
        ring=list(box(10,10,40,30).exterior.coords);ring[-1]=(ring[-1][0]-.00001,ring[-1][1]);p=self.parents([ring]);self.assertEqual(recover_page(p)[1]['recovered_faces'],0)
        p=self.parents([list(box(10,10,40,30).exterior.coords)]);p[0]['paint_references'][0]['stroke_style']['dashes_pdf']='[1 2] 0';self.assertEqual(recover_page(p)[1]['recovered_faces'],0)
        p[0]['paint_references'][0]['stroke_style']['dashes_pdf']='[] 0';p[0]['curve_approximation']['cubic_segments']=1;self.assertEqual(recover_page(p)[1]['recovered_faces'],0)

    def test_dense_network_budget_withholds_recovery_but_keeps_components(self):
        p=self.parents([list(box(10,10,40,30).exterior.coords)]);records,report=recover_page(p,recovery_options={'max_intersection_pairs':1})
        self.assertEqual(report['status'],'network_budget_withheld');self.assertEqual(len(records),4)
        with self.assertRaises(ValueError):recover_page(p,recovery_options={'max_segments':True})

    def test_intersections_node_original_edges_and_keep_coverage(self):
        p=self.parents([list(box(10,10,50,50).exterior.coords),[(30,10),(30,50)]]);r,report=recover_page(p);faces=[shape(c['geometry']) for c in r if c['extraction_kind']=='linework_boundaries']
        self.assertEqual(report['recovered_faces'],2);self.assertAlmostEqual(sum(g.area for g in faces),1600)

    def test_actual_pdf_retained_recompute_resume_tamper_and_placement(self):
        import pymupdf
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.footprint_matching import NativeNames,references
        from voxel_mapper.mapped_sheet_placement import run as place
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c=Corpus(root/'corpus');doc=pymupdf.open();page=doc.new_page(width=400,height=600)
            polygons=[box(20,20,50,40),box(110,30,150,60),box(40,120,65,155)]
            for g in polygons:
                for a,b in zip(g.exterior.coords,list(g.exterior.coords)[1:]):page.draw_line(pymupdf.Point(a[0],600-a[1]),pymupdf.Point(b[0],600-b[1]))
            data=doc.tobytes();doc.close()
            try:
                c.ingest([{'url':'https://portal.test/a','title':'Plan'}],['portal.test']);c.acquire(fetch=lambda _:data);extract(c,root/'geometry')
                feed=root/'geometry/geometry-candidates.jsonl';args=(c,feed,root/'boundaries');receipt=run(*args);self.assertEqual(receipt['counts']['recovered_faces'],3);self.assertEqual(run(*args),receipt)
                reordered=root/'reordered.jsonl';reordered.write_text('\n'.join(reversed(feed.read_text().splitlines()))+'\n')
                self.assertEqual(run(c,reordered,root/'reordered-output')['output_sha256'],receipt['output_sha256'])
                records=[json.loads(x) for x in (root/'boundaries/boundary-candidates.jsonl').read_text().splitlines()];faces=[r for r in records if r['extraction_kind']=='linework_boundaries'];names=NativeNames(c,[])
                try:
                    names.get(faces[0]);forged={**faces[0],'line_parent_references':[]}
                    with self.assertRaisesRegex(ValueError,'differs'):names.get(forged)
                finally:names.close()
                from shapely.affinity import translate
                refs=root/'refs';refs.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','id':str(i),'geometry':mapping(translate(g,1000,2000)),'properties':{}} for i,g in enumerate(polygons)]}))
                report=place(root/'boundaries/boundary-candidates.jsonl',refs,'EPSG:27700','EPSG:27700',root/'placement',c);self.assertEqual(report['counts']['provisional_mapped_placement'],1)
                self.assertEqual(place(root/'boundaries/boundary-candidates.jsonl',refs,'EPSG:27700','EPSG:27700',root/'placement',c),report)
                from voxel_mapper.park_pipeline import run as park
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'linework_boundaries':{'enabled':True},'mapped_placement':{'enabled':True,'references':'refs','reference_crs':'EPSG:27700','target_crs':'EPSG:27700'}}))
                first=park(job,'acquire');self.assertEqual(first['stages']['linework_boundaries']['counts']['recovered_faces'],3);self.assertEqual(first['stages']['mapped_placement']['counts']['provisional_mapped_placement'],1)
                self.assertEqual(park(job,'acquire')['stages']['mapped_placement'],first['stages']['mapped_placement'])
                changed=root/'partial';changed.write_text(json.dumps(json.loads(feed.read_text().splitlines()[0]))+'\n')
                with self.assertRaisesRegex(ValueError,'Complete exact'):run(c,changed,root/'bad')
                pdf=c.root/'files'/f"{receipt['source_documents'][0]}.pdf";pdf.write_bytes(pdf.read_bytes()+b'bad')
                with self.assertRaisesRegex(ValueError,'Source PDF'):run(*args)
            finally:c.close()

if __name__=='__main__':unittest.main()
