import json
import sqlite3
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import app
import dashboard_data
import network_daily
from core import CITIES


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        network_daily.schema(self.db)
        self.db.execute('CREATE TABLE reports (period TEXT PRIMARY KEY,data TEXT NOT NULL,notes TEXT NOT NULL,weekly TEXT NOT NULL,monthly TEXT NOT NULL,monthly_data TEXT)')
        @contextmanager
        def connect():
            with self.db:yield self.db
        self.connect=connect
    def tearDown(self):self.db.close()
    def insert_csv(self,day,city,values,source='one'):
        self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',(source,day,city,source+city,json.dumps(values),'unreviewed'))
    def test_network_preserves_missing_zero_and_conflicting_sources(self):
        day='2026-10-21'
        self.insert_csv(day,'合肥',{'nr_upoct':'0'})
        self.insert_csv(day,'芜湖',{'nr_upoct':'10'})
        self.insert_csv(day,'芜湖',{'nr_upoct':'20'},'two')
        self.insert_csv(day,'安徽省',{'nr_upoct':'30','lte_upoct':'12','split_flow_rate':'70'})
        result=dashboard_data.network(self.connect,day,'5G数据流量')
        cities={r['name']:r for r in result['cities']}
        self.assertEqual(cities['合肥']['value'],0)
        self.assertIsNone(cities['芜湖']['value']);self.assertIn('差异',cities['芜湖']['source'])
        self.assertIsNone(cities['安庆']['value']);self.assertEqual(result['day'],day)
        self.assertEqual(result['cards'][0]['value'],'30')
    def test_monthly_uses_selected_version_and_keeps_partial_cities(self):
        rows=[{'city':name,'included':10,'qualified':5} for name in CITIES]
        self.db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?)',('2026-10-30',json.dumps({'cities':rows,'total':{'included':160,'qualified':80}}),'{}','周报','',None))
        suspension={'total':7,'period':None,'kind':'manual','city_note':'部分地市未提供','cities':[{'name':'合肥','value':7}]}
        result=dashboard_data.monthly(self.connect,'2026-10',suspension_reader=lambda _:suspension)
        self.assertEqual(result['source_info']['period'],'2026-10-30')
        self.assertEqual(result['cities'][0]['rate'],50)
        self.assertEqual(result['suspension']['cities'],[{'name':'合肥','value':7}])
        self.assertIn('部分',result['suspension']['city_note'])
    def test_province_city_traffic_discrepancy_is_not_ranked(self):
        day='2026-10-21'
        for name in CITIES:self.insert_csv(day,name,{'nr_upoct':'1'})
        self.insert_csv(day,'安徽省',{'nr_upoct':'16'})
        normal=dashboard_data.network(self.connect,day,'5G数据流量')
        self.assertEqual(sum(x['value'] for x in normal['cities']),16)
        self.db.execute('DELETE FROM network_daily_indicators WHERE region=?',('安徽省',))
        self.insert_csv(day,'安徽省',{'nr_upoct':'1000'})
        conflict=dashboard_data.network(self.connect,day,'5G数据流量')
        self.assertTrue(all(x['value'] is None for x in conflict['cities']))
        self.assertIn('不一致',conflict['notice'])
        self.assertEqual(conflict['cards'][0]['value'],'1000')
    def test_traffic_comparison_tolerance_and_incomplete_sources(self):
        day='2026-10-21'
        for name in CITIES:self.insert_csv(day,name,{'nr_upoct':'1','split_flow_rate':'80'})
        self.insert_csv(day,'安徽省',{'nr_upoct':'16.10','split_flow_rate':'10'})
        self.assertTrue(all(x['value'] is not None for x in dashboard_data.network(self.connect,day,'5G数据流量')['cities']))
        self.db.execute('DELETE FROM network_daily_indicators WHERE region=?',('安徽省',))
        self.insert_csv(day,'安徽省',{'nr_upoct':'16.11','split_flow_rate':'10'})
        self.assertTrue(all(x['value'] is None for x in dashboard_data.network(self.connect,day,'5G数据流量')['cities']))
        self.assertTrue(all(x['value'] is not None for x in dashboard_data.network(self.connect,day,'5G分流比')['cities']))
        self.db.execute('DELETE FROM network_daily_indicators WHERE region=?',('安徽省',))
        self.assertTrue(all(x['value'] is not None for x in dashboard_data.network(self.connect,day,'5G数据流量')['cities']))
        self.insert_csv(day,'安徽省',{'nr_upoct':'1000'})
        self.db.execute('DELETE FROM network_daily_indicators WHERE region=?',(CITIES[0],))
        partial=dashboard_data.network(self.connect,day,'5G数据流量')['cities']
        self.assertEqual(sum(x['value'] is not None for x in partial),15)
    def test_map_is_the_16_prefecture_boundaries(self):
        geo=json.loads((Path(app.__file__).parent/'static/data/anhui-cities.geojson').read_text(encoding='utf-8'))
        self.assertEqual({f['properties']['name'].removesuffix('市') for f in geo['features']},set(CITIES))
    def test_missing_blackspot_does_not_hide_known_suspension(self):
        suspended={'total':7,'period':None,'kind':'manual','city_note':'部分地市未提供','cities':[{'name':'合肥','value':7}]}
        result=dashboard_data.monthly(self.connect,'2026-09',suspension_reader=lambda _:suspended)
        self.assertEqual(result['cities'],[])
        self.assertEqual(result['suspension']['total'],7)
        self.assertTrue(result['notice'])
    def test_home_and_report_routes(self):
        with patch.object(app,'connect',self.connect):
            client=app.app.test_client()
            self.assertIn('全省无线网络总览',client.get('/').get_data(as_text=True))
            self.assertIn('黑点周报与月报',client.get('/reports').get_data(as_text=True))
            redirect=client.get('/?period=2026-10-30&kind=weekly')
            self.assertEqual(redirect.status_code,302);self.assertIn('/reports?period=',redirect.location)
