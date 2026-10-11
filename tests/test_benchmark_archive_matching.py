import copy,csv,hashlib,tempfile,unittest
from pathlib import Path
from voxel_mapper.benchmark_archive_matching import review,grid_position

class BenchmarkArchiveTests(unittest.TestCase):
    def source(self,root,duplicate=False):
        path=root/'archive.csv'
        rows=[{'NG LETTERS':'SK','EASTING':'0744','NORTHING':'4354','HEIGHT':'178.9000','DATUM':'N','DESCRIPTION':'building corner'}]
        if duplicate:rows.append({**rows[0],'DESCRIPTION':'different benchmark'})
        with path.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        values=[{'id':'value','text':'(value 178.90m)','glyph_screen':{'status':'raster_consistent_candidate'}}]
        source=[{'document_sha256':'a'*64,'page':1,'status':'printed_benchmark_layout_evidence_only','printed_values':values,
            'layout_links':[{'marker_id':'marker','status':'one_visible_printed_value_layout_candidate','visible_candidate_value_ids':['value']}]}]
        return path,hashlib.sha256(path.read_bytes()).hexdigest(),source

    def test_grid_precision_and_height_match_do_not_authorize_controls(self):
        self.assertEqual(grid_position('SK','0744','4354'),([407440,343540],10))
        self.assertEqual(grid_position('TQ','30000','80000'),([530000,180000],1))
        with tempfile.TemporaryDirectory() as temp:
            path,pin,source=self.source(Path(temp));before=copy.deepcopy(source)
            result=review(source,path,pin,[407000,343000,408000,344000])
            self.assertEqual(result['links'][0]['status'],'one_height_consistent_archive_candidate')
            self.assertEqual(result['links'][0]['printed_rounding_half_interval_m'],'0.005')
            self.assertFalse(result['coordinate_control_verified']);self.assertFalse(result['vertical_datum_verified'])
            self.assertEqual(source,before)

    def test_competing_records_are_retained_and_hidden_values_are_not_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path,pin,source=self.source(Path(temp),duplicate=True)
            result=review(source,path,pin,[407000,343000,408000,344000])
            self.assertEqual(result['links'][0]['status'],'missing_or_competing_archive_candidates')
            self.assertEqual(len(result['links'][0]['candidate_archive_ids']),2)
            source[0]['layout_links'][0]['status']='benchmark_visibility_withheld'
            self.assertEqual(review(source,path,pin,[407000,343000,408000,344000])['links'],[])

    def test_complete_budget_withholding_and_wrong_archive_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            path,pin,source=self.source(Path(temp),duplicate=True)
            result=review(source,path,pin,[407000,343000,408000,344000],max_rows=1)
            self.assertEqual(result['status'],'archive_budget_withheld');self.assertEqual(result['links'],[])
            self.assertEqual(result['nearby_archive_records'],[])
            path.write_text('edited')
            with self.assertRaises(ValueError):review(source,path,pin,[407000,343000,408000,344000])

    def test_printed_mm_conversion_and_missing_height_match(self):
        with tempfile.TemporaryDirectory() as temp:
            path,pin,source=self.source(Path(temp))
            source[0]['printed_values'][0]['text']='(value 178900mm)'
            result=review(source,path,pin,[407000,343000,408000,344000])
            self.assertEqual(result['links'][0]['printed_height_m'],'178.900')
            self.assertEqual(result['links'][0]['printed_rounding_half_interval_m'],'0.0005')
            source[0]['printed_values'][0]['text']='(value 190.00m)'
            self.assertEqual(review(source,path,pin,[407000,343000,408000,344000])['links'][0]['candidate_archive_ids'],[])
