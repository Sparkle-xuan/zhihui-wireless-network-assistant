import json,tempfile,unittest
from pathlib import Path
import suspension,app as service
from core import CITIES

class SuspensionModelTests(unittest.TestCase):
    def make(self,group):return suspension.summary(json.dumps({'suspended':group},ensure_ascii=False),'2026-10-30','weekly')
    def test_normal_and_missing_parts(self):
        data=self.make({'count':5,'cities':[['合肥',3],['安庆',2]],'categories':{'无项目':3,'低价值':2}})
        self.assertEqual(len(data['cities']),16);self.assertEqual(data['cities'][0]['name'],CITIES[0]);self.assertEqual(data['cities'][0]['value'],2)
        self.assertEqual(sum(x['value'] for x in data['categories']),5)
        data=self.make({'count':5})
        self.assertIsNone(data['cities']);self.assertIsNone(data['categories']);self.assertIn('未保存',data['city_note'])
    def test_incomplete_and_conflicting_breakdowns(self):
        data=self.make({'count':5,'cities':[['合肥',2]],'categories':{'无项目':3}})
        self.assertIn('3 处',data['city_note']);self.assertEqual(data['categories'][-1],{'name':'未记录分类','value':2})
        data=self.make({'count':1,'cities':[['合肥',2]],'categories':{'无项目':2}})
        self.assertIsNone(data['cities']);self.assertIsNone(data['categories']);self.assertIn('大于总数',data['category_note'])
    def test_invalid_not_zero(self):
        for count in [None,-1,True,1.5]:
            with self.subTest(count=count),self.assertRaises(ValueError):self.make({'count':count,'cities':[],'categories':{}})
        data=self.make({'count':0,'cities':[],'categories':{}})
        self.assertEqual(data['total'],0);self.assertEqual(data['categories'],[])

