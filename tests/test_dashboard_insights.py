import unittest
from unittest.mock import patch
import app
import dashboard_insights
from core import CITIES


class DashboardInsightsTests(unittest.TestCase):
    def month(self, date, rate=5, suspended=10):
        return {'cities':[{'name':name,'included':10,'qualified':rate,'rate':rate*10.0} for name in CITIES],
                'source_info':{'period':date+'-30','kind':'weekly'},
                'suspension':{'total':suspended,'period':date+'-30','kind':'weekly','city_note':None,
                              'cities':[{'name':name,'value':i} for i,name in enumerate(CITIES)]}}
    def day(self, day, source='日报'):
        return {'day':day,'cards':[{'label':name,'value':value,'source':source} for name,value in [('5G数据流量','10'),('4G数据流量','5'),('5G分流比','70')]]}
    def test_exact_periods_and_ties(self):
        months={'2026-10':self.month('2026-10',6,15),'2026-09':self.month('2026-09',5,10)}
        days=[]
        def daily(day):days.append(day);return self.day(day)
        result=dashboard_insights.build('2026-10','2026-11-02',months.get,daily)
        self.assertEqual(days,['2026-11-02','2026-11-01'])
        self.assertAlmostEqual(result['changes']['黑点解决率']['delta'],10)
        self.assertEqual(result['changes']['挂起库数量']['delta'],5)
        self.assertEqual(len(result['focus'][0]['items']),16) # all tied at the cutoff
    def test_missing_or_conflicting_sources_are_not_zero(self):
        current=self.month('2026-10');current['cities']=current['cities'][:-1];current['suspension']['city_note']='部分数据缺失'
        result=dashboard_insights.build('2026-10','2026-11-02',lambda m:current if m=='2026-10' else {},lambda d:self.day(d,'日报' if d.endswith('02') else 'CSV'))
        self.assertIsNone(result['changes']['5G数据流量']['delta'])
        self.assertIsNone(result['changes']['黑点解决率']['delta'])
        self.assertIsNone(result['changes']['挂起库数量']['delta'])
        self.assertEqual(result['focus'],[])
    def test_zero_denominator_is_not_ranked(self):
        m=self.month('2026-10');m['cities'][0].update(included=0,qualified=0,rate=None)
        result=dashboard_insights.build('2026-10','2026-11-02',lambda _:m,lambda d:self.day(d))
        self.assertNotIn(CITIES[0],[i['city'] for i in result['focus'][0]['items']])
    def test_summary_uses_server_facts_and_requires_key(self):
        with patch.object(app,'dashboard_insight_data',return_value={'summary':'2026-10黑点解决率60.00%。'}),patch.object(app.credential_store,'get_assistant_key',return_value=None):
            response=app.app.test_client().post('/api/dashboard/insights/summary',base_url='http://localhost:5088',headers={'Origin':'http://localhost:5088'},json={'month':'2026-10','day':'2026-11-02','summary':'伪造的数据'})
        self.assertEqual(response.status_code,400)
        self.assertIn('密钥',response.get_json()['error'])
    def test_city_report_uses_the_requested_city_and_local_facts(self):
        facts={'month':'2026-10','period':'2026-10-30','source':'周报','trend':[{}, {'period':'2026-09-25','source':'周报'}],
               'cities':[{'city':'合肥','included':10,'qualified':6,'rate':60.0,'change':5.0,'highlight':False},
                         {'city':'芜湖','included':10,'qualified':9,'rate':90.0,'change':1.0,'highlight':False}]}
        with patch('analysis_report.create_report',return_value={'facts':facts,'advice':'','advice_notice':'本地'}),patch.object(app.analysis_mail,'save',return_value='a'*32):
            response=app.app.test_client().post('/api/analysis-report',base_url='http://localhost:5088',headers={'Origin':'http://localhost:5088'},json={'month':'2026-10','city':'合肥'})
        self.assertEqual(response.status_code,200)
        html=response.get_json()['html']
        self.assertIn('合肥重点投诉区域分析',html)
        self.assertNotIn('芜湖',html)


if __name__=='__main__':unittest.main()
