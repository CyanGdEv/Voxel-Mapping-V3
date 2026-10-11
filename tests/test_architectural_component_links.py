import copy
import unittest
from shapely.geometry import box,mapping,shape
from tests import test_linework_boundaries as fixtures
from voxel_mapper.drawing_components import split_page
from voxel_mapper.architectural_interpretation import component_links,wall_bands


class ComponentLinkTests(unittest.TestCase):
    def fixture(self,leader=None):
        lines=[[(20,20),(100,20)],[(20,23),(100,23)]]
        if leader:lines.append(leader)
        parents=fixtures.LineworkTests().parents(lines);components=split_page(parents)
        bands=wall_bands(parents,.1)[0]
        edge=components[0]
        roof={'id':'roof','document_sha256':edge['document_sha256'],'page':edge['page'],
              'coordinate_frame':edge['coordinate_frame'],'geometry':mapping(box(20,20,100,100)),
              'line_parent_references':[{'candidate_id':edge['id'],'extraction_contract':edge['extraction_contract']}]}
        return parents,bands,[{'candidate_id':'roof','source_candidate':roof}]

    def label(self,role='eaves_level',visible=True):
        return {'printed_claim':{'role':role,'printed_value':181.49,'printed_units':'unspecified',
                'vertical_datum':'unspecified','height_application_verified':False},
                'glyph_screen':{'status':'raster_consistent_candidate' if visible else 'withheld'},
                'label_geometry':mapping(box(110,45,125,60))}

    def test_shared_source_edge_has_exact_geometry_and_no_wall_certification(self):
        parents,bands,roofs=self.fixture();original=copy.deepcopy((parents,bands,roofs))
        report=component_links(parents,bands,roofs,[],.1)
        self.assertEqual(len(report['roof_wall_links']),1)
        link=report['roof_wall_links'][0]
        self.assertEqual(link['shared_boundary_length_m'],8)
        self.assertEqual(link['source_component'],split_page(parents)[0])
        self.assertTrue(shape(link['shared_boundary_geometry']).equals(shape(parents[0]['geometry'])))
        self.assertEqual(link['roof_ring_role'],'exterior_ring')
        self.assertFalse(link['wall_identity_verified']);self.assertEqual(link['world_geometry_additions'],0)
        self.assertEqual((parents,bands,roofs),original)

    def test_same_line_contract_and_exact_overlap_required(self):
        parents,bands,roofs=self.fixture()
        changed=copy.deepcopy(roofs);changed[0]['source_candidate']['line_parent_references'][0]['extraction_contract']='changed'
        self.assertEqual(component_links(parents,bands,changed,[],.1)['roof_wall_links'],[])
        changed=copy.deepcopy(roofs);changed[0]['source_candidate']['geometry']=mapping(box(20,20.01,100,100))
        self.assertEqual(component_links(parents,bands,changed,[],.1)['roof_wall_links'],[])
        changed=copy.deepcopy(roofs);changed[0]['source_candidate']['page']=2
        with self.assertRaisesRegex(ValueError,'source page'):component_links(parents,bands,changed,[],.1)

    def test_unique_visible_source_leader_retains_heights_without_applying_them(self):
        parents,bands,roofs=self.fixture([(115,50),(100,50)]);labels=[self.label()]
        original=copy.deepcopy(labels);report=component_links(parents,bands,roofs,labels,.1)
        self.assertEqual(len(report['leader_associations']),1)
        link=report['leader_associations'][0]
        self.assertEqual(link['candidate_id'],'roof');self.assertEqual(link['printed_claim_index'],0)
        self.assertFalse(link['leader_semantics_verified']);self.assertFalse(link['height_application_verified'])
        self.assertEqual(link['source_leader_component'],split_page(parents)[-1])
        self.assertEqual(labels,original)
        self.assertEqual(component_links(parents,bands,roofs,[self.label(visible=False)],.1)['leader_associations'],[])

    def test_competing_leaders_nested_targets_dashes_and_nearby_endpoints_are_withheld(self):
        parents,bands,roofs=self.fixture([(115,50),(100,50)])
        other=copy.deepcopy(roofs[0]);other['candidate_id']='other';other['source_candidate']['id']='other'
        report=component_links(parents,bands,roofs+[other],[self.label()],.1)
        self.assertEqual(report['leader_associations'],[])
        self.assertEqual(report['claim_link_reviews'][0]['status'],'ambiguous_source_endpoint_connections')
        parents[-1]['paint_references'][0]['stroke_style']['dashes_pdf']='[1 2] 0'
        self.assertEqual(component_links(parents,bands,roofs,[self.label()],.1)['leader_associations'],[])
        parents,bands,roofs=self.fixture([(115,50),(99.99,50)])
        self.assertEqual(component_links(parents,bands,roofs,[self.label()],.1)['leader_associations'],[])
        parents,bands,roofs=self.fixture([(115,50),(100,50)])
        duplicate=fixtures.LineworkTests().parents([[(115,55),(100,55)]])[0]
        parents.append(duplicate)
        self.assertEqual(component_links(parents,bands,roofs,[self.label()],.1)['leader_associations'],[])

    def test_link_budget_discards_partial_results_and_boundary_is_not_its_own_leader(self):
        parents,bands,roofs=self.fixture([(115,50),(100,50)])
        report=component_links(parents,bands,roofs,[self.label()],.1,max_checks=1)
        self.assertEqual(report['status'],'component_link_budget_withheld')
        self.assertEqual(report['roof_wall_links'],[]);self.assertEqual(report['leader_associations'],[])
        label=self.label();label['label_geometry']=mapping(box(15,15,25,25))
        self.assertEqual(component_links(parents,bands,roofs,[label],.1)['leader_associations'],[])
        with self.assertRaises(ValueError):component_links(parents,bands,roofs,[],.1,max_checks=True)


if __name__=='__main__':unittest.main()
