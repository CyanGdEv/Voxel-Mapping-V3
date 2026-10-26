"""Proposed FFL claims and terrain steps must not become accepted grades."""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from shapely.geometry import box,mapping
from voxel_mapper import planning_surface_audit as audit,planning_geo_preview as geo


class SurfaceAuditTests(unittest.TestCase):
    def test_only_literal_ffl_claims_link_to_source_footprints(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf'
            with pymupdf.open() as doc:
                page=doc.new_page(width=300,height=200)
                for y,text in [(40,'Shop'),(55,'FFL 182.5'),(80,'HP3 - 191.4'),(95,'Theming Envelope 1 to 195.8')]:page.insert_text((30,y),text)
                doc.save(path)
            sha=hashlib.sha256(path.read_bytes()).hexdigest();buildings={'records':[{'id':'shop','labels':[{'text':'Shop'}],'geometry_pdf_native':mapping(box(20,100,200,180))}]}
            result=audit.floor_claims(path,sha,buildings,1)
            self.assertEqual(len(result),1);self.assertEqual(result[0]['printed_level_m'],182.5)
            self.assertEqual(result[0]['building_labels'],['Shop']);self.assertFalse(result[0]['vertical_datum_verified'])
            self.assertFalse(result[0]['applied_to_world'])
            with self.assertRaises(ValueError):audit.floor_claims(path,'0'*64,buildings,1)

    def test_floor_ground_difference_remains_conditional(self):
        claim={'source_building_ids':['station'],'printed_level_m':183.25,'applied_to_world':False}
        buildings={'records':[{'id':'station','geometry_pdf_native':mapping(box(0,0,2,2))}]}
        heights={(0,0):178,(1,0):179,(0,1):180,(1,1):181}
        result=audit.floor_terrain_comparison([claim],buildings,heights,1)[0]
        self.assertEqual(result['printed_ffl_minus_ground_block_range_m'],[2.25,5.25])
        self.assertEqual(result['terrain_block_relief_m'],3);self.assertFalse(result['final_floor_surface_verified'])
        raw=audit.floor_terrain_comparison([claim],buildings,heights,1,raw_sampler=lambda k:heights[k]+.75)[0]
        self.assertEqual(raw['printed_ffl_minus_original_terrain_range_m'],[1.5,4.5])
        self.assertEqual(raw['printed_ffl_minus_ground_block_range_m'],[2.25,5.25])
        with self.assertRaises(ValueError):audit.floor_terrain_comparison([claim],buildings,{(0,0):178},1)

    def test_walkable_cells_exclude_ride_buildings_and_assumed_edging(self):
        sampled={'paving':{(0,0),(1,0),(2,0),(3,0)},'markers':{(3,0)},'rocks':{(2,0):[(1,'oak_fence')]},
            'plan_markers':{(1,0):{'role':'track_centre'},(4,0):{'role':'queue_area'}},
            'expansion_cells':{(5,0):{'role':'passage'},(6,0):{'role':'building_boundary'}}}
        self.assertEqual(audit.walkable_cells(sampled),{(0,0),(4,0),(5,0)})

    def test_two_block_steps_split_local_component_and_have_projected_location(self):
        heights={(0,0):180,(1,0):180,(2,0):181,(3,0):183}
        result=audit.path_steps(set(heights),heights,[1,0,0,1,100,200])
        self.assertEqual(result['step_histogram_blocks'],{'0':1,'1':1,'2':1})
        self.assertEqual(result['multi_block_step_pairs'],1);self.assertEqual(result['component_sizes'],[3,1])
        self.assertEqual(result['hotspots'][0]['bng_midpoint_en_m'],[103,200.5])
        self.assertFalse(result['route_playability_verified'])
        with self.assertRaises(CancelledError):audit.path_steps(set(heights),heights,[1,0,0,1,0,0],cancelled=lambda:True)
        with self.assertRaises(ValueError):audit.path_steps({(0,0),(1,0)},{(0,0):180},[1,0,0,1,0,0])

    def test_changed_world_is_rejected_before_audit_or_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);asset=root/'input.json';asset.write_text('{}');sha=hashlib.sha256(asset.read_bytes()).hexdigest()
            config={};pins={}
            for n in ('osm','grid','dtm'):config[n+'_path']=str(asset);config[n+'_sha256']=sha;pins[n]=sha
            (root/'world.mcworld').write_bytes(b'changed')
            report={'source_pins':pins,'implementation_sha256':hashlib.sha256(Path(geo.__file__).read_bytes()).hexdigest(),
                'profile_sha256':hashlib.sha256(geo.PROFILE_PATH.read_bytes()).hexdigest(),'world':{'file':'world.mcworld','sha256':'0'*64}}
            (root/'quality-report.json').write_text(json.dumps(report))
            with self.assertRaises(ValueError):audit.run(config,root,'missing.pdf','missing-roof.pdf',root/'output')
            self.assertFalse((root/'output').exists())


if __name__=='__main__':unittest.main()
