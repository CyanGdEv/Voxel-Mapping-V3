import tempfile
import unittest
from pathlib import Path
import pymupdf
from shapely.geometry import box,LineString
from voxel_mapper.osm_landmark_context import bind_labels,junctions,topology_checks
from voxel_mapper.osm_alignment_snapshot import acquire

class LandmarkAutomationTests(unittest.TestCase):
    def test_visible_unique_name_selects_seed_without_manual_ids(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((50,80),'Swiss Cottage',fontsize=9)
            objects=[{'candidate_id':'outline','geometry':box(40,300,160,370)}]
            refs=[{'id':'osm/way/1','name':'Swiss Cottage','geometry':box(0,0,20,20)}]
            result=bind_labels(page,objects,[],refs)
            self.assertEqual(result['priority_seed_ids'],['outline'])
            self.assertEqual(result['named_pairs'],[('outline','osm/way/1')])
            self.assertFalse(result['physical_identity_verified'])
            ambiguous=bind_labels(page,objects,[],refs+[{**refs[0],'id':'osm/way/2'}])
            self.assertEqual(ambiguous['priority_seed_ids'],[])
            self.assertEqual(ambiguous['labels'][0]['status'],'ambiguous_named_reference')
    def test_hidden_and_repeated_source_names_do_not_choose_seeds(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((50,80),'Swiss Cottage',fontsize=9)
            objects=[{'candidate_id':'outline','geometry':box(40,300,160,370)}]
            refs=[{'id':'osm/way/1','name':'Swiss Cottage','geometry':box(0,0,20,20)}]
            page.insert_text((50,180),'Swiss Cottage',fontsize=9)
            result=bind_labels(page,objects,[],refs);self.assertEqual(result['priority_seed_ids'],[])
            self.assertTrue(all(r['status']=='repeated_source_name' for r in result['labels']))
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((50,80),'Swiss Cottage',fontsize=9)
            page.draw_rect((40,60,160,90),fill=(1,1,1),color=None)
            result=bind_labels(page,objects,[],refs);self.assertEqual(result['priority_seed_ids'],[])
            self.assertEqual(result['labels'][0]['status'],'withheld_visibility')
    def test_crossings_gaps_and_duplicate_edges_do_not_invent_junctions(self):
        crossing=[LineString([(-1,0),(1,0)]),LineString([(0,-1),(0,1)])]
        self.assertEqual(junctions(crossing),[])
        connected=[LineString([(0,0),(1,0)]),LineString([(0,0),(-1,0)]),LineString([(0,0),(0,1)])]
        self.assertEqual(junctions(connected+connected)[0]['degree'],3)
        gapped=[connected[0],connected[1],LineString([(0,.001),(0,1)])]
        self.assertEqual(junctions(gapped),[])
        parents=[{'geometry':{'type':'LineString','coordinates':list(g.coords)}} for g in connected]
        fit={'matrix':[[1,0],[0,1]],'translation_m':[0,0]}
        result=topology_checks(parents,connected,[fit])
        self.assertEqual(len(result['hypotheses'][0]['unique_junction_matches']),1)
        self.assertFalse(result['registration_verified'])
    def test_automatic_snapshot_reuses_pinned_bytes_and_offline_waits(self):
        data=b'<osm><node id="1" lon="0" lat="0"/></osm>'
        bounds=[-1.89,52.98,-1.88,52.99]
        with tempfile.TemporaryDirectory() as tmp:
            path,record=acquire(tmp,bounds,fetch=lambda *args:data)
            self.assertFalse(record['registration_verified'])
            again,second=acquire(tmp,bounds,offline=True,fetch=lambda *a:(_ for _ in ()).throw(AssertionError('network')))
            self.assertEqual(record,second);self.assertEqual(path,again)
            path.write_bytes(b'<osm/>')
            with self.assertRaisesRegex(ValueError,'snapshot changed'):acquire(tmp,bounds)
        with tempfile.TemporaryDirectory() as tmp:
            path,record=acquire(tmp,bounds,offline=True);self.assertIsNone(path)
            self.assertEqual(record['status'],'awaiting_osm_snapshot')
    def test_invalid_snapshot_bounds_and_partial_data_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bounds in ([0,0,1,1],[0,0,float('nan'),.01],[True,0,.01,.01]):
                with self.assertRaises(ValueError):acquire(tmp,bounds,offline=True)
            with self.assertRaises(Exception):acquire(tmp,[0,0,.01,.01],fetch=lambda *a:b'{"elements":[],"remark":"timeout"}')
            self.assertFalse((Path(tmp)/'snapshot.json').exists())

    def test_raster_fallback_confirms_native_text_without_replacing_coordinates(self):
        from unittest.mock import patch,Mock
        from voxel_mapper.osm_landmark_context import raster_name_agreement
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((50,80),'Swiss Cottage',fontsize=9,color=(.54,.54,.54))
            run=page.get_texttrace()[0]
            def recognized(words):
                def execute(command,**kwargs):
                    Path(command[2]+'.tsv').write_text('level\tconf\ttext\n5\t92\t'+words+'\n')
                    return Mock(returncode=0)
                return execute
            with patch('voxel_mapper.osm_landmark_context.shutil.which',return_value='/fake/tesseract'),patch('voxel_mapper.osm_landmark_context.subprocess.run',side_effect=recognized('Swiss Cottage')):
                proof=raster_name_agreement(page,run,'Swiss Cottage')
            self.assertEqual(proof['status'],'native_raster_name_agreement_hint')
            self.assertIn('no OCR coordinate substitution',proof['source_coordinates'])
            self.assertFalse(proof['registration_verified'])
            with patch('voxel_mapper.osm_landmark_context.shutil.which',return_value='/fake/tesseract'),patch('voxel_mapper.osm_landmark_context.subprocess.run',side_effect=recognized('Other Cottage')):
                self.assertEqual(raster_name_agreement(page,run,'Swiss Cottage')['status'],'withheld')
    def test_zero_ocr_budget_accepts_screened_grey_labels_and_withholds_erased_ones(self):
        from unittest.mock import patch
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((50,80),'Swiss Cottage',fontsize=9,color=(.54,.54,.54))
            with patch('voxel_mapper.osm_landmark_context.raster_name_agreement',side_effect=AssertionError('OCR')):
                result=bind_labels(page,[{'candidate_id':'outline','geometry':box(40,300,160,370)}],[],
                    [{'id':'osm/way/1','name':'Swiss Cottage'}],max_ocr_labels=0)
            self.assertEqual(result['ocr_attempts'],0);self.assertEqual(result['priority_seed_ids'],['outline'])
            self.assertEqual(result['named_pairs'],[('outline','osm/way/1')])
            self.assertFalse(result['physical_identity_verified'])
            page.draw_rect((40,60,160,90),color=None,fill=(1,1,1))
            with patch('voxel_mapper.osm_landmark_context.raster_name_agreement',side_effect=AssertionError('OCR')):
                erased=bind_labels(page,[{'candidate_id':'outline','geometry':box(40,300,160,370)}],[],
                    [{'id':'osm/way/1','name':'Swiss Cottage'}],max_ocr_labels=0)
            self.assertEqual(erased['ocr_attempts'],0);self.assertEqual(erased['priority_seed_ids'],[])

    def test_coincident_distinct_osm_nodes_do_not_join_bridge_and_ground_paths(self):
        lines=[{'geometry':LineString([(0,0),(1,0)]),'node_ids':[1,2]},
               {'geometry':LineString([(0,0),(-1,0)]),'node_ids':[1,3]},
               {'geometry':LineString([(0,0),(0,1)]),'node_ids':[4,5]}]
        self.assertEqual(junctions(lines),[])
        lines[2]['node_ids']=[1,5]
        self.assertEqual(junctions(lines)[0]['degree'],3)
