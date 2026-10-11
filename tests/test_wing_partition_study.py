import copy,hashlib,json
import unittest
import pymupdf
from shapely.geometry import shape
from voxel_mapper.wing_partition_review import review,derive
from voxel_mapper.wing_partition_study import apply,VERSION
from voxel_mapper.wing_shell_study import build
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.wing_block_shapes import occupied_halves


class PartitionStudyTests(unittest.TestCase):
    def setUp(self):
        from tests.test_wing_shell_study import ShellStudyTests
        from voxel_mapper.local_wing_review import build as front_build
        self.f=ShellStudyTests();self.f.setUp();self.path=self.f.f.f.paths['plan']
        with pymupdf.open(self.path) as doc:
            page=doc[0]
            for x in (75,78):
                s=page.new_shape();s.draw_polyline([(x,30),(x,95),(x+5,95)]);s.finish(color=(0,0,0));s.commit()
            raw=doc.tobytes();pix=page.get_pixmap();r=copy.deepcopy(self.f.f.f.recipe)
            r['documents']['plan'].update(sha256=hashlib.sha256(raw).hexdigest(),render_samples_sha256=hashlib.sha256(pix.samples).hexdigest())
        self.path.write_bytes(raw);r['plan_trace']['rear_point']=[10,105]
        r['openings'][0]['kind']='archway';r['openings'][0]['points_pixels']=[[110,200],[170,200],[170,80],[110,80]]
        r['openings'][1]['points_pixels']=[[180,175],[230,175],[230,80],[180,80]]
        self.parent=front_build(r,self.f.f.f.paths);shellseed=copy.deepcopy(self.f.seed)
        shellseed['parent_model_sha256']=hashlib.sha256((json.dumps(self.parent,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
        self.model,self.cells,self.audit=build(self.parent,shellseed);self.review=review(self.parent,self.path)
        self.seed={'version':VERSION,'parent_model_sha256':self.model['parent_model_sha256'],'review_sha256':self.digest(self.review),
                   'selected_band_ids':[self.review['bands'][0]['id']],'source_footprint_reviewed':True,'display_height_m':2.5}
        with pymupdf.open(self.path) as doc:self.parents,_=extract_page(doc[0],r['documents']['plan']['sha256'],1,min_line_length_points=.25,max_candidates=10000,isolate_open_stroked_subpaths=True)
    def tearDown(self):self.f.tearDown()
    @staticmethod
    def digest(r):return hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()

    def test_long_path_sides_keep_exact_original_segment_proofs(self):
        self.assertGreaterEqual(len(self.review['bands']),1);components={c['id']:c for c in self.review['source_components']}
        for segment in self.review['segments']:
            proof=segment['source_segment'];g=shape(components[proof['component_id']]['geometry'])
            chains=[g.coords] if g.geom_type=='LineString' else [g.exterior.coords,*[r.coords for r in g.interiors]]
            i=proof['segment_index'];self.assertEqual(list(chains[proof['ring_index']])[i:i+2],shape(segment['geometry']).coords[:])
        self.assertFalse(self.review['height_application_verified'])

    def test_budget_exhaustion_withholds_all_partial_bands_and_segments(self):
        r=derive(self.parents,self.review['native_to_local_matrix'],100*.0254/72,shape(self.review['review_scope_local']),max_segments=1)
        self.assertEqual(r['status'],'segment_budget_withheld');self.assertEqual(r['bands'],[]);self.assertEqual(r['segments'],[])

    def test_dashed_source_is_not_partition_evidence(self):
        parents=copy.deepcopy(self.parents)
        for p in parents:
            for paint in p['paint_references']:paint['stroke_style']['dashes_pdf']='[2 2] 0'
        r=derive(parents,self.review['native_to_local_matrix'],100*.0254/72,shape(self.review['review_scope_local']))
        self.assertEqual(r['bands'],[])

    def test_source_checksum_changes_reject(self):
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):review(self.parent,self.path)

    def test_partition_keeps_retained_shell_and_arch_clearance(self):
        m,c,a=apply(self.model,self.cells,self.audit,self.review,self.seed)
        self.assertTrue(all(c[p]==v for p,v in self.cells.items()));self.assertGreater(len(c),len(self.cells))
        self.assertFalse(m['partition_study']['room_inventory_complete']);self.assertTrue(m['components'][-1]['mesh']['watertight'])
        self.assertFalse(m['components'][-1]['height_measured']);self.assertFalse(any('glass' in v for v in c.values()))
        half=occupied_halves(c)
        for x in a['arch_columns']:
            for z in range(a['native_grid'][1]):
                for dx in (0,1):
                    for hy in range(4):
                        for dz in (0,1):self.assertNotIn((2*x+dx,hy,2*z+dz),half)
        self.assertEqual((m,c,a),apply(self.model,self.cells,self.audit,self.review,self.seed))

    def test_changed_review_and_repinned_forged_proof_both_reject(self):
        r=copy.deepcopy(self.review);sid=r['bands'][0]['source_line_references'][0]['component_id']
        next(s for s in r['segments'] if s['id']==sid)['source_segment']['native_endpoints'][0][0]+=.1
        with self.assertRaisesRegex(ValueError,'checksum'):apply(self.model,self.cells,self.audit,r,self.seed)
        s=copy.deepcopy(self.seed);s['review_sha256']=self.digest(r)
        with self.assertRaisesRegex(ValueError,'proof changed'):apply(self.model,self.cells,self.audit,r,s)

    def test_unreviewed_or_invalid_height_rejects(self):
        for key,value in [('source_footprint_reviewed',False),('display_height_m',float('nan')),('selected_band_ids',[]),('parent_model_sha256','0'*64)]:
            s=copy.deepcopy(self.seed);s[key]=value
            with self.assertRaises(ValueError):apply(self.model,self.cells,self.audit,self.review,s)

if __name__=='__main__':unittest.main()
