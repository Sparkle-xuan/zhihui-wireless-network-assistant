import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app as service
import city_alerts
import blackspot_history
import alert_rules
from core import CITIES


class CityAlertsTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'test.sqlite3';service.app.testing=True
        self.client=service.app.test_client()
        rows=[{'city':c,'included':10,'qualified':v} for c,v in zip(CITIES,[0,1,2,2]+[8]*11+[0])]
        rows[-1]={'city':CITIES[-1],'included':0,'qualified':0}
        self.data={'cities':rows,'total':{'included':150,'qualified':100}}
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-10-30',json.dumps(self.data),'{}','周报',''))
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.tmp.cleanup()
    def test_rank_ties_zero_denominator_and_idempotent(self):
        first=city_alerts.generate(service.connect,'2026-10')
        self.assertEqual(first['created'],4)
        self.assertEqual(city_alerts.generate(service.connect,'2026-10')['created'],0)
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        self.assertEqual({i['city'] for i in items},set(CITIES[:4]))
        self.assertTrue(all(i['status']=='draft' for i in items))
        self.assertTrue(all(i['details']['period']=='2026-10-30' for i in items))
    def test_changed_data_never_overwrites_existing_drafts(self):
        city_alerts.generate(service.connect,'2026-10')
        self.data['cities'][0]['qualified']=5
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.data),'2026-10-30'))
        with self.assertRaisesRegex(ValueError,'未覆盖'):city_alerts.generate(service.connect,'2026-10')
        self.assertEqual(len(city_alerts.list_alerts(service.connect,'2026-10')['items']),4)
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report') as send:
            payload={'sender':'sender@qq.com','recipient':'to@example.com','subject':'提醒','body':'请关注。','auth_code':''}
            response=self.client.post('/api/city-alerts/2026-10/'+CITIES[0]+'/send',json=payload)
            self.assertEqual(response.status_code,400);self.assertIn('数据已变化',response.json['error']);send.assert_not_called()
        result=city_alerts.generate(service.connect,'2026-10',replace_drafts=True)
        self.assertGreater(result['created'],0)
    def test_missing_and_no_denominator_never_make_drafts(self):
        with self.assertRaises(ValueError):city_alerts.generate(service.connect,'2098-10')
        for row in self.data['cities']:row['included']=row['qualified']=0
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.data),'2026-10-30'))
        with self.assertRaises(ValueError):city_alerts.generate(service.connect,'2026-10')
        self.assertEqual(city_alerts.list_alerts(service.connect,'2026-10')['items'],[])
    def test_contacts_validation_and_drafts_read_latest_contacts(self):
        city_alerts.generate(service.connect,'2026-10')
        city_alerts.save_contacts(service.connect,{CITIES[0]:'person@example.com'})
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        self.assertEqual(next(x['recipient'] for x in items if x['city']==CITIES[0]),'person@example.com')
        with self.assertRaises(ValueError):city_alerts.save_contacts(service.connect,{CITIES[0]:'a@example.com,b@example.com'})
    def test_configurable_thresholds_and_missing_history(self):
        rules={**alert_rules.DEFAULT,'bottom_three':False,'minimum_rate':30,'unfinished_at_least':9}
        alert_rules.save(service.connect,rules)
        city_alerts.generate(service.connect,'2026-10')
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        self.assertEqual({x['city'] for x in items},set(CITIES[:4]))
        self.assertIn('解决率低于 30%',items[0]['details']['reasons'])
        self.assertEqual(self.client.get('/api/city-alerts/rules').json,rules)
        with self.assertRaises(ValueError):alert_rules.save(service.connect,{**rules,'minimum_rate':101})
        alert_rules.save(service.connect,{**alert_rules.DEFAULT,'two_month_decline':True})
        with self.assertRaisesRegex(ValueError,'2026-09'):city_alerts.calculate(service.connect,'2026-10')
    def test_suspension_increase_requires_complete_data(self):
        alert_rules.save(service.connect,{**alert_rules.DEFAULT,'bottom_three':False,'suspension_increase_at_least':2})
        def sample(month):
            return {'period':month+'-25','kind':'weekly','city_note':'', 'cities':[{'name':city,'value':(4 if month=='2026-10' and i==0 else 1)} for i,city in enumerate(CITIES)]}
        city_alerts.generate(service.connect,'2026-10',suspension_reader=sample)
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        self.assertEqual([x['city'] for x in items],[CITIES[0]])
        self.assertIn('挂起较上月增加 3 处',items[0]['details']['reasons'])
        with self.assertRaisesRegex(ValueError,'不完整'):city_alerts.calculate(service.connect,'2026-10',suspension_reader=lambda _:None)
    def test_consecutive_decline_uses_three_actual_months(self):
        for period,qualified in [('2026-08-28',4),('2026-09-25',3)]:
            rows=[{'city':city,'included':10,'qualified':qualified if i==1 else 8} for i,city in enumerate(CITIES)]
            snapshot={'cities':rows,'total':{'included':160,'qualified':100}}
            with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',(period,json.dumps(snapshot),'{}','周报',''))
        alert_rules.save(service.connect,{**alert_rules.DEFAULT,'bottom_three':False,'two_month_decline':True})
        city_alerts.generate(service.connect,'2026-10')
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        self.assertEqual([i['city'] for i in items],[CITIES[1]])
        self.assertIn('解决率连续两个月下降',items[0]['details']['reasons'])
    def test_custom_rules_read_current_snapshot_only_once(self):
        alert_rules.save(service.connect,{**alert_rules.DEFAULT,'minimum_rate':30})
        old=json.dumps(self.data)
        changed=json.loads(old)
        changed['cities'][0]['qualified']=9
        fresh=json.dumps(changed)
        calls=[]
        def source(period):
            calls.append(period)
            return (old if len(calls)==1 else fresh,None,'周报','')
        _,rows,_=city_alerts.calculate(service.connect,'2026-10',source_reader=source)
        self.assertEqual(calls,['2026-10-30'])
        row=next(r for r in rows if r[0]==CITIES[0])
        self.assertEqual(row[2],'0');self.assertIn('解决率倒数靠前',row[4])
    def test_send_requires_saved_credential_and_cannot_duplicate(self):
        city_alerts.generate(service.connect,'2026-10')
        data={'sender':'sender@qq.com','recipient':'to@example.com','subject':'提醒','body':'请关注。','auth_code':''}
        url='/api/city-alerts/2026-10/'+CITIES[0]+'/send'
        with patch('credential_store.get_for_sender',return_value=None),patch('app.send_report') as send:
            self.assertEqual(self.client.post(url,json=data).status_code,400);send.assert_not_called()
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report') as send:
            self.assertEqual(self.client.post(url,json=data).status_code,200)
            self.assertEqual(self.client.post(url,json=data).status_code,400)
            self.assertEqual(send.call_count,1)
        item=next(i for i in city_alerts.list_alerts(service.connect,'2026-10')['items'] if i['city']==CITIES[0])
        self.assertEqual(item['status'],'sent');self.assertEqual(item['recipient'],'to@example.com')
        self.data['cities'][1]['qualified']=6
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.data),'2026-10-30'))
        city_alerts.generate(service.connect,'2026-10',replace_drafts=True)
        items=city_alerts.list_alerts(service.connect,'2026-10')['items']
        sent=next(i for i in items if i['city']==CITIES[0])
        self.assertEqual(sent['status'],'sent');self.assertEqual(sent['recipient'],'to@example.com')
        self.assertTrue(any(i['status']=='draft' for i in items))
    def test_auth_failure_remains_editable_and_can_retry(self):
        from mailing import MailNotSentError
        city_alerts.generate(service.connect,'2026-10')
        data={'sender':'sender@qq.com','recipient':'to@example.com','subject':'提醒','body':'请关注。','auth_code':'test'}
        url='/api/city-alerts/2026-10/'+CITIES[0]+'/send'
        with patch('app.send_report',side_effect=[MailNotSentError('验证失败'),None]):
            failed=self.client.post(url,json=data)
            self.assertFalse(failed.json['locked'])
            self.assertEqual(next(i for i in city_alerts.list_alerts(service.connect,'2026-10')['items'] if i['city']==CITIES[0])['status'],'draft')
            self.assertEqual(self.client.post(url,json=data).status_code,200)
    def test_uncertain_delivery_is_locked_and_keeps_final_body(self):
        city_alerts.generate(service.connect,'2026-10')
        data={'sender':'sender@qq.com','recipient':'to@example.com','subject':'提醒','body':'核对后的内容','auth_code':''}
        url='/api/city-alerts/2026-10/'+CITIES[0]+'/send'
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report',side_effect=ValueError('发送状态未确认')) as send:
            failed=self.client.post(url,json=data)
            self.assertTrue(failed.json['locked']);self.assertEqual(self.client.post(url,json=data).status_code,400);self.assertEqual(send.call_count,1)
        item=next(i for i in city_alerts.list_alerts(service.connect,'2026-10')['items'] if i['city']==CITIES[0])
        self.assertEqual((item['status'],item['body']),('unknown','核对后的内容'))
        self.data['cities'][1]['qualified']=6
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.data),'2026-10-30'))
        with self.assertRaisesRegex(ValueError,'先核对'):city_alerts.generate(service.connect,'2026-10',replace_drafts=True)
        reset='/api/city-alerts/2026-10/'+CITIES[0]+'/reset'
        self.assertEqual(self.client.post(reset,json={}).status_code,400)
        self.assertEqual(self.client.post(reset,json={'confirmed_not_sent':True}).status_code,200)
        item=next(i for i in city_alerts.list_alerts(service.connect,'2026-10')['items'] if i['city']==CITIES[0])
        self.assertEqual(item['status'],'draft')
    def test_inflight_and_sent_items_cannot_be_reset(self):
        city_alerts.generate(service.connect,'2026-10')
        with service.connect() as c:c.execute("UPDATE city_alert_items SET status='sending' WHERE month=? AND city=?",('2026-10',CITIES[0]))
        with self.assertRaises(ValueError):city_alerts.reset_uncertain(service.connect,'2026-10',CITIES[0])
        with service.connect() as c:c.execute("UPDATE city_alert_items SET status='sent' WHERE month=? AND city=?",('2026-10',CITIES[0]))
        with self.assertRaises(ValueError):city_alerts.reset_uncertain(service.connect,'2026-10',CITIES[0])
    def test_schedule_is_disabled_by_default_and_never_sends(self):
        self.assertFalse(city_alerts.schedule(service.connect)['enabled'])
        with patch('app.send_report') as send:
            self.assertIsNone(city_alerts.check_due(service.connect,now=datetime(2026,10,30,19)))
            city_alerts.set_schedule(service.connect,True,18,0)
            text=city_alerts.check_due(service.connect,now=datetime(2026,10,30,19))
            self.assertIn('2026-10',text);self.assertEqual(len(city_alerts.list_alerts(service.connect,'2026-10')['items']),4);send.assert_not_called()
            self.assertIsNone(city_alerts.check_due(service.connect,now=datetime(2026,10,30,19,5)))
    def test_after_downtime_latest_due_month_and_missing_retry(self):
        self.assertEqual(city_alerts.due_month(datetime(2026,11,2,10),18,0),'2026-10')
        self.assertEqual(city_alerts.due_month(datetime(2026,10,30,17,59),18,0),'2026-09')
        city_alerts.set_schedule(service.connect,True,18,0)
        message=city_alerts.check_due(service.connect,now=datetime(2027,1,1,19))
        self.assertIn('未完成',message)
        self.assertEqual(city_alerts.schedule(service.connect)['checked_month'],'2026-12')
    def test_scheduled_check_does_not_use_earlier_historical_version(self):
        blackspot_history.save(service.connect,'2026-09-24',self.data)
        city_alerts.set_schedule(service.connect,True,18,0)
        message=city_alerts.check_due(service.connect,now=datetime(2026,9,25,19))
        self.assertIn('最后一个周五',message)
        self.assertEqual(city_alerts.list_alerts(service.connect,'2026-09')['items'],[])


if __name__=='__main__':unittest.main()
