import unittest
from voxel_mapper.raster_grid import edge_labels, inspect_label_layout


def tsv(text, confidence=95, left=10, top=100, width=60, height=15):
    return ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
            f'5\t1\t1\t1\t1\t1\t{left}\t{top}\t{width}\t{height}\t{confidence}\t{text}')


class RasterGridTests(unittest.TestCase):
    def labels(self):
        return [{'axis':axis,'value':value,'pixel_position':position} for axis, values in
                [('E',[(500000,100),(500050,1100),(500100,2100)]),
                 ('N',[(168000,2100),(168050,1100),(168100,100)])] for value,position in values]

    def test_rotated_crop_is_mapped_back_to_page_pixels(self):
        result = edge_labels(tsv('503500E'), 'top', (20,30,1020,210), 90)
        self.assertEqual(result[0]['value'], 503500)
        self.assertAlmostEqual(result[0]['pixel_position'], 1020-107.5/3)
        result = edge_labels(tsv('168400N'), 'right', (900,20,1020,1020), 0)
        self.assertAlmostEqual(result[0]['pixel_position'], 20+107.5/3)

    def test_digits_axis_confidence_and_bounds_are_not_repaired(self):
        for value in ('503500','50350OE','5035505','"503500E'):
            self.assertEqual(edge_labels(tsv(value),'top',(0,0,1000,180),90), [])
        self.assertEqual(edge_labels(tsv('503500E',40),'top',(0,0,1000,180),90), [])
        self.assertEqual(edge_labels(tsv('168400N'),'top',(0,0,1000,180),90), [])
        with self.assertRaisesRegex(ValueError,'outside'):
            edge_labels(tsv('503500E',left=10000),'top',(0,0,1000,180),90)

    def test_consistency_is_never_geographic_registration(self):
        result = inspect_label_layout(self.labels())
        self.assertEqual(result['status'],'consistent_label_layout_unverified')
        self.assertEqual(result['geographic_registration'],'not_established')
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertNotIn('transform',result)

    def test_duplicate_borders_do_not_create_third_control(self):
        labels = [x for x in self.labels() if x['value']!=500100]
        labels += [dict(x) for x in labels if x['axis']=='E']
        self.assertEqual(inspect_label_layout(labels)['status'],'insufficient_axis_labels')

    def test_corrupt_digit_reversed_axis_and_inconsistent_duplicate_are_withheld(self):
        labels=self.labels(); labels[1]['value']+=10
        self.assertEqual(inspect_label_layout(labels)['status'],'rejected_label_layout')
        labels=self.labels(); labels[-1]['pixel_position']=4100
        self.assertEqual(inspect_label_layout(labels)['status'],'rejected_label_layout')
        labels=self.labels(); labels.append(dict(labels[0],pixel_position=150))
        self.assertEqual(inspect_label_layout(labels)['status'],'rejected_label_layout')

    def test_budget_and_nonfinite_position_rejected(self):
        with self.assertRaises(ValueError): inspect_label_layout(self.labels()*11)
        labels=self.labels(); labels[0]['pixel_position']=float('nan')
        with self.assertRaises(ValueError): inspect_label_layout(labels)