class SuspensionApiTests(unittest.TestCase):
    def setUp(self):
        self.old_db=service.DB;self.old_testing=service.app.testing;service.app.testing=True
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);service.DB=Path(self.temp.name)/'data.sqlite3';self.client=service.app.test_client()
    def tearDown(self):service.DB=self.old_db;service.app.testing=self.old_testing;self.temp.cleanup()
    def put(self,period,weekly=None,monthly=None,weekly_text='',monthly_text='月报'):
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',(period,json.dumps(weekly or monthly or {}),'{}',weekly_text,monthly_text,json.dumps(monthly) if monthly is not None else None))
    def snapshot(self,values):
        return {'suspended':{'count':sum(values.values()),'cities':list(values.items()),'categories':{'无项目':sum(values.values())}}}
    def test_last_friday_weekly_and_previous_month(self):
        self.put('2026-09-25',weekly=self.snapshot({'合肥':2,'安庆':3}),weekly_text='周报',monthly_text='')
        self.put('2026-10-23',weekly=self.snapshot({'合肥':99}),weekly_text='周报',monthly_text='')
        self.put('2026-10-30',weekly=self.snapshot({'合肥':7,'安庆':2,'芜湖':2,'宣城':2}),monthly=self.snapshot({'合肥':100}),weekly_text='PRIVATE',monthly_text='PRIVATE')
        self.put('2026-11-06',weekly=self.snapshot({'合肥':8}),monthly_text='',weekly_text='周报')
        periods=self.client.get('/api/suspension/periods').get_json()
        self.assertEqual([(x['month'],x['available']) for x in periods],[('2026-11',False),('2026-10',True),('2026-09',True)])
        response=self.client.get('/api/suspension/month/2026-10');self.assertEqual(response.status_code,200);data=response.get_json()
        self.assertEqual(data['period'],'2026-10-30');self.assertEqual(data['kind'],'weekly');self.assertEqual(data['total'],13);self.assertEqual(data['comparison']['delta'],8)
        self.assertEqual(next(x['delta'] for x in data['comparison']['cities'] if x['name']=='合肥'),5)
        self.assertEqual(len(data['warning_cities']),4);self.assertNotIn('PRIVATE',str(data))
        response=self.client.get('/api/suspension/month/2026-11');self.assertEqual(response.status_code,404);self.assertIn('2026-11-27',response.get_json()['error'])
    def test_no_prior_month_and_invalid_month(self):
        self.put('2026-10-30',weekly=self.snapshot({'合肥':3}),weekly_text='周报',monthly_text='')
        d=self.client.get('/api/suspension/month/2026-10').get_json();self.assertFalse(d['comparison']['available']);self.assertIsNone(d['comparison']['delta'])
        for value in ['2026-13','2026-1','bad']:
            self.assertEqual(self.client.get('/api/suspension/month/'+value).status_code,422)
        self.assertEqual(service.suspension_last_friday('2026-01'),'2026-01-30')
        self.assertEqual(suspension.previous_month('2026-01'),'2025-12')
    def test_same_friday_monthly_fallback_and_other_date_not_substituted(self):
        self.put('2026-09-18',weekly=self.snapshot({'合肥':7}),weekly_text='周报',monthly_text='')
        self.put('2026-10-30',monthly=self.snapshot({'合肥':4}))
        result=self.client.get('/api/suspension/month/2026-10').get_json()
        self.assertEqual(result['kind'],'monthly');self.assertEqual(result['total'],4);self.assertFalse(result['comparison']['available'])
        self.assertEqual(self.client.get('/api/suspension/month/2026-09').status_code,404)
    def test_incomplete_city_data_does_not_produce_ranking_or_change(self):
        self.put('2026-09-25',weekly=self.snapshot({'合肥':1}),weekly_text='周报',monthly_text='')
        self.put('2026-10-30',weekly={'suspended':{'count':5,'cities':[['合肥',2]],'categories':{'无项目':5}}},weekly_text='周报',monthly_text='')
        d=self.client.get('/api/suspension/month/2026-10').get_json()
        self.assertIsNone(d['warning_cities']);self.assertIsNone(d['comparison']['cities']);self.assertEqual(d['comparison']['delta'],4)

    def test_partial_manual_history_is_safe_and_compares_only_known_cities(self):
        payload={'month':'2026-09','total':20,'cities':{'合肥':10,'安庆':3},'categories':{'无项目':20}}
        self.assertEqual(self.client.post('/api/suspension/manual',json=payload).status_code,200)
        self.assertEqual(self.client.post('/api/suspension/manual',json=payload).status_code,409)
        self.put('2026-10-30',weekly=self.snapshot({'合肥':12,'安庆':2,'宣城':4}),weekly_text='周报',monthly_text='')
        previous=self.client.get('/api/suspension/month/2026-09').get_json()
        self.assertEqual(previous['kind'],'manual');self.assertIsNone(previous['period']);self.assertEqual(len(previous['cities']),2);self.assertIsNone(previous['warning_cities'])
        current=self.client.get('/api/suspension/month/2026-10').get_json();comp=current['comparison']
        self.assertEqual(comp['delta'],-2);self.assertEqual(comp['previous_kind'],'manual');self.assertEqual({x['name']:x['delta'] for x in comp['cities']},{'安庆':-1,'合肥':2})
        self.assertIn('仅提供部分地市',comp['note'])
        self.put('2026-09-25',weekly=self.snapshot({'合肥':7}),weekly_text='周报',monthly_text='')
        self.assertEqual(self.client.get('/api/suspension/month/2026-09').get_json()['kind'],'weekly')
    def test_manual_validation_rejects_impossible_and_unknown_values(self):
        for payload in [{'month':'2026-09','total':2,'cities':{'合肥':3},'categories':{}},{'month':'2026-09','total':2,'cities':{'不存在':1},'categories':{}},{'month':'2026-09','total':2,'cities':{},'categories':{'甲':3}}]:
            self.assertEqual(self.client.post('/api/suspension/manual',json=payload).status_code,400)

    def test_workbook_import_preserves_source_date_and_handles_missing_category(self):
        from openpyxl import Workbook
        from io import BytesIO
        def workbook(category=True):
            w=Workbook();sheet=w.active;sheet.title='挂起';sheet.append(['工单Id','地市']+(['waitingClassifyName'] if category else []));sheet.append(['x','合肥']+(['无项目'] if category else []));out=BytesIO();w.save(out);out.seek(0);return out
        def upload(day,filename,category=True):
            return self.client.post('/api/suspension/import',data={'source_date':day,'file':(workbook(category),filename)},content_type='multipart/form-data')
        self.assertEqual(upload('2026-09-24','2026-0924.xlsx').status_code,200)
        self.assertEqual(upload('2026-09-24','2026-0924.xlsx').status_code,200)
        self.assertEqual(upload('2026-08-28','2026-0828.xlsx',False).status_code,200)
        self.assertEqual(upload('2026-07-31','2026-0730.xlsx').status_code,400)
        previous=self.client.get('/api/suspension/month/2026-08').get_json();self.assertIsNone(previous['categories']);self.assertTrue(previous['category_note'])
        current=self.client.get('/api/suspension/month/2026-09').get_json();self.assertEqual(current['kind'],'imported');self.assertEqual(current['period'],'2026-09-24');self.assertEqual(current['comparison']['delta'],0)
        self.put('2026-09-25',weekly=self.snapshot({'合肥':4}),weekly_text='周报',monthly_text='')
        self.assertEqual(self.client.get('/api/suspension/month/2026-09').get_json()['period'],'2026-09-24')

if __name__=='__main__':unittest.main()
