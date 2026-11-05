import io
import sqlite3
import unittest
from network_daily_store import import_history, parse_csv

class NetworkHistoryTests(unittest.TestCase):
    def setUp(self): self.db=sqlite3.connect(':memory:')
    def tearDown(self): self.db.close()
    def test_preserves_conflicts_missing_and_duplicate_rows(self):
        csv=('scan_start_time,region_name,nr_upoct,lte_upoct\n'
             '2026-10-21,合肥,2,NULL\n2026-10-21,合肥,2,NULL\n'
             '2026-10-21,合肥,3,NULL\n2026-10-21,安徽省,5,0\n').encode()
        report='全省无线网络运行日报（2026年10月21日）\n正文'.encode()
        result=import_history(self.db,[report],csv)
        self.assertEqual(result['csv']['exact_duplicates'],1)
        self.assertEqual(result['csv']['conflict_groups'],1)
        self.assertEqual(self.db.execute("select count(*) from network_daily_indicators where quality_status='conflict'").fetchone()[0],2)
        self.assertIn('null',self.db.execute("select metrics_json from network_daily_indicators where region='合肥' limit 1").fetchone()[0])
        again=import_history(self.db,[report],csv)
        self.assertEqual(again['new_reports'],0)
        self.assertFalse(again['csv']['new_source'])
    def test_invalid_input_has_no_writes(self):
        with self.assertRaises(ValueError): import_history(self.db,['无标题'.encode()],b'bad')
        self.assertEqual(self.db.execute("select count(*) from sqlite_master where name like 'network_%'").fetchone()[0],0)
    def test_reject_unknown_columns(self):
        with self.assertRaises(ValueError): parse_csv('scan_start_time,region_name,nr_upoct,other\n2026-10-21,合肥,1,x'.encode())

if __name__=='__main__': unittest.main()
