import json,sqlite3,unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch
import app,network_daily,network_query as q

class NetworkQueryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');network_daily.schema(self.db)
        @contextmanager
        def connect():
            with self.db: yield self.db
        self.connect=connect;self.patcher=patch.object(app,'connect',connect);self.patcher.start();app.app.testing=True;self.client=app.app.test_client()
    def tearDown(self):self.patcher.stop();self.db.close()
    def report(self,day='2026-10-21'):
        text='\n'.join(['全省无线网络运行日报','类型','指标',day,'较上月对比','5G','5G数据流量（TB）','100','2%','地市','4G用户数','5G用户数','4G MME附着用户（万户）','Volte在网用户数（万户）','5G终端用户数（万户）','5G活跃用户数（万户）','VONR活跃用户数(万户)','合肥','1','2','3','4','5','安徽省','1','2','3','4','5','地市','全网','全网话务','4G流量（TB)','5G流量（TB）','分流比','合肥','11','12','52%','安徽省','50','100','60%','二、质量','地市','小区名','CGI','规则','原因分析','处理措施','5G','HF','敏感小区名','460-00-1-1','规则','敏感原因','处理措施','三、投诉'])
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',(day,'hash',text,'source','pending_review'))
    def csv(self,day='2026-10-21',city='合肥',**fields):
        self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',('s',day,city,city+day,json.dumps(fields),'unreviewed'))
    def query(self,**kw):return q.query(self.connect,{'day':'2026-10-21','city':'合肥','metric':'5G数据流量',**kw})
    def test_report_and_csv_match_and_do_not_disclose_detail(self):
        self.report();self.csv(nr_upoct='12.004')
        result=self.query();self.assertTrue(result['available']);self.assertIn('12 TB',result['reply']);self.assertIn('历史日报 / 指标CSV',result['reply']);self.assertNotIn('敏感',str(result));self.assertNotIn('460-00',str(result))
    def test_wren_rows_use_same_source_conflict_checks(self):
        self.report()
        with patch('app.wren_daily_bridge.read_rows',return_value=[['合肥',json.dumps({'nr_upoct':'50'})]]) as read, patch.dict('os.environ',{'ZHIHUI_DATABASE':'postgres'}), patch('credential_store.get_assistant_key',return_value='fake'), patch('app.summarize_query') as summary:
            r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月21日合肥5G流量'}]})
            self.assertIn('差异',r.json['reply']);read.assert_called_once_with('2026-10-21');summary.assert_not_called()

    def test_wren_failure_does_not_silently_fallback(self):
        with patch('app.wren_daily_bridge.read_rows',side_effect=ValueError('Wren 本机查询失败')), patch.dict('os.environ',{'ZHIHUI_DATABASE':'postgres'}), patch('credential_store.get_assistant_key',return_value='fake'):
            r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月21日合肥5G流量'}]})
            self.assertIn('Wren 本机查询失败',r.json['reply'])

    def test_overview_reads_wren_source_once(self):
        self.report()
        from unittest.mock import Mock
        reader=Mock(return_value=[['安徽省',json.dumps({'nr_upoct':'100'})]])
        result=q.overview(self.connect,'2026-10-21',source_reader=reader)
        self.assertTrue(result['available']);reader.assert_called_once_with('2026-10-21')

    def test_conflicts_and_missing_do_not_become_zero(self):
        self.report();self.csv(nr_upoct='50')
        result=self.query();self.assertFalse(result['available']);self.assertIn('差异',result['reply']);self.assertNotIn('50 TB',result['reply'])
        result=self.query(city='芜湖');self.assertFalse(result['available']);self.assertIn('未保存',result['reply'])
    def test_all_cities_structured_missing_and_zero(self):
        self.csv(city='合肥',nr_upoct='0');result=self.query(city='全部地市');self.assertEqual(len(result['table']['rows']),16);self.assertIn(['合肥','0 TB','指标CSV'],result['table']['rows']);self.assertIn(['芜湖','—','暂无数据'],result['table']['rows']);self.assertFalse(result['available'])
    def test_latest_is_latest_data_day_not_latest_available_metric(self):
        self.csv(day='2026-10-20',nr_upoct='3');self.csv(day='2026-10-21',lte_upoct='6')
        r=self.query(day='latest');self.assertFalse(r['available']);self.assertIn('2026-10-21',r['reply'])
    def test_uninitialized_database_is_reported_without_writing(self):
        db=sqlite3.connect(':memory:')
        @contextmanager
        def empty():
            with db: yield db
        result=q.query(empty,{'day':'2026-10-21','city':'合肥','metric':'5G数据流量'})
        self.assertFalse(result['available']);self.assertIn('尚未初始化',result['reply'])
        self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],0)
        db.close()

    def test_corrupted_csv_never_silently_ignored(self):
        self.report()
        self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',('s','2026-10-21','合肥','bad','invalid-json','unreviewed'))
        result=self.query();self.assertFalse(result['available']);self.assertIn('核对',result['reply'])

    def test_missing_day_has_no_substitution(self):
        self.report();result=self.query(day='2026-10-22');self.assertFalse(result['available']);self.assertIn('没有已保存',result['reply'])
    def test_5ga_source_is_the_original_daily_report(self):
        raw='\n'.join(['全省无线网络运行日报','地市','3CC开通站点数','3CC开通小区数','5G-A套餐用户数','合肥','12','24','30','汇总','50','80','100','二、网络'])
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x',raw,'s','pending_review'))
        self.assertIn('12 个',self.query(metric='3CC开通站点数')['reply'])
        self.assertIn('50 个',self.query(city='全省',metric='3CC开通站点数')['reply'])
        self.assertIn('30 户',self.query(metric='5G-A套餐用户数')['reply'])
    def test_compound_vendor_counts_are_not_summed(self):
        raw='\n'.join(['地市','设备厂商','通感基站数','扇区数','合肥','华为/爱立信','2/7','6/21','二、网络'])
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x',raw,'s','pending_review'))
        result=self.query(metric='通感基站数');self.assertIn('2/7',result['reply']);self.assertNotIn('9 站',result['reply'])

    def test_requested_overview_phrases(self):
        self.assertEqual(q.overview_plan([{'role':'user','content':'11月2日简述日报内容'}])['day'],'2026-11-02')
        self.assertEqual(q.overview_plan([{'role':'user','content':'11月1日全省网络情况如何'}])['day'],'2026-11-01')

    def test_yesterday_5g_traffic_comparison(self):
        plan=q.comparison_plan('昨天全省 5G 流量比前天怎么样',date(2026,11,5))
        self.assertEqual((plan['day'],plan['base_day']),('2026-11-04','2026-11-03'))
        self.csv(day='2026-11-04',city='安徽省',nr_upoct='120')
        self.csv(day='2026-11-03',city='安徽省',nr_upoct='100')
        result=q.compare(self.connect,plan)
        self.assertTrue(result['available']);self.assertIn('增长20.00TB',result['reply']);self.assertIn('+20.00%',result['reply'])
        self.assertIn('2026-11-03',result['reply']);self.assertIn('2026-11-04',result['reply'])

    def test_comparison_missing_zero_and_conflicts(self):
        plan=q.comparison_plan('昨天全省5G流量比前天怎么样',date(2026,11,5))
        self.csv(day='2026-11-04',city='安徽省',nr_upoct='10')
        self.assertFalse(q.compare(self.connect,plan)['available'])
        self.csv(day='2026-11-03',city='安徽省',nr_upoct='0')
        self.assertIn('无法计算变化率',q.compare(self.connect,plan)['reply'])
        self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',('other','2026-11-03','安徽省','other',json.dumps({'nr_upoct':'11'}),'unreviewed'))
        self.assertFalse(q.compare(self.connect,plan)['available'])

    def test_comparison_and_detail_never_become_aggregate(self):
        for text in ['2026年10月21日合肥5G数据流量同比多少','2026年10月21日合肥某小区5G流量多少','2026年10月21日合肥5G终端用户名单','2026年10月21日和10月22日合肥5G流量','昨天和今天合肥5G流量','昨天到11月2日全省5G流量']:
            with self.subTest(text=text):self.assertIn('error',q.local_plan(text))
        self.assertIn('error',q.local_plan('2026年10月合肥5G流量'))
    def test_date_intent_and_metric_aliases(self):
        self.assertEqual(q.date_in_question('截至10月21日合肥5G流量',date(2026,11,4)),'2026-10-21')
        self.assertEqual(q.date_in_question('2026年10月21日最新合肥5G流量',date(2026,11,4)),'2026-10-21')
        self.assertIsNone(q.date_in_question('2026年2月30日最新合肥5G流量',date(2026,11,4)))
        self.assertEqual(q.recognize('2026年10月21日合肥3CC开通站点数'),'3CC开通站点数')
        self.assertEqual(q.recognize('2026年10月21日合肥SA接通率'),'SA接通率')
        self.assertEqual(q.recognize('2026年11月1日合肥 RedCap 用户的 RRC建立成功率'),'RedCap RRC建立成功率')
        self.assertEqual(q.recognize('2026年10月21日全省5G和4G流量'),'多个指标')
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_unavailable_numeric_daily_metric_is_not_guessed(self,key,plan):
        r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年11月2日全省RedCap用户数量是多少'}]})
        self.assertIn('暂未接入',r.json['reply']);plan.assert_not_called()
        r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年11月2日全省5G用户数'}]})
        self.assertIn('暂未接入',r.json['reply']);plan.assert_not_called()

    @patch('app.summarize_query',return_value='合肥当日5G数据流量为12 TB。')
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_endpoint_queries_only_local_aggregates(self,key,plan,summary):
        self.report();self.csv(nr_upoct='12');r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月21日合肥5G流量'}]})
        self.assertEqual(r.status_code,200);self.assertTrue(r.json['local_query']);self.assertIn('12 TB',r.json['reply']);plan.assert_not_called()
        args=str(summary.call_args);self.assertNotIn('敏感',args);self.assertNotIn('460-00',args)
    @patch('app.summarize_query')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_conflicts_not_sent_to_model(self,key,summary):
        self.report();self.csv(nr_upoct='50');r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月21日合肥5G流量'}]});self.assertIn('差异',r.json['reply']);summary.assert_not_called()
    @patch('app.summarize_query',side_effect=ValueError('offline'))
    @patch('app.plan_query',return_value={'reply':'请指定具体指标。'})
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_daily_overview_and_followup_use_safe_aggregates(self,key,plan,summary):
        self.report()
        for messages in ([{'role':'user','content':'简述2026年10月21日日报内容'}],
                         [{'role':'user','content':'简述2026年10月21日日报内容'},{'role':'assistant','content':'请指定具体指标。'},{'role':'user','content':'你都讲一下'}]):
            r=self.client.post('/api/assistant/query-chat',json={'messages':messages})
            self.assertEqual(r.status_code,200)
            self.assertIn('100',r.json['reply'])
            self.assertNotIn('敏感',str(r.json))
        plan.assert_not_called()
        self.assertNotIn('敏感',str(summary.call_args_list))
        self.assertNotIn('460-00',str(summary.call_args_list))

    def test_overview_followup_inherits_only_previous_daily_date(self):
        prior={'role':'user','content':'简述11月2号日报内容'}
        follow={'role':'user','content':'你跟我简述一下全省的情况'}
        self.assertEqual(q.overview_plan([prior,{'role':'assistant','content':'请确认范围'},follow]),{'day':'2026-11-02'})
        self.assertIsNone(q.overview_plan([prior,{'role':'user','content':'讲讲天气'},follow]))
        self.assertEqual(q.overview_plan([prior,{'role':'user','content':'简述11月1日全省的情况'}]),{'day':'2026-11-01'})

    def test_followup_uses_only_previous_explicit_query(self):
        import query_context
        p={'role':'user','content':'2026年10月21日合肥5G流量'}
        follow={'role':'user','content':'全省呢'}
        self.assertEqual(query_context.resolve_network_followup([p,follow])['arguments'],{'day':'2026-10-21','city':'全省','metric':'5G数据流量'})
        self.assertIsNone(query_context.resolve_network_followup([p,{'role':'user','content':'天气如何'},follow]))
        self.assertIsNone(query_context.resolve_network_followup([p,{'role':'user','content':'全省同比呢'}]))

    def test_overview_requires_unambiguous_date_and_scope(self):
        for question in ('简述日报内容','简述10月21日和10月22日日报内容','简述10月21日合肥日报内容','总结10月21日日报小区明细'):
            with self.subTest(question=question):self.assertIn('error',q.overview_plan([{'role':'user','content':question}]))
        self.assertIsNone(q.overview_plan([{'role':'user','content':'什么是5G？'},{'role':'assistant','content':'请问什么？'},{'role':'user','content':'你都讲一下'}]))

    @patch('app.summarize_query',return_value='全省5G数据流量为100 TB。')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_overview_ai_only_gets_aggregates(self,key,summary):
        self.report()
        r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'简述2026年10月21日日报内容'}]})
        self.assertEqual(r.json['summary_kind'],'ai')
        self.assertIn('100 TB',r.json['reply'])
        self.assertIn('仅涵盖',r.json['reply'])
        self.assertNotIn('敏感',str(summary.call_args))
        self.assertNotIn('460-00',str(summary.call_args))

    @patch('app.plan_query',return_value={'tool':'query_network_daily','arguments':{'day':'2026-10-21','city':'合肥','metric':'5G数据流量'}})
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_model_cannot_invent_tool_params(self,key,plan):
        self.report();r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'帮我看下网络怎么样'}]});self.assertIn('无法确定',r.json['reply']);self.assertNotIn('100',r.json['reply'])

if __name__=='__main__':unittest.main()
