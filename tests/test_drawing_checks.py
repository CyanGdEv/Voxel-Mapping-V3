import unittest
from tests.test_drawing_marks import marked_fixture
from voxel_mapper.drawing_controls import inspect_coordinate_labels
from voxel_mapper.geopdf import page_point_to_metric
from voxel_mapper.drawing_checks import check_external_controls


class ExternalCheckTests(unittest.TestCase):
    def test_displacement_uncertainty_provenance_and_coverage(self):
        viewport=inspect_coordinate_labels(marked_fixture(),reuse_allowed=True,require_marks=True)['viewports'][0]
        checks=[dict(source_id='external-survey',evidence_reference='survey-control-'+str(i),used_in_fit=False,
                     horizontal_uncertainty_m=.1,metric_crs=viewport['metric_crs'],page_point=p,
                     metric_point=list(page_point_to_metric(viewport,*p))) for i,p in enumerate(([120,120],[120,480],[480,480],[480,120]))]
        run=lambda:check_external_controls(viewport,checks,drawing_source_id='drawing')
        self.assertEqual(run()['status'],'external_control_agreement')
        checks[0]['metric_point'][0]+=2
        self.assertEqual(run()['status'],'external_control_disagreement')
        checks[0]['metric_point'][0]-=2
        checks[0]['horizontal_uncertainty_m']=2
        self.assertEqual(run()['status'],'external_control_disagreement')
        checks[0]['source_id']='drawing'
        self.assertEqual(run()['status'],'rejected')
        checks[0]['source_id']='external-survey'
        checks[0]['used_in_fit']=True
        self.assertEqual(run()['status'],'rejected')
        checks[0]['used_in_fit']=False
        for c in checks:c['page_point']=[200,200]
        self.assertEqual(run()['status'],'rejected')
