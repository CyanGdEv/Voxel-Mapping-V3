"""Actual managed source-plan export and saved-page integrity at submission."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voxel_mapper.desktop_runtime import DesktopRuntime, write_json
from voxel_mapper.desktop_planning_area_smoke import run


class DesktopPlanningAreaTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'An actual desktop display is required')
    def test_short_viewports_keep_both_exports_and_the_source_job_row_reachable(self):
        import tkinter as tk
        from voxel_mapper.desktop_app import DesktopWindow
        try:root=tk.Tk()
        except tk.TclError as error:raise unittest.SkipTest(str(error))
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(DesktopWindow,'_create_runtime'),patch.object(DesktopWindow,'_poll'):
                window=DesktopWindow(root,Path(temporary))
            try:
                for width,height in ((1120,630),(964,638),(1024,650)):
                    with self.subTest(viewport=(width,height)):
                        root.geometry(f'{width}x{height}+0+0')
                        root.update()
                        window.web_run.master.master.select(window.web_run.master)
                        root.update()
                        for widget in (window.planning_area_export,window.planning_world_export):
                            x=widget.winfo_rootx()-root.winfo_rootx()
                            y=widget.winfo_rooty()-root.winfo_rooty()
                            self.assertTrue(widget.winfo_ismapped())
                            self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                            self.assertLessEqual(x+widget.winfo_width(),root.winfo_width())
                            self.assertLessEqual(y+widget.winfo_height(),root.winfo_height())
                        probe=window.jobs.insert('','end',values=('probe','planning_collection','completed','100%','source'))
                        try:
                            window.jobs.see(probe);root.update_idletasks()
                            bounds=window.jobs.bbox(probe)
                            self.assertTrue(bounds)
                            self.assertLessEqual(bounds[1]+bounds[3],window.jobs.winfo_height())
                            window.jobs.selection_set(probe)
                            self.assertIn(probe,window.jobs.selection())
                        finally:window.jobs.delete(probe)
            finally:window.close()

    def test_full_pdf_analysis_and_native_export_survive_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=run(Path(temporary)/'managed area with spaces')
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['building_footprint_markers'],2)
            self.assertEqual(result['saved_paving_components'],2)
            self.assertTrue(result['persistent_restart_verified'])
            self.assertTrue(result['complete_tiled_area_verified'])
            self.assertTrue(result['original_building_name_context_verified'])
            self.assertTrue(result['whole_native_annotation_context_verified'])
            self.assertTrue(result['original_closed_curve_review_verified'])
            self.assertTrue(result['open_curve_network_recovery_verified'])
            self.assertTrue(result['complete_long_curve_scope_verified'])
            self.assertTrue(result['source_hatch_legend_regions_verified'])
            self.assertTrue(result['existing_solid_paving_verified'])
            self.assertTrue(result['source_fill_rule_holes_verified'])
            self.assertTrue(result['assumed_rock_gap_policy_verified'])
            self.assertTrue(result['reference_geometry_world_verified'])
            self.assertTrue(result['narrow_path_oak_fences_verified'])
            self.assertTrue(result['rock_reference_style_verified'])
            self.assertTrue(result['additional_2d_building_boundaries_verified'])
            self.assertTrue(result['plan_marking_wool_palette_verified'])
            self.assertTrue(result['theming_queueing_below_semantics_verified'])
            self.assertTrue(result['user_identified_queue_area_profile_verified'])
            self.assertRegex(result['reviewed_plan_marking_profile_sha256'],'^[a-f0-9]{64}$')
            self.assertEqual(result['wide_area_sections'],2)
            self.assertGreater(result['wide_area_platform_cells'],16384)
            self.assertLessEqual(result['wide_area_native_write_attempts'],100000)
            self.assertFalse(result['real_park_accuracy_assessed'])
            self.assertEqual(result['area_world_job']['result']['reconstructed_buildings'],0)

    def test_saved_layout_mutation_and_wrong_job_cannot_be_queued(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);runtime=DesktopRuntime(root/'memory',workers=2,memory_budget_mb=2048)
            try:
                with self.assertRaisesRegex(ValueError,'completed planning'):
                    runtime.planning_area_layouts('absent')
                output=root/'saved';output.mkdir()
                path=output/'area-layout-fixture-1.json'
                write_json(path,{'id':'page-id','analysis_complete':True,
                    'shared_frame':{'fixture':True},'candidates':[{}]})
                pin=hashlib.sha256(path.read_bytes()).hexdigest()
                write_json(output/'area-layouts.json',{'page_layout_files':[{
                    'id':'page-id','file':path.name,'sha256':pin,
                    'document_sha256':'a'*64,'page':1,'candidate_count':1}]})
                manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
                runtime.store.add_job({'id':'saved','kind':'planning_source_pilot','config_path':str(root/'unused.json'),
                    'config_sha256':'b'*64,'output_directory':str(output)})
                runtime.store.update_job('saved',status='completed',result={'output_sha256':manifest})
                # This checks submission pins only; the exporter separately
                # validates the complete source geometry and scale receipt.
                self.assertEqual(len(runtime.planning_area_layouts('saved')),1)
                path.write_text(json.dumps({'changed':True}),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'page changed'):
                    runtime.submit_planning_area_world_preview('saved')
                self.assertEqual(len(runtime.store.jobs()),1)
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
