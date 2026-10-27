"""Original raster bytes, separate labels, and pinned acquisition boundaries."""
from pathlib import Path
import hashlib,json,tempfile,unittest
from concurrent.futures import CancelledError
from PIL import Image,ImageDraw
from voxel_mapper import study_raster_dataset as raster,study_source_acquisition as acquisition,study_component_learning as reader


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(root):
    p=root/'sources';p.mkdir();im=Image.new('RGB',(80,64),'white');d=ImageDraw.Draw(im)
    d.rectangle((10,10,60,50),fill='black');d.rectangle((25,25,40,40),fill='white');d.rectangle((28,28,32,32),fill='black');im.save(p/'drawing.png')
    source={'id':'sheet','file':'drawing.png','sha256':sha(p/'drawing.png'),'size_pixels':[80,64],
        'url':'https://example.org/drawing.png','rights_advisory':'Synthetic engineering fixture only.','source_state':'existing'}
    target={'type':'Polygon','coordinates':[[[10,10],[60,10],[60,50],[10,50],[10,10]],[[25,25],[40,25],[40,40],[25,40],[25,25]]]}
    annotation={'id':'component','source_id':'sheet','building_id':'fixture-building','kind':'wall','target_role':'wall_outline',
        'review_status':'reviewed_source_trace','review_basis':'Synthetic contract test, not a real source review.','trace_uncertainty_pixels':2,'target_geometry':target}
    review={'version':raster.VERSION,'sources':[source],'records':[annotation]};path=root/'review.json';path.write_text(json.dumps(review));return p,path,review


class RasterSourceTests(unittest.TestCase):
    def test_original_pixels_holes_and_review_lineage_remain_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources,path,review=fixture(root);original=(sources/'drawing.png').read_bytes()
            out=root/'output';result=raster.build(path,sources,out);row=result['records'][0]
            self.assertTrue(row['original_raster_verified']);self.assertFalse(row['original_pdf_verified'])
            self.assertEqual((out/result['documents'][0]['file']).read_bytes(),original)
            self.assertEqual(row['source']['document_sha256'],sha(sources/'drawing.png'))
            a,b,c,d,e,f=row['crop_to_input_matrix'];xy=(round(a*30+c*30+e),round(b*30+d*30+f))
            with Image.open(out/row['input_file']) as im:self.assertLess(im.getpixel(xy),100)
            with Image.open(out/row['target_mask_file']) as im:self.assertEqual(im.getpixel(xy),0)
            self.assertEqual(len(reader.read_dataset(out)[1]),1)

    def test_changed_bytes_dimensions_unreviewed_and_outside_geometry_fail_atomically(self):
        for mode in ['bytes','dimensions','review','outside','missing_source']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);sources,path,review=fixture(root)
                if mode=='bytes':(sources/'drawing.png').write_bytes(b'changed')
                elif mode=='dimensions':review['sources'][0]['size_pixels']=[81,64]
                elif mode=='review':review['records'][0]['review_status']='unreviewed'
                elif mode=='outside':review['records'][0]['target_geometry']['coordinates'][0][0]=[-10,10]
                else:review['records'][0]['source_id']='absent'
                path.write_text(json.dumps(review))
                with self.assertRaises(ValueError):raster.build(path,sources,root/'output')
                self.assertFalse((root/'output').exists())

    def test_multiple_views_of_one_building_remain_one_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources,path,review=fixture(root)
            import copy
            second=copy.deepcopy(review['records'][0]);second['id']='second-view';review['records'].append(second);path.write_text(json.dumps(review))
            result=raster.build(path,sources,root/'output')
            self.assertEqual(len(result['records']),2);self.assertEqual(len(result['groups']),1)

    def test_partial_trace_is_not_closed_or_extruded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources,path,review=fixture(root);review['records'][0]['target_geometry']={'type':'LineString','coordinates':[[10,10],[30,25],[60,15]]};path.write_text(json.dumps(review))
            result=raster.build(path,sources,root/'output')
            self.assertEqual(result['records'][0]['target_geometry']['type'],'LineString')
            self.assertFalse(result['physical_geometry_verified'])

    def test_fresh_outputs_and_cancellation_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources,path,review=fixture(root);before=(sources/'drawing.png').read_bytes();out=root/'output'
            with self.assertRaises(CancelledError):raster.build(path,sources,out,cancelled=lambda:True)
            self.assertFalse(out.exists());raster.build(path,sources,out)
            with self.assertRaisesRegex(ValueError,'Fresh'):raster.build(path,sources,out)
            self.assertEqual((sources/'drawing.png').read_bytes(),before)


class Response:
    url='https://example.org/source.png'
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,n):yield self.data[:3];yield self.data[3:]

class Session:
    def __init__(self,data):self.data=data
    def get(self,*args,**kwargs):return Response(self.data)

class SourceAcquisitionTests(unittest.TestCase):
    def test_pins_format_and_receipt_bind_download_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=b'\x89PNG\r\n\x1a\nfixture';profile={'version':'pinned-study-source-acquisition-v1','sources':[{'file':'source.png','url':'https://example.org/source.png','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'format':'png'}]}
            p=root/'profile.json';p.write_text(json.dumps(profile));result=acquisition.acquire(p,root/'sources',session=Session(data))
            self.assertEqual((root/'sources/source.png').read_bytes(),data)
            self.assertEqual(result['training_labels_generated'],0)

    def test_changed_oversized_and_wrong_format_downloads_never_publish(self):
        for mode in ['hash','size','format']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);data=b'%PDF-source';row={'file':'source.pdf','url':'https://example.org/source.pdf','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'format':'pdf'}
                if mode=='hash':row['sha256']='a'*64
                elif mode=='size':row['bytes']-=1
                else:row['format']='png'
                p=root/'p.json';p.write_text(json.dumps({'version':'pinned-study-source-acquisition-v1','sources':[row]}))
                with self.assertRaises(ValueError):acquisition.acquire(p,root/'output',session=Session(data))
                self.assertFalse((root/'output').exists())

if __name__=='__main__':unittest.main()
