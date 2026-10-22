import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box, mapping

from voxel_mapper import automatic_door_symbols as symbols
from voxel_mapper.reconstruction_evidence_queue import digest


class DoorSymbolTests(unittest.TestCase):
    def edges(self):
        hinge=[40.,100.]; vertices=[[40+20*math.cos(math.radians(a)),100+20*math.sin(math.radians(a))] for a in range(-90,1,10)]
        vertices[0]=[40.,80.];vertices[-1]=[60.,100.]
        pairs=[[hinge,vertices[0]],*[[a,b] for a,b in zip(vertices,vertices[1:])]]
        return [{'id':str(i),'points_pdf_native':copy.deepcopy(p),'stroke_width_pdf_points':.25,'stroke_color':[0.,0.,0.],
            'clip_references':[]} for i,p in enumerate(pairs)]

    def gap(self):
        return {'id':'gap','gap_endpoints_pdf_native':[[40.,100.],[60.,100.]],
            'geometry_pdf_native':mapping(box(40,98,60,102)),'physical_opening_verified':False}

    def fixture(self, root):
        with pymupdf.open() as document:
            page=document.new_page(width=200,height=200)
            for edge in self.edges():
                a,b=edge['points_pdf_native'];page.draw_line((a[0],200-a[1]),(b[0],200-b[1]),width=.25)
            page.insert_text((20,150),'Internal layout shown for illustrative purposes only',fontsize=6)
            data=document.tobytes()
        sha=hashlib.sha256(data).hexdigest();(root/'files').mkdir();(root/'files'/(sha+'.pdf')).write_bytes(data)
        view={'id':'plan','document_sha256':sha,'page':1,'geometry':mapping(box(0,0,200,200)),
            'printed_claim':{'view_kind':'plan','plan_level_or_form':'groundfloor'}}
        source=[{'document_sha256':sha,'page':1,'views':[view]}]
        inventory={'view_id':'plan','source_view_sha256':digest(view),'plan_gap_review':{'gaps':[self.gap()]}}
        position={'id':'position','status':'all_witness_positions_compatible',
            'source_gap_projection':{'source_gap_sha256':digest(self.gap())}}
        returns={'source_inventory_sha256':{'plan':digest(inventory)},'diagnostics':[{'position_comparisons':[position]}]}
        return SimpleNamespace(root=root),source,[inventory],returns

    def test_original_leaf_anchors_quarter_swing_without_circle_or_joint_fitting(self):
        edges=self.edges();before=copy.deepcopy(edges);result=symbols.find_symbols(self.gap(),edges,lambda:None)
        self.assertEqual(edges,before);self.assertEqual(len(result['symbols']),1)
        row=result['symbols'][0];self.assertEqual(row['hinge_pdf_native'],[40.,100.]);self.assertEqual(len(row['arc_edge_ids']),9)
        self.assertAlmostEqual(abs(row['sweep_degrees']),90)
        self.assertFalse(row['hinge_fitted']);self.assertFalse(row['source_points_moved']);self.assertFalse(row['joints_snapped'])
        self.assertFalse(row['symbol_semantics_verified']);self.assertFalse(row['physical_opening_verified'])

    def test_a_tiny_broken_original_joint_cannot_be_snapped_into_a_symbol(self):
        edges=self.edges();edges[3]['points_pdf_native'][0][0]+=.0001
        self.assertEqual(symbols.find_symbols(self.gap(),edges,lambda:None)['symbols'],[])

    def test_partial_arc_wrong_radius_style_and_missing_leaf_do_not_supply_symbols(self):
        for mode in ('partial','radius','style','leaf','translated'):
            with self.subTest(mode=mode):
                edges=self.edges()
                if mode=='partial':edges=edges[:-3]
                elif mode=='radius':edges[3]['points_pdf_native'][1][0]+=2
                elif mode=='style':edges[3]['stroke_width_pdf_points']=.5
                elif mode=='leaf':edges=edges[1:]
                else:
                    for edge in edges[1:]:edge['points_pdf_native']=[[x+2,y+2] for x,y in edge['points_pdf_native']]
                self.assertEqual(symbols.find_symbols(self.gap(),edges,lambda:None)['symbols'],[])

    def test_all_competing_original_leaves_survive_without_ranking(self):
        edges=self.edges();edges.append({**copy.deepcopy(edges[0]),'id':'competing'})
        result=symbols.find_symbols(self.gap(),edges,lambda:None)
        self.assertEqual({s['leaf_edge_id'] for s in result['symbols']},{'0','competing'})

    def test_a_continuing_source_arc_cannot_be_cut_at_a_convenient_quarter_turn(self):
        edges=self.edges();end=edges[-1]['points_pdf_native'][1]
        for angle in (10,20):
            other=[40+20*math.cos(math.radians(angle)),100+20*math.sin(math.radians(angle))]
            edges.append({**copy.deepcopy(edges[-1]),'id':'continuation-'+str(angle),'points_pdf_native':[end,other]})
            end=other
        self.assertEqual(symbols.find_symbols(self.gap(),edges,lambda:None)['symbols'],[])

    def test_native_pdf_recovers_short_segments_and_binds_conditional_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));before=copy.deepcopy(args[1:]);result=symbols.run(*args)
            self.assertEqual(args[1:],before);self.assertEqual(result['counts']['symbol_candidates'],1)
            self.assertEqual(result['counts']['conditional_positions_with_symbol_support'],1)
            self.assertEqual(result['counts']['illustrative_wording_records'],1)
            self.assertEqual(result['world_geometry_additions'],0);self.assertEqual(result['training_labels_generated'],0)
            for edge in result['pages'][0]['edges']:
                self.assertTrue(edge['whole_original_stroke_within_clip']);self.assertFalse(edge['later_overpaint_visibility_verified'])
            self.assertFalse(result['artwork_scale_verified']);self.assertFalse(result['physical_opening_verified'])

    def test_crossing_original_arc_segments_are_withheld_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));view=args[1][0]['views'][0];view['geometry']=mapping(box(35,90,65,110))
            args[2][0]['source_view_sha256']=digest(view);args[3]['source_inventory_sha256']={'plan':digest(args[2][0])}
            result=symbols.run(*args);self.assertEqual(result['counts']['symbol_candidates'],0)
            self.assertEqual(result['conditional_position_links'][0]['status'],'original_door_symbol_not_found')

    def test_original_clip_paint_and_group_scopes_cannot_be_ignored(self):
        with pymupdf.open() as document:
            page=document.new_page(width=200,height=200);page.draw_line((40,100),(40,80),width=.25)
            original=page.get_drawings(extended=True)[0]
            for changes in ({'stroke_opacity':.5},{'dashes':'[2 2] 0'},{'layer':'hidden'},{'closePath':True}):
                with patch.object(page,'get_drawings',return_value=[{**original,**changes}]):
                    self.assertEqual(symbols.source_edges(page,{'document_sha256':'a'*64,'page':1},lambda:None)['edges'],[])
            clip={'type':'clip','level':0,'items':[('re',pymupdf.Rect(30,70,50,110),1)]}
            with patch.object(page,'get_drawings',return_value=[clip,{**original,'level':1}]):
                edges=symbols.source_edges(page,{'document_sha256':'a'*64,'page':1},lambda:None)['edges']
                self.assertEqual(len(edges),1);self.assertEqual(edges[0]['clip_references'][0]['path_ordinal'],0)
            clip['items']=[('re',pymupdf.Rect(30,90,50,110),1)]
            with patch.object(page,'get_drawings',return_value=[clip,{**original,'level':1}]):
                self.assertEqual(symbols.source_edges(page,{'document_sha256':'a'*64,'page':1},lambda:None)['edges'],[])
            with patch.object(page,'get_drawings',return_value=[{'type':'group','level':0},{**original,'level':1}]):
                self.assertEqual(symbols.source_edges(page,{'document_sha256':'a'*64,'page':1},lambda:None)['edges'],[])

    def test_early_and_late_budget_holds_discard_every_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp))
            for limit in (1,25):
                result=symbols.run(*args,max_checks=limit)
                self.assertEqual(result['status'],'door_symbol_budget_withheld');self.assertEqual(result['pages'],[])
                self.assertEqual(result['views'],[]);self.assertEqual(result['conditional_position_links'],[])
            with patch.object(symbols,'find_symbols',side_effect=OverflowError('door_symbol_candidate_budget')):
                result=symbols.run(*args)
                self.assertEqual(result['pages'],[]);self.assertEqual(result['reason'],'door_symbol_candidate_budget')

    def test_stale_duplicate_changed_pdf_and_nonfinite_gap_inputs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));args[2][0]['changed']=True
            with self.assertRaisesRegex(ValueError,'Matching original return'):symbols.run(*args)
            args[2][0].pop('changed');args[1][0]['views'].append(copy.deepcopy(args[1][0]['views'][0]))
            with self.assertRaisesRegex(ValueError,'Matching unique original'):symbols.run(*args)
            args[1][0]['views'].pop();path=next((Path(tmp)/'files').glob('*.pdf'));path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'PDF checksum'):symbols.run(*args)
            for value in (0,True,100001):
                with self.assertRaises(ValueError):symbols.run(*args,max_checks=value)
        gap=self.gap();gap['gap_endpoints_pdf_native'][0][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'Finite positive'):symbols.find_symbols(gap,self.edges(),lambda:None)

    def test_independent_saved_json_audit_checks_every_original_symbol_edge(self):
        from collections import Counter
        from scripts.audit_door_symbol_evidence import verify
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));result=json.loads(json.dumps(symbols.run(*args)));checked=Counter()
            verify(*args,result,checked,100000)
            self.assertEqual(checked['original_door_symbol_edges'],10)
            self.assertEqual(checked['independent_leaf_anchored_swings'],1)
            self.assertEqual(checked['independent_symbol_position_links'],1)
            broken=copy.deepcopy(result);broken['views'][0]['gaps'][0]['symbols'][0]['hinge_pdf_native'][0]+=.5
            with self.assertRaises(AssertionError):verify(*args,broken,Counter(),100000)


if __name__=='__main__':unittest.main()
