"""Actual managed source-plan export and saved-page integrity at submission."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper.desktop_runtime import DesktopRuntime, write_json
from voxel_mapper.desktop_planning_area_smoke import run


class DesktopPlanningAreaTests(unittest.TestCase):
    def test_full_pdf_analysis_and_native_export_survive_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            result=run(Path(temporary)/'managed area with spaces')
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['building_footprint_markers'],2)
            self.assertEqual(result['saved_paving_components'],2)
            self.assertTrue(result['persistent_restart_verified'])
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
