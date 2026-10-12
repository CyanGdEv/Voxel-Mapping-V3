import unittest
from unittest.mock import Mock, patch
import requests
from voxel_mapper.cli import fetch_osm


class OsmRetryTests(unittest.TestCase):
    def response(self, status, data=None):
        response = Mock(status_code=status)
        response.json.return_value = data or {'elements': []}
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError('Overpass HTTP '+str(status))
        return response

    @patch('voxel_mapper.cli.time.sleep')
    def test_transient_gateway_error_retries_same_query(self, sleep):
        with patch('voxel_mapper.cli.requests.post', side_effect=[self.response(504), self.response(200)]) as post:
            collection, raw, skipped = fetch_osm([-1.886, 52.986, -1.881, 52.990])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0], post.call_args_list[1])
        self.assertEqual(raw['elements'], [])

    @patch('voxel_mapper.cli.time.sleep')
    def test_permanent_error_is_not_retried(self, sleep):
        with patch('voxel_mapper.cli.requests.post', return_value=self.response(403)) as post:
            with self.assertRaises(requests.HTTPError):
                fetch_osm([-1.886, 52.986, -1.881, 52.990])
        self.assertEqual(post.call_count, 1)

    @patch('voxel_mapper.cli.time.sleep')
    def test_timeout_retry_budget_is_finite(self, sleep):
        with patch('voxel_mapper.cli.requests.post', side_effect=requests.Timeout('timeout')) as post:
            with self.assertRaises(requests.Timeout):
                fetch_osm([-1.886, 52.986, -1.881, 52.990])
        self.assertEqual(post.call_count, 3)

    @patch('voxel_mapper.cli.time.sleep')
    def test_partial_data_is_never_accepted(self, sleep):
        with patch('voxel_mapper.cli.requests.post', return_value=self.response(200, {'elements': [], 'remark': 'timeout'})):
            with self.assertRaisesRegex(ValueError, 'incomplete data'):
                fetch_osm([-1.886, 52.986, -1.881, 52.990])
