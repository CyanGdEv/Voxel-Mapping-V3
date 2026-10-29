import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import laspy
import numpy as np
from pyproj import CRS
from shapely.geometry import Polygon

from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.lidar_detail import (sample_archive, load_samples, observed_roof_layers,
                                     apply, apply_park_ground_and_foliage, unmapped_structure_surfaces,
                                     export_native_crop)
from voxel_mapper.alton_aligned_world import ChunkRenderer
from tests.test_alton_aligned_world import layers


class LidarDetailTests(unittest.TestCase):
    def cloud_archive(self, directory):
        directory = Path(directory)
        header = laspy.LasHeader(point_format=3, version='1.2')
        header.add_crs(CRS.from_epsg(27700))
        data = laspy.LasData(header)
        data.x = [1.1, 1.2, 1.8, 2.1, 3.1, 4.1, 5.1, 16.1]
        data.y = np.full(8, 2.1)
        data.z = [10.1, 10.4, 14.1, 10, 10, 10, 10, 10]
        data.classification = [6, 6, 6, 1, 5, 6, 6, 6]
        data.withheld = [0, 0, 0, 0, 0, 1, 0, 0]
        data.synthetic = [0, 0, 0, 0, 0, 0, 1, 0]
        cloud = directory/'source.las'
        data.write(cloud)
        archive = directory/'archive.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(cloud, 'source.las')
        receipt = {'crs':'EPSG:27700', 'vertical_datum':'ODN', 'survey_id':'P_10682',
                   'survey_date':'2022-01-05', 'archive_sha256':file_hash(archive),
                   'scanned_points':8, 'entry':'source.las', 'url':'https://example.test/survey'}
        source = directory/'source.json'
        source.write_text(json.dumps(receipt))
        return archive, source, receipt

    def test_stream_retains_all_structural_returns_and_separate_height_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, source, original = self.cloud_archive(tmp)
            out = Path(tmp)/'fine'
            result = sample_archive(archive, source, [0,0,16,16], out)
            xyz, labels, loaded = load_samples(out/'lidar-detail-receipt.json', [0,0,16,16], original)
            self.assertEqual(len(xyz), 4)
            self.assertEqual(labels.tolist(), [6,6,6,1])
            self.assertEqual(result['eligible_local_points'], 5)
            self.assertEqual(result['excluded_local_withheld_or_synthetic_points'], 2)
            self.assertEqual(result['multi_height_native_columns'], 1)
            self.assertGreater(result['quarter_metre_evidence_cells'], result['one_metre_evidence_cells'])
            self.assertFalse(result['random_subsampling'])
            self.assertTrue(result['quarter_index_covers_all_eligible_classes'])
            self.assertEqual(result['quarter_index_points_accounted_for'], 5)
            self.assertEqual(result['quarter_index_classes'], [1,5,6])
            self.assertEqual(loaded['samples_sha256'], result['samples_sha256'])
            with np.load(out/'lidar-detail-samples.npz') as samples:
                self.assertEqual(int(samples['quarter_counts'].sum()), 5)

    def test_changed_archive_or_sample_cache_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, source, receipt = self.cloud_archive(tmp)
            out=Path(tmp)/'fine'
            sample_archive(archive, source, [0,0,16,16], out)
            with (out/'lidar-detail-samples.npz').open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_samples(out/'lidar-detail-receipt.json', [0,0,16,16], receipt)
            with archive.open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                sample_archive(archive, source, [0,0,16,16], Path(tmp)/'other')

    def test_native_laz_preserves_all_classes_original_xyz_and_source_scales(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive,source,_=self.cloud_archive(tmp)
            target=Path(tmp)/'park.laz'
            result=export_native_crop(archive,source,[0,0,16,16],target)
            native=laspy.read(target)
            self.assertEqual(result['retained_points'],5)
            self.assertEqual(np.asarray(native.classification).tolist(),[6,6,6,1,5])
            self.assertTrue(np.allclose(np.asarray(native.z),[10.1,10.4,14.1,10,10]))
            self.assertEqual(native.header.parse_crs().to_epsg(),27700)
            self.assertFalse(np.asarray(native.withheld,bool).any())
            self.assertFalse(np.asarray(native.synthetic,bool).any())
            self.assertFalse(result['random_subsampling'])

    def test_mismatched_survey_or_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, source, receipt = self.cloud_archive(tmp)
            out=Path(tmp)/'fine'; sample_archive(archive, source, [0,0,16,16], out)
            with self.assertRaisesRegex(ValueError, 'survey and world frame'):
                load_samples(out/'lidar-detail-receipt.json', [0,0,32,16], receipt)
            with self.assertRaisesRegex(ValueError, 'survey and world frame'):
                load_samples(out/'lidar-detail-receipt.json', [0,0,16,16], {**receipt,'survey_date':'2023-01-01'})

    def planes(self):
        return np.array([(x,y,z) for z in (10.,14.)
                         for x in (.1,.5,.9) for y in (3.1,3.5,3.9)])

    def test_separate_observed_roofs_remain_separate_and_single_spike_is_rejected(self):
        points=np.vstack([self.planes(), [[.5,3.5,30.]]])
        tops, lower, report=observed_roof_layers(points, np.full(len(points),6),
                                               Polygon([(0,0),(4,0),(4,4),(0,4)]), 0, 0, 4)
        self.assertEqual(tops, {(0,0):14.})
        self.assertEqual(lower, [((0,0),10.)])
        self.assertEqual(report['isolated_layer_groups_omitted'],1)

    def test_vegetation_and_unclassified_points_never_set_a_building_roof(self):
        points=self.planes()
        for code in (1,5):
            tops, lower, _=observed_roof_layers(points,np.full(len(points),code),
                            Polygon([(0,0),(4,0),(4,4),(0,4)]),0,0,4)
            self.assertEqual(tops,{})
            self.assertEqual(lower,[])

    def test_points_inside_footprint_hole_do_not_create_surfaces(self):
        geometry=Polygon([(0,0),(4,0),(4,4),(0,4)],
                         holes=[[(.05,3.05),(.95,3.05),(.95,3.95),(.05,3.95)]])
        tops, lower, _=observed_roof_layers(self.planes(),np.full(18,6),geometry,0,0,4)
        self.assertEqual(tops,{})
        self.assertEqual(lower,[])

    def test_vertical_facade_is_not_promoted_to_a_lower_interior_floor(self):
        points=np.vstack([self.planes()[9:], np.array([(.5,y,z) for y in (3.1,3.5,3.9)
                                                     for z in (9.7,10.,10.3)])])
        _, lower, _=observed_roof_layers(points,np.full(len(points),6),
                            Polygon([(0,0),(4,0),(4,4),(0,4)]),0,0,4)
        self.assertEqual(lower,[])

    def test_native_lower_surface_is_saved_and_reference_air_keeps_priority(self):
        l=layers(); l.lidar_detail={(0,-1):[(5,70,5,'stone_slab_top'),(6,70,5,'stone_slab')]}
        l.reference_air={(0,-1):[(6,70,5)]}
        renderer=ChunkRenderer(l); arr,bottom=renderer.chunk(0,-1)
        self.assertEqual(renderer.materials[int(arr[5,70-bottom,5])],'stone_slab_top')
        self.assertEqual(renderer.materials[int(arr[6,70-bottom,5])],'air')

    def test_detail_application_respects_protected_wicker_and_ride_columns(self):
        from unittest.mock import patch
        l=layers(); l.bounds=[0,0,16,16]; l.e0=0; l.n1=16
        l.cloud_receipt={}; l.dtm=np.zeros((16,16)); l.audit={}; l.rgb=np.full((16,16,3),100.)
        l.roof_half[:]=20; l.building_floor[:]=0; l.protected[0,0]=True
        l.building_features=[{'id':'building','geometry':Polygon([(0,0),(4,0),(4,16),(0,16)]),
                             'properties':{}}]
        points=np.vstack([self.planes(), self.planes()+[1,0,0]])+[0,12,0]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'receipt.json'; p.write_text('{}')
            with patch('voxel_mapper.lidar_detail.load_samples',return_value=(points,np.full(len(points),6),{})), patch('voxel_mapper.lidar_detail.apply_park_ground_and_foliage',return_value={}):
                apply(l,p)
        self.assertEqual(l.roof_half[0,0],20)
        self.assertEqual(l.roof_half[0,1],28)
        self.assertTrue(l.lidar_detail)

    def test_park_wide_ground_uses_all_weights_and_preserves_protected_water_buildings(self):
        l=layers(); l.dtm=np.full((16,16),65.)
        l.protected[1,1]=True; l.water[2,2]=65; l.footprints[3,3]=True
        def key(c,r,z,code):
            return np.uint64(c*4) | (np.uint64(r*4) << np.uint64(14)) | (np.uint64(z*4+2048) << np.uint64(28)) | (np.uint64(code) << np.uint64(41))
        keys=np.array([key(i,i,65.75,2) for i in range(5)]+[key(8,8,72,5)],np.uint64)
        counts=np.array([3,3,3,3,1,1],np.uint32)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); np.savez_compressed(folder/'samples.npz',quarter_keys=keys,quarter_counts=counts)
            result=apply_park_ground_and_foliage(l,folder/'receipt.json',{
                'quarter_index_covers_all_eligible_classes':True,
                'samples_file':'samples.npz','eligible_local_points':int(counts.sum())})
        self.assertEqual(l.ground[0,0],65)
        for i in (1,2,3,4): self.assertEqual(l.ground[i,i],64)
        self.assertEqual(result['changed_native_ground_columns'],1)
        self.assertEqual(result['vegetation_native_voxels_regridded'],1)

    def test_supported_structure_layers_outside_osm_are_kept_without_extruding_gaps(self):
        from collections import defaultdict
        l=layers(); l.e0=0; l.n1=16; l.dtm=np.zeros((16,16)); l.ground[:]=0
        l.rgb=np.full((16,16,3),100.)
        points=self.planes()+[2,10,0]
        extra=defaultdict(list)
        result=unmapped_structure_surfaces(l,points,np.full(len(points),6),extra)
        self.assertEqual(result['observed_surface_blocks'],2)
        self.assertTrue(l.protected[2,2])
        ys={row[1] for rows in extra.values() for row in rows}
        self.assertEqual(ys,{9,13})
        self.assertNotIn(11,ys)


if __name__=='__main__':
    unittest.main()
