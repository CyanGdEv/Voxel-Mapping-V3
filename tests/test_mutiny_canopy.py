import tempfile,unittest
from pathlib import Path
from shapely.geometry import box,Point
from shapely.affinity import rotate,scale
from voxel_mapper.mutiny_canopy import canopy_rows,provisional_pose,source_canopy,SCALE


class MutinyCanopyTests(unittest.TestCase):
 def test_pose_keeps_printed_scale_when_mapped_extent_differs(self):
  source=box(0,0,400,420);mapped=rotate(scale(source,xfact=SCALE*.94,yfact=SCALE*.94,origin=(0,0)),-32,origin=(0,0))
  candidate,audit=provisional_pose(source,mapped)
  self.assertEqual(candidate['scale_m_per_pdf_point'],SCALE)
  self.assertFalse(audit['registration_verified']);self.assertGreater(audit['inner_area_ratio'],1.1)
  self.assertNotIn('shop_corner_rms_m',candidate)

 def test_posts_bear_on_ground_and_roof_has_seams_between_steps(self):
  polygon=box(0,0,16,16);rows,report=canopy_rows(polygon,lambda x,z:178)
  self.assertEqual(report['roof_columns'],256)
  self.assertTrue(any(r['material']=='spruce_planks' for r in rows.values()))
  posts={(x,z) for (x,y,z),r in rows.items() if r['feature']=='mutiny/canopy-support'}
  self.assertEqual(len(posts),6)
  for x,z in posts:
   self.assertEqual(rows[x,179,z]['material'],'spruce_fence')
   roof=next(y for (xx,y,zz),r in rows.items() if xx==x and zz==z and r['feature']=='mutiny/canopy-roof')
   self.assertTrue(all((x,y,z) in rows for y in range(179,roof+1)))
  self.assertTrue(all(polygon.covers(Point(x+.5,z+.5)) and y>178 for x,y,z in rows))

 def test_missing_or_high_ground_cannot_receive_floating_supports(self):
  rows,_=canopy_rows(box(0,0,16,16),lambda x,z:None if x<8 else 183)
  self.assertEqual(rows,{})

 def test_other_pdf_cannot_supply_canopy_outline(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'other.pdf';p.write_bytes(b'not the reviewed canopy')
   with self.assertRaisesRegex(ValueError,'Pinned existing canopy'):source_canopy(p)
