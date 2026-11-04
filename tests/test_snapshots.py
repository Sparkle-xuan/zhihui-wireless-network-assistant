import copy
import unittest

from app import compact_snapshot


class SnapshotTests(unittest.TestCase):
    def test_retains_calculated_aggregates_without_detail_fields(self):
        numbers = {'platform': 10, 'platform_complaints': 23, 'included': 5,
                   'complaints': 12, 'five': 3, 'suspended': 2, 'investment': 2,
                   'cost': 3, 'qualified': 4, 'rate': .8, 'after': 2,
                   'solved': 10, 'reduction': 10 / 12, 'stages': {'项目申请': 1}}
        data = {'total': copy.deepcopy(numbers),
                'cities': [dict(numbers, city='安庆', address='do-not-save')],
                'qualified_complaints': {'before': 11, 'after': 1, 'reduction': 10 / 11},
                'archive': {'count': 3, 'before': 8, 'after': 0, 'reduction': 1},
                'global': {'count': 2, 'qualified': 1, 'rate': .5, 'opening': 1},
                'suspended': {'count': 2, 'cities': [('安庆', 2)], 'categories': {'无项目': 2}},
                'legacy': None,
                'workbook_rows': ['do-not-save']}
        saved = compact_snapshot(data)
        self.assertEqual(saved['snapshot_version'], 2)
        self.assertEqual(saved['cities'][0]['stages']['项目申请'], 1)
        self.assertEqual(saved['suspended']['cities'], [('安庆', 2)])
        self.assertEqual(saved['global']['opening'], 1)
        self.assertIsNone(saved['legacy'])
        self.assertNotIn('do-not-save', str(saved))
        data['legacy'] = {'count': 94, 'done': 92, 'remaining': 2,
                          'coordination': 1, 'other': 1, 'rate': 92 / 94}
        self.assertEqual(compact_snapshot(data)['legacy']['remaining'], 2)


if __name__ == '__main__':
    unittest.main()
