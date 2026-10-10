import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_anchor_audit
from voxel_mapper import alton_sheet_replay


class ReplayTests(unittest.TestCase):
    def test_pinned_replay_resumes_and_rejects_changed_map_or_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive,sha=test_anchor_audit.AnchorTests().make_archive(root)
            osm=root/'osm.json';osm.write_text(json.dumps({'elements':[]}));osmsha=hashlib.sha256(osm.read_bytes()).hexdigest()
            # Use synthetic pinned sources and an official-host fixture URL.
            import zipfile
            with zipfile.ZipFile(archive) as z:
                blobs={n:z.read(n) for n in z.namelist()}
            catalogue=json.loads(blobs['metadata/alton-planning-catalogue.json'])
            catalogue['entries'][0]['url']='https://publicaccess.staffsmoorlands.gov.uk/a'
            blobs['metadata/alton-planning-catalogue.json']=json.dumps(catalogue).encode()
            blobs['alton-planning-catalogue.json']=blobs['metadata/alton-planning-catalogue.json']
            with zipfile.ZipFile(archive,'w') as z:
                for name,data in blobs.items():z.writestr(name,data)
            sha=hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.dict(alton_sheet_replay.ARCHIVES,{'mutiny':sha,'expanded':sha}),patch.object(alton_sheet_replay,'OSM_SHA256',osmsha):
                first=alton_sheet_replay.run(archive,archive,osm,root/'work')
                second=alton_sheet_replay.run(archive,archive,osm,root/'work')
                self.assertEqual(first['stages']['sheet_alignment'],second['stages']['sheet_alignment'])
                self.assertEqual(second['stages']['drawing_geometry']['resumed_pages'],1)
                self.assertEqual(second['stages']['sheet_alignment']['world_geometry_additions'],0)
                original=osm.read_bytes();osm.write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError,'map checksum'):alton_sheet_replay.run(archive,archive,osm,root/'work')
                osm.write_bytes(original);reference=root/'work/reference-landmarks.geojson';reference.write_text('{}')
                with self.assertRaisesRegex(ValueError,'Reference output changed'):alton_sheet_replay.run(archive,archive,osm,root/'work')

    def test_wrong_archive_rejected_before_creating_replay_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'wrong.zip';p.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'archive checksum'):alton_sheet_replay.run(p,p,root/'missing-map',root/'work')
            self.assertFalse((root/'work').exists())

if __name__=='__main__':unittest.main()
