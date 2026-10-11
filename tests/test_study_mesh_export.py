import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from shapely.geometry import box
from voxel_mapper.wing_shell_study import solid
from voxel_mapper.study_mesh_export import write_glb


class StudyMeshExportTests(unittest.TestCase):
    def test_glb_lengths_buffers_axis_and_normals(self):
        mesh=solid(box(2.123456,3,4,5),2,6,8)
        model={'status':'test_hypothesis','assumptions':['test'],
               'components':[{'id':'test_floor','role':'floor','mesh':mesh}]}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'model.glb';r=write_glb(model,p);raw=p.read_bytes()
        self.assertEqual(struct.unpack('<4sII',raw[:12]),(b'glTF',2,len(raw)))
        size,kind=struct.unpack('<I4s',raw[12:20]);self.assertEqual(kind,b'JSON')
        doc=json.loads(raw[20:20+size]);offset=20+size
        binsize,kind=struct.unpack('<I4s',raw[offset:offset+8]);self.assertEqual(kind,b'BIN\0')
        self.assertEqual(binsize,doc['buffers'][0]['byteLength'])
        data=raw[offset+8:];self.assertEqual(len(data),binsize)
        arrays=[]
        for view in doc['bufferViews']:
            start=view['byteOffset'];length=view['byteLength']
            self.assertEqual(start%4,0);self.assertLessEqual(start+length,len(data))
            arrays.append(np.frombuffer(data[start:start+length],dtype='<f4').reshape(-1,3))
        for accessor,array in zip(doc['accessors'],arrays):
            self.assertEqual(accessor['min'],array.min(axis=0).tolist())
            self.assertEqual(accessor['max'],array.max(axis=0).tolist())
        pos,norm=arrays
        self.assertEqual(pos.min(axis=0).tolist(),[float(np.float32(2.123456)),6,-5])
        self.assertEqual(pos.max(axis=0).tolist(),[4,8,-3])
        self.assertTrue(np.allclose(np.linalg.norm(norm,axis=1),1))
        tri=pos.reshape(-1,3,3);cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        self.assertTrue(np.all(np.sum(cross*norm[::3],axis=1)>0))
        self.assertFalse(doc['extras']['surveyed_complete_structure'])
        self.assertEqual(r['component_meshes'],1)

    def test_degenerate_triangles_rejected(self):
        model={'status':'test','assumptions':[],'components':[{'id':'bad','mesh':{'vertices':[[0,0,0],[0,0,0],[1,0,0]],'triangles':[[0,1,2]]}}]}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'Degenerate'):write_glb(model,Path(tmp)/'bad.glb')


if __name__=='__main__':unittest.main()
