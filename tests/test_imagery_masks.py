import hashlib,json,tempfile,unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box,mapping
from voxel_mapper.reconstruction.imagery import imagery_masks_adapter
from voxel_mapper.reconstruction.model import Source,EvidenceMissing
from voxel_mapper.reconstruction.sources import AdapterRegistry
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.generators import default_registry

class ImageryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'rgb.tif'
        pixels=np.ones((3,20,20),dtype='uint8')*100
        pixels[:,0,0]=0
        with rasterio.open(self.path,'w',driver='GTiff',width=20,height=20,count=3,dtype='uint8',crs='EPSG:27700',transform=from_origin(0,20,1,1),nodata=0) as dst:dst.write(pixels)
        self.source=Source('photo','imagery','fixture://photo','test','EPSG:27700',registration_status='accepted',metadata={'capture_date':'2026-01-01'})
        self.item={'id':'plaza','geometry':mapping(box(3,3,9,9)),'properties':{'kind':'plaza','reviewed':True,'reviewer':'fixture','surface':'brick'}}
        self.data={'imagery':{'file':'rgb.tif','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()},'features':[self.item]}
    def load(self):return imagery_masks_adapter(self.data,self.source,self.root)
    def test_registered_feed_generates_whole_polygon_and_keeps_image_evidence(self):
        (self.root/'masks.json').write_text(json.dumps(self.data))
        features,reports=AdapterRegistry().load([{'source':'photo','adapter':'imagery_masks','file':'masks.json'}],{'photo':self.source},'EPSG:27700',self.root)
        rows,report=ReconstructionEngine(default_registry()).plan(features,Context({'photo':self.source},lambda x,z:100,box(0,0,20,20),'ODN'))
        self.assertEqual(len(rows),36)
        self.assertEqual(reports[0]['decisions'][0]['status'],'accepted')
        self.assertEqual(features[0].metadata['imagery_sha256'],self.data['imagery']['sha256'])
        self.assertFalse(features[0].metadata['material_inferred_from_colour'])
    def test_unreviewed_and_outside_and_nodata_withheld(self):
        for geometry,reviewed in [(box(3,3,9,9),False),(box(19,19,22,22),True),(box(0,18,2,20),True)]:
            self.item['geometry']=mapping(geometry);self.item['properties']['reviewed']=reviewed
            features,decisions=self.load();self.assertFalse(features);self.assertEqual(decisions[0]['status'],'withheld')
    def test_hash_registration_date_and_crs_checked(self):
        self.data['imagery']['sha256']='wrong'
        with self.assertRaises(EvidenceMissing):self.load()
        self.data['imagery']['sha256']=hashlib.sha256(self.path.read_bytes()).hexdigest()
        for changes in [{'registration_status':'unregistered'},{'metadata':{}},{'crs':'EPSG:4326'}]:
            source=Source(**{**self.source.__dict__,**changes})
            with self.assertRaises(EvidenceMissing):imagery_masks_adapter(self.data,source,self.root)
    def test_missing_material_does_not_guess_from_rgb(self):
        del self.item['properties']['surface']
        self.assertFalse(self.load()[0])
    def test_polygon_hole_is_not_paved(self):
        from shapely.geometry import Polygon
        self.item['geometry']=mapping(Polygon([(3,3),(9,3),(9,9),(3,9)],holes=[[(5,5),(7,5),(7,7),(5,7)]]))
        features,_=self.load()
        rows,_=ReconstructionEngine(default_registry()).plan(features,Context({'photo':self.source},lambda x,z:100,box(0,0,20,20),'ODN'))
        self.assertEqual(len(rows),32)
        self.assertFalse(any(5<=r['x']<7 and 5<=r['z']<7 for r in rows))
