import copy
import tempfile
import unittest
from pathlib import Path
from voxel_mapper.building_structure import inspect
from voxel_mapper.building_native import compile_spec
from voxel_mapper.building_pipeline import run
from tests.test_building_native import hall
from tests.test_building_data_pipeline import candidate


class StructureTests(unittest.TestCase):
    def test_roof_supported_through_wall_to_declared_floor(self):
        cells={(0,-1,0):'stone_bricks',(0,0,0):'stone_bricks',(0,1,0):'dark_oak_slab'}
        r=inspect(cells,{(0,-1,0)})
        self.assertEqual(r['status'],'passed_native_checks');self.assertEqual(r['component_count'],1)
        self.assertEqual(r['unsupported_roof_regions'],0);self.assertEqual(r['floor_connected_fraction'],1)
        self.assertFalse(r['physical_structural_safety_verified'])

    def test_floating_roof_and_disconnected_wall_reported(self):
        cells={(0,-1,0):'stone_bricks',(0,0,0):'stone_bricks',(0,3,0):'dark_oak_slab',(3,0,0):'stone_bricks'}
        r=inspect(cells,{(0,-1,0)})
        self.assertEqual(r['component_count'],3);self.assertEqual(r['unsupported_roof_regions'],1)
        self.assertIn('geometry_without_floor_connection',r['reasons'])
        self.assertIn('roof_regions_without_floor_connection',r['reasons'])

    def test_missing_floor_reference_is_unassessed_not_inferred(self):
        r=inspect({(0,0,0):'stone_bricks',(0,1,0):'dark_oak_slab'})
        self.assertIsNone(r['unsupported_roof_regions']);self.assertIsNone(r['floor_connected_fraction'])
        self.assertEqual(r['reasons'],['missing_declared_floor_anchor'])

    def test_face_connectivity_excludes_diagonal_contact(self):
        r=inspect({(0,0,0):'stone_bricks',(1,1,1):'dark_oak_planks'},{(0,0,0)})
        self.assertEqual(r['component_count'],2);self.assertEqual(r['unsupported_roof_regions'],1)

    def test_guarded_air_blocked_is_detected_independently(self):
        r=inspect({(0,0,0):'stone_bricks'},{(0,0,0)},[(0,0,0)])
        self.assertEqual(r['blocked_air_half_cells'],1);self.assertIn('blocked_declared_air',r['reasons'])

    def test_expected_roof_gap_and_guarded_interface_are_separate(self):
        cells={(0,0,0):'dark_oak_slab',(1,1,0):'dark_oak_slab'}
        contact={'columns':[(0,0),(1,0)],'minimum_half_y':0,'maximum_half_y':2}
        r=inspect(cells,roof_contacts=[contact]);self.assertEqual(r['missing_roof_contact_count'],1)
        r=inspect(cells,protected_air=[(1,1,0)],roof_contacts=[contact])
        self.assertEqual(r['missing_roof_contact_count'],0);self.assertEqual(r['guarded_roof_contacts_unassessed'],1)
        self.assertIn('missing_declared_floor_anchor',r['reasons'])

    def test_budget_exhaustion_returns_no_partial_assessment(self):
        with self.assertRaisesRegex(ValueError,'work budget'):inspect({(0,0,0):'stone_bricks'},max_checks=1)
        with self.assertRaisesRegex(ValueError,'occupancy'):inspect({(0,0,0):'stone_bricks'},max_halves=1)

    def test_report_deterministic_with_negative_coordinates(self):
        cells={(-2,-1,-3):'stone_bricks',(-2,0,-3):'dark_oak_slab'}
        self.assertEqual(inspect(cells,{(-2,-1,-3)}),inspect(dict(reversed(list(cells.items()))),{(-2,-1,-3)}))

    def test_shared_compiler_reports_real_floor_and_roof_checks(self):
        cells,audit=compile_spec(hall());r=audit['structural_review']
        self.assertGreater(r['declared_floor_anchor_cells'],0)
        self.assertEqual(r['blocked_air_half_cells'],0)
        self.assertEqual(r['status'],'passed_native_checks')

    def test_strict_batch_rejects_floating_candidate_and_tries_next(self):
        good=candidate('b-good');good['spec']=hall()
        bad=copy.deepcopy(good);bad['id']='a-bad'
        roof=bad['spec']['components'][-1]
        roof['geometry']['profile']=[[x,z+4] for x,z in roof['geometry']['profile']]
        job={'version':'building-batch-v1','native_output':'cells','native_quality':'require_pass',
            'buildings':[{'building_id':'building-a','candidates':[bad,good]}]}
        with tempfile.TemporaryDirectory() as tmp:
            report=run(job,Path(tmp)/'batch')
            self.assertEqual(report['built'],1);self.assertEqual(report['buildings'][0]['selected_id'],'b-good')
            rejected=report['buildings'][0]['construction_failures'][0]
            self.assertEqual(rejected['reason'],'native_structural_checks_failed')
            self.assertGreater(rejected['structural_review']['unsupported_roof_regions'],0)


class StrictGeometryOnlyTests(unittest.TestCase):
    def test_strict_checks_cannot_be_bypassed_by_disabling_native_export(self):
        c=candidate();c['spec']=hall();c['spec']['components'].pop(1)
        job={'version':'building-batch-v1','native_quality':'require_pass',
            'buildings':[{'building_id':'building-a','candidates':[c]}]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'batch';r=run(job,root)
            self.assertEqual(r['built'],0)
            self.assertFalse((root/'building-0000/model.glb').exists())
            self.assertEqual(r['buildings'][0]['construction_failures'][0]['reason'],'native_structural_checks_failed')
