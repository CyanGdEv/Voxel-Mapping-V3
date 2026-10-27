import copy
import json
from pathlib import Path
import tempfile
import unittest

from voxel_mapper import aerial_material_research as aerial, colour_materials as materials
from test_aerial_material_research import config, fixture, cache_fixture


class ColourMaterialTests(unittest.TestCase):
    def rows(self,root):
        path,receipt=fixture(root)
        return aerial.sample(path,receipt,4,0)

    def test_colour_appearance_assigns_vegetation_and_gray_without_claiming_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.rows(Path(tmp));original=copy.deepcopy(rows)
            green=materials.assign(rows[0]);gray=materials.assign(rows[-1])
            self.assertEqual(green['material'],'vegetation')
            self.assertIn('minecraft:grass_block',green['blocks'])
            self.assertEqual(gray['status'],'provisional_colour_assignment')
            self.assertEqual(gray['material'],rows[-1]['block_palette_candidates'][0]['palette'])
            self.assertFalse(gray['material_verified']);self.assertFalse(gray['training_eligible'])
            self.assertFalse(gray['physical_registration_verified']);self.assertEqual(rows,original)

    def test_blue_colour_maps_to_water_but_shadow_and_nodata_remain_unassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.rows(Path(tmp));blue={**rows[0],'median_rgb':[45,110,190],'colour_cue':'blue_surface_or_water','shadow_fraction':0}
            water=materials.assign(blue);self.assertEqual(water['blocks'],['minecraft:water'])
            self.assertFalse(water['material_verified'])
            self.assertEqual(materials.assign(rows[2])['reason'],'shadow_or_dark_surface')
            self.assertIsNone(materials.assign({**rows[0],'status':'insufficient_opaque_pixels'})['material'])

    def test_unknown_palette_or_nonfinite_colours_do_not_become_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=self.rows(Path(tmp))[-1]
            with self.assertRaises(ValueError):materials.assign({**row,'median_rgb':[float('nan'),0,0]})
            with self.assertRaises(ValueError):materials.assign({**row,'block_palette_candidates':[{'palette':'arbitrary_block'}]})

    def test_colour_layer_geojson_csv_and_preview_preserve_source_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=self.rows(root);summary=materials.write(rows,root,'Public <Park>')
            self.assertEqual(summary['assigned_cells'],12);self.assertEqual(summary['unassigned_cells'],4)
            layer=json.loads((root/'material-assignments.geojson').read_text())
            self.assertEqual(len(layer['features']),16)
            self.assertEqual(layer['features'][0]['geometry'],rows[0]['geometry'])
            self.assertEqual(layer['features'][0]['properties']['image_sha256'],rows[0]['image_sha256'])
            self.assertTrue((root/'material-map.png').is_file());self.assertIn('Public &lt;Park&gt;',(root/'materials.html').read_text())
            self.assertEqual(summary['world_blocks_generated'],0);self.assertEqual(summary['training_labels_generated'],0)

    def test_assignment_mode_is_explicit_and_original_rgb_candidates_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=config();cache_fixture(root,c)
            suggestions=aerial.run(c,root/'suggestions',root/'cache')
            assigned=aerial.run({**c,'material_mode':'colour_appearance'},root/'assigned',root/'cache')
            self.assertEqual(suggestions['provisional_material_assignments'],0)
            self.assertEqual(assigned['provisional_material_assignments'],12)
            self.assertIn('materials.html',(root/'assigned/index.html').read_text())
            self.assertEqual(suggestions['candidate_file_sha256'],assigned['candidate_file_sha256'])
            self.assertEqual(assigned['material_assignments_accepted'],0)
            self.assertEqual(assigned['network_bytes'],0);self.assertFalse(assigned['model_weights_updated'])
            with self.assertRaises(ValueError):aerial.validate({**c,'material_mode':'verified'})

    def test_desktop_worker_produces_material_layer_from_cached_rgb(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c={**config(),'material_mode':'colour_appearance'};cache_fixture(root,c)
            desktop=root/'desktop';shutil.copytree(root/'cache',desktop/'web-cache')
            path=root/'request.json';path.write_text(json.dumps(c));runtime=DesktopRuntime(desktop,workers=1,memory_budget_mb=2048)
            try:
                jid=runtime.submit('aerial_material_research',path);runtime._futures[jid].result(timeout=30)
                job=runtime.store.job(jid);self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertEqual(job['result']['provisional_material_assignments'],12)
                self.assertEqual(job['result']['colour_material_assignments']['unassigned_cells'],4)
                self.assertIn('provisional_material_assignments',runtime.store.context(20000))
            finally:runtime.close(wait=True)


if __name__=='__main__':unittest.main()
