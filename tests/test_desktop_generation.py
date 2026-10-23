from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from voxel_mapper.desktop_runtime import _worker,file_hash,write_json


class DesktopGenerationTests(unittest.TestCase):
    def fixture(self,root,budget=1000):
        (root/'park inputs').mkdir();(root/'wicker inputs').mkdir()
        path=root/'job.json';write_json(path,{'source_output':'park inputs','wicker_output':'wicker inputs','max_blocks':budget})
        return {'version':'desktop-worker-v1','kind':'alton_world','config_path':str(path),'config_sha256':file_hash(path),
            'output_directory':str(root/'fresh output'),'progress_path':str(root/'progress.json'),'cancel_path':str(root/'cancel')}

    def test_full_park_uses_existing_generator_with_retained_paths_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);request=self.fixture(root)
            with patch('voxel_mapper.alton_world.generate_park',return_value={'status':'draft_only'}) as generator:
                result=_worker(request)
            generator.assert_called_once_with(root/'park inputs',root/'wicker inputs',root/'fresh output',max_blocks=1000)
            self.assertEqual(result['status'],'draft_only')
            self.assertFalse((root/'fresh output').exists())

    def test_bad_budget_and_missing_retained_input_do_not_start_generation(self):
        for mode in ('budget','missing'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);request=self.fixture(root,80000001 if mode=='budget' else 1000)
                if mode=='missing':(root/'park inputs').rmdir()
                with patch('voxel_mapper.alton_world.generate_park') as generator,self.assertRaises(ValueError):_worker(request)
                generator.assert_not_called()
