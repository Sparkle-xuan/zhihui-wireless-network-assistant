import json, sqlite3, unittest
import network_daily as n

class NetworkDailyTests(unittest.TestCase):
    def setUp(self): self.db=sqlite3.connect(':memory:');n.schema(self.db)
    def tearDown(self): self.db.close()
    def add(self,region,metric,quality='unreviewed',source='a'):
        payload=json.dumps(metric,sort_keys=True); self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',(source,'2026-10-21',region,source,payload,quality))
    def test_draft_and_conflicts_are_not_treated_as_zero(self):
        self.add('安徽省',{'nr_upoct':'100','lte_upoct':None,'split_flow_rate':'75','nr_terminal_login_users_day':'25'})
        self.add('合肥',{'nr_upoct':'10'},'conflict')
        self.add('合肥',{'nr_upoct':'11'},'conflict','b')
        result=n.detail(self.db,'2026-10-21')
        self.assertEqual(result['conflicts'],['合肥']);self.assertIsNone(result['cities'][0]['five'])
        text=n.build_draft(result);self.assertIn('100TB',text);self.assertIn('【缺少数据，待补充】',text)
    def test_same_day_source_disagreement_is_not_selected(self):
        self.add('安徽省',{'nr_upoct':'10'});self.add('安徽省',{'nr_upoct':'11'},source='b')
        result=n.detail(self.db,'2026-10-21');self.assertEqual(result['conflicts'],['安徽省']);self.assertIsNone(result['metrics'][0]['value'])
    def test_numeric_equivalence_and_complementary_sources(self):
        self.add('安徽省',{'nr_upoct':'10','lte_upoct':None})
        self.add('安徽省',{'nr_upoct':'10.0','lte_upoct':'5'},source='b')
        result=n.detail(self.db,'2026-10-21')
        self.assertEqual(result['conflicts'],[])
        self.assertEqual(result['metrics'][1]['value'],'5')
    def test_original_is_preserved_when_draft_saved(self):
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x','原文','s','pending_review'))
        n.save(self.db,'2026-10-21','草稿');result=n.detail(self.db,'2026-10-21')
        self.assertEqual(result['original'],'原文');self.assertEqual(result['draft'],'草稿')
    def test_report_extract_and_cross_source_conflict(self):
        body='全省5G当日数据流量100TB，4G当日数据流量20TB，5G分流比80%。'
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x',body,'s','pending_review'))
        self.add('安徽省',{'nr_upoct':'101','lte_upoct':'20','split_flow_rate':'80'})
        result=n.detail(self.db,'2026-10-21');metrics={m['key']:m for m in result['metrics']}
        self.assertIsNone(metrics['nr_upoct']['value']);self.assertEqual(metrics['nr_upoct']['source'],'来源冲突')
        self.assertEqual(metrics['lte_upoct']['source'],'CSV / 日报')

    def test_equivalent_report_numbers_are_not_a_conflict(self):
        body='全省5G当日数据流量10TB。全省5G当日数据流量10.0TB。'
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x',body,'s','pending_review'))
        result=n.detail(self.db,'2026-10-21')
        self.assertEqual(result['metric_conflicts'],[])
        self.assertEqual(result['metrics'][0]['value'],'10')

    def test_report_tables_use_selected_day_and_hide_conflicting_fields(self):
        self.add('安徽省',{'nr_upoct':'100','volte_online_users':None})
        self.add('合肥',{'nr_upoct':'10','wirelessconn_rate_5g':'99.8'})
        self.add('合肥',{'nr_upoct':'11','wirelessconn_rate_5g':'99.80'},source='b')
        result=n.detail(self.db,'2026-10-21')['report_tables']
        self.assertEqual(result['province']['nr_upoct'],'100')
        self.assertIsNone(result['province']['volte_online_users'])
        self.assertIsNone(result['cities'][0]['values']['nr_upoct'])
        self.assertEqual(result['cities'][0]['values']['wirelessconn_rate_5g'],'99.8')
        self.assertEqual(n.detail(self.db,'2026-10-22')['report_tables']['cities'],[])

    def test_invalid_date_and_no_data(self):
        with self.assertRaises(ValueError):n.detail(self.db,'invalid')
        with self.assertRaises(ValueError):n.build_draft(n.detail(self.db,'2026-10-21'))

if __name__=='__main__':unittest.main()
