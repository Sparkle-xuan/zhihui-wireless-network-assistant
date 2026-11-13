import json
import tempfile
import unittest
from pathlib import Path

import app as service
from core import CITIES
import followup_query
import city_followups
from datetime import date
from unittest.mock import patch


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'followups.sqlite3';service.app.testing=True
        self.client=service.app.test_client()
        self.payload={'month':'2026-09','city':CITIES[0],'issue':'解决率偏低','status':'待联系','action':'','next_date':'2026-10-10'}
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing;self.tmp.cleanup()
    def report(self,period,qualified):
        rows=[{'city':c,'included':10,'qualified':qualified} for c in CITIES]
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',(period,json.dumps({'cities':rows,'total':{'included':160,'qualified':qualified*16}}),'{}','周报',''))
    def test_create_edit_and_comparison(self):
        self.report('2026-09-25',4)
        created=self.client.post('/api/city-followups',json=self.payload)
        self.assertEqual(created.status_code,200);ident=created.json['id']
        item=self.client.get('/api/city-followups').json['items'][0]
        self.assertFalse(item['comparison']['available'])
        self.assertIn('下月',item['comparison']['message'])
        self.report('2026-10-30',6)
        item=self.client.get('/api/city-followups').json['items'][0]
        self.assertTrue(item['comparison']['available']);self.assertEqual(item['comparison']['change'],20)
        self.assertEqual([x['month'] for x in item['trend']],['2026-08','2026-09','2026-10','2026-11'])
        self.assertEqual(item['trend'][0]['note'],'暂无数据')
        self.assertEqual((item['comparison']['base_period'],item['comparison']['period']),('2026-09-25','2026-10-30'))
        result=self.client.post('/api/city-followups',json={**self.payload,'id':ident,'status':'推进中','action':'计划协调'})
        self.assertEqual(result.status_code,200)
        items=self.client.get('/api/city-followups').json['items'];self.assertEqual(len(items),1);self.assertEqual(items[0]['action'],'计划协调')
        self.assertEqual(len(items[0]['events']),2)
    def test_validation_and_no_implicit_emails(self):
        for payload in [{**self.payload,'city':'不存在'},{**self.payload,'next_date':'2026-02-30'},{**self.payload,'status':'未知'},{**self.payload,'issue':''}]:
            self.assertEqual(self.client.post('/api/city-followups',json=payload).status_code,400)
        self.assertEqual(self.client.get('/api/city-followups').json['items'],[])
    def test_suspension_trend_never_fills_unrecorded_cities_with_zero(self):
        self.client.post('/api/city-followups',json=self.payload)
        def source(month):
            return {'kind':'manual','period':None,'city_note':'仅部分地市','cities':[{'name':CITIES[0],'value':5}]} if month=='2026-09' else {'kind':'manual','period':None,'city_note':'仅部分地市','cities':[{'name':CITIES[1],'value':2}]}
        result=city_followups.list_records(service.connect,suspension_reader=source)[0]['suspension_trend']
        self.assertEqual(result[1]['count'],5);self.assertIsNone(result[0]['count']);self.assertEqual(result[0]['note'],'暂无数据')
    def test_local_assistant_query_reports_manual_records_and_no_send(self):
        self.client.post('/api/city-followups',json=self.payload)
        parsed=followup_query.plan('上个月提醒过哪些地市？现在推进得怎么样？',date(2026,10,15))
        self.assertEqual(parsed['month'],'2026-09')
        self.assertIn('error',followup_query.plan('查询2026年13月推进台账',date(2026,10,15)))
        with patch('app.send_report') as send,patch('credential_store.get_assistant_key',return_value=None):
            response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'查询2026年9月推进台账'}]})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['table']['rows'][0][1],CITIES[0]);send.assert_not_called()

    def test_assistant_filters_before_recent_limit(self):
        self.client.post('/api/city-followups',json=self.payload)
        with service.connect() as c:
            for n in range(101):
                c.execute('INSERT INTO city_followups (id,month,city,issue,status,action,next_date,updated_at) VALUES (?,?,?,?,?,?,?,?)',(f'{n:032x}','2026-10',CITIES[1],'测试事项','待联系','','','2099-01-01T00:00:00'))
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'查询2026年9月推进台账'}]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['table']['rows'][0][0],'2026-09')

    def test_comparison_does_not_hide_query_failure(self):
        self.client.post('/api/city-followups',json=self.payload)
        with patch('city_followups.query',side_effect=RuntimeError('Wren offline')):
            item=self.client.get('/api/city-followups').json['items'][0]
        self.assertFalse(item['comparison']['available'])
        self.assertIn('查询',item['comparison']['message'])

    def test_history_retains_original_city_month_and_issue(self):
        ident=self.client.post('/api/city-followups',json=self.payload).json['id']
        changed={**self.payload,'id':ident,'month':'2026-10','city':CITIES[1],'issue':'新事项','status':'推进中'}
        self.assertEqual(self.client.post('/api/city-followups',json=changed).status_code,200)
        item=self.client.get('/api/city-followups').json['items'][0]
        older=item['events'][-1]
        self.assertEqual((older['month'],older['city'],older['issue']),(self.payload['month'],self.payload['city'],self.payload['issue']))

    def test_history_is_limited_per_record_not_globally(self):
        ident=self.client.post('/api/city-followups',json=self.payload).json['id']
        with service.connect() as c:
            for n in range(1000):
                c.execute('INSERT INTO city_followup_events (id,record_id,captured_at,status,action,next_date) VALUES (?,?,?,?,?,?)',(f'{n:032x}','f'*32,'2099-01-01T00:00:00','待联系','',''))
        item=self.client.get('/api/city-followups').json['items'][0]
        self.assertEqual(item['id'],ident);self.assertEqual(len(item['events']),1)

