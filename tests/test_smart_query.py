import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as service
import assistant_service
from smart_query import query
from core import CITIES, STAGES
from smart_query import identify_explicit_metric


class SmartQueryTests(unittest.TestCase):
    def setUp(self):
        self.old_db=service.DB
        self.old_testing=service.app.testing
        service.app.testing=True
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.temp.name)/'query.sqlite3'
        self.client=service.app.test_client()
        self.week={'snapshot_version':2,'total':{'included':10,'qualified':5},'cities':[{'city':'合肥','included':10,'qualified':5}],'suspended':{'count':3,'cities':[['合肥',3]],'categories':{}}}
        self.month={'snapshot_version':2,'total':{'included':20,'qualified':15},'cities':[{'city':'合肥','included':20,'qualified':15}],'suspended':{'count':7,'cities':[['合肥',7]],'categories':{}}}

    def tearDown(self):
        service.DB=self.old_db
        service.app.testing=self.old_testing
        self.temp.cleanup()

    def insert(self,period='2026-10-30',weekly=True,monthly=True,week=None,month=None):
        with service.connect() as c:
            c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',(period,json.dumps(week or self.week),'{}','周报' if weekly else '','月报' if monthly else '',json.dumps(month or self.month) if monthly else None))

    def test_suspension_query_uses_selected_partial_bulletin_without_inventing_cities(self):
        selected={'kind':'manual','period':None,'total':10,'cities':[{'name':'合肥','value':7}],'city_note':'仅记录部分地市'}
        args={'month':'2026-07','city':'全省'}
        result=query(service.connect,'query_suspended',args,structured=True,suspension_reader=lambda month:selected)
        self.assertTrue(result['available']);self.assertIn('10处',result['reply']);self.assertIn('日期未提供',result['reply'])
        args['city']='合肥';self.assertIn('7处',query(service.connect,'query_suspended',args,structured=True,suspension_reader=lambda month:selected)['reply'])
        args['city']='安庆';self.assertFalse(query(service.connect,'query_suspended',args,structured=True,suspension_reader=lambda month:selected)['available'])
        args['city']='全部地市';result=query(service.connect,'query_suspended',args,structured=True,suspension_reader=lambda month:selected);self.assertEqual(result['table']['rows'],[['合肥','7']])

    @patch('app.summarize_query',side_effect=ValueError('offline'))
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_chat_reads_preferred_suspension_bulletin(self,key,summary):
        payload={'month':'2026-07','total':10,'cities':{'合肥':7},'categories':{},'preferred':True}
        self.assertEqual(self.client.post('/api/suspension/manual',json=payload).status_code,200)
        plan={'tool':'query_suspended','arguments':{'month':'2026-07','city':'合肥'}}
        with patch('app.plan_query',return_value=plan):
            response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年7月合肥挂起库数量'}]})
        self.assertEqual(response.status_code,200);self.assertIn('7处',response.json['reply']);self.assertIn('日期未提供',response.json['reply'])

    def test_monthly_precedence_and_rate(self):
        self.insert()
        result=query(service.connect,'query_city_metrics',{'month':'2026-10','city':'合肥市','metric':'解决率'})
        self.assertIn('2026-10-30',result);self.assertIn('合肥市黑点解决率为75.00%',result);self.assertIn('确认纳入20处',result);self.assertIn('质检合格15处',result);self.assertIn('尚未质检合格',result);self.assertIn('月报快照',result)

    def test_missing_month_end_no_fallback(self):
        self.insert('2026-10-23')
        self.assertIn('缺少最后一个周五',query(service.connect,'query_suspended',{'month':'2026-10','city':'全省'}))

    def test_older_data_missing_city_does_not_become_zero(self):
        old={'total':{'included':1,'qualified':1},'cities':[],'suspended':{'count':5}}
        self.insert(weekly=True,monthly=False,week=old)
        self.assertIn('全省挂起库累计5处',query(service.connect,'query_suspended',{'month':'2026-10','city':'全省'}))
        with self.assertRaisesRegex(ValueError,'未保存'):
            query(service.connect,'query_suspended',{'month':'2026-10','city':'合肥'})

    def test_unknown_tool_and_untrusted_inputs_rejected(self):
        for name,args in [('delete',{'month':'2026-10','city':'全省'}),('query_suspended',{'month':'2026-10','city':'全省','sql':'DROP'}),('query_suspended',{'month':'2026-99','city':'全省'})]:
            with self.subTest(name=name,args=args),self.assertRaises(ValueError):query(service.connect,name,args)

    def test_all_cities_return_structured_tables(self):
        dataset={'snapshot_version':2,'total':{'included':20,'qualified':15},'cities':[{'city':city,'included':10,'qualified':5} for city in CITIES],'suspended':{'count':7,'cities':[['合肥',7]],'categories':{}}}
        self.insert(weekly=True,monthly=False,week=dataset)
        result=query(service.connect,'query_city_metrics',{'month':'2026-10','city':'全部地市','metric':'解决率'},structured=True)
        self.assertEqual(len(result['table']['rows']),16)
        self.assertEqual(result['table']['rows'][0],[CITIES[0],'10','5','50.00%'])
        self.assertIn('整体解决率为50.00%',result['reply'])
        self.assertIn('确认纳入160处',result['reply'])
        result=query(service.connect,'query_suspended',{'month':'2026-10','city':'全部地市'},structured=True)
        self.assertIn(['合肥','7'],result['table']['rows'])
        self.assertIn('2026-10-30',result['reply'])

    @patch('app.summarize_query',return_value='截至2026年10月，合肥市挂起库累计7处。')
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_endpoint_routes_to_local_query(self,get_key,plan,summarize):
        self.insert()
        plan.return_value={'tool':'query_suspended','arguments':{'month':'2026-10','city':'合肥'}}
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'10月合肥挂起多少'}]})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['local_query']);self.assertIn('合肥市挂起库累计7处',response.json['reply'])
        self.assertIn('合肥市挂起库累计7处',response.json['evidence'])
        self.assertEqual(response.json['summary_kind'],'ai')
        self.assertNotIn('累计7处',str(plan.call_args))

    @patch('app.summarize_query',return_value='合肥挂起7处。')
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_selected_model_used_for_both_planning_and_summary(self,get_key,plan,summarize):
        self.insert()
        plan.return_value={'tool':'query_suspended','arguments':{'month':'2026-10','city':'合肥'}}
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月合肥挂起库多少处'}],'model':'deepseek-v4-pro'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(plan.call_args.kwargs['model'],'deepseek-v4-pro')
        self.assertEqual(summarize.call_args.kwargs['model'],'deepseek-v4-pro')

    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_reject_unapproved_model(self,get_key,plan):
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'你好'}],'model':'other-provider'})
        self.assertEqual(response.status_code,400)
        plan.assert_not_called()

    @patch('app.summarize_query',side_effect=ValueError('mock failure'))
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_summary_failure_falls_back_to_local_result(self,get_key,plan,summarize):
        self.insert()
        plan.return_value={'tool':'query_suspended','arguments':{'month':'2026-10','city':'合肥'}}
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'10月合肥挂起多少'}]})
        self.assertIn('合肥市挂起库累计7处',response.json['reply'])
        self.assertIn('AI 总结暂不可用',response.json['summary_notice'])

    @patch('app.summarize_query')
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_missing_data_is_not_sent_for_summary(self,get_key,plan,summarize):
        plan.return_value={'tool':'query_suspended','arguments':{'month':'2026-10','city':'合肥'}}
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'10月合肥挂起多少'}]})
        self.assertIn('缺少最后一个周五',response.json['reply'])
        summarize.assert_not_called()

    @patch('app.summarize_query',side_effect=ValueError('offline'))
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_application_suspended_alias_and_conflict(self,key,planner,summary):
        self.insert()
        r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月合肥申请挂起数量'}]})
        self.assertEqual(r.status_code,200);self.assertIn('7处',r.json['reply']);planner.assert_not_called()

    def test_suspended_source_conflicts_are_not_summarized_as_equal(self):
        self.month['total']['suspended']=8
        self.insert()
        result=query(service.connect,'query_suspended',{'month':'2026-10','city':'全省'},structured=True)
        self.assertFalse(result['available']);self.assertIn('不一致',result['reply'])

    @patch('app.summarize_query',side_effect=ValueError('offline'))
    @patch('app.plan_query',return_value={'tool':'query_suspended','arguments':{'month':'2026-10','city':'合肥'}})
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_wren_snapshot_preserves_monthly_selection(self,key,plan,summary):
        row=[json.dumps(self.week),json.dumps(self.month),'yes','yes']
        with patch.dict('os.environ',{'ZHIHUI_DATABASE':'postgres'}),patch('app.selected_suspension',return_value=None),patch('app.wren_daily_bridge.read_snapshot',return_value=row) as reader:
            r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月合肥挂起库多少'}]})
        self.assertIn('7处',r.json['reply']);reader.assert_called_once_with('2026-10-30')

    def test_wren_snapshot_missing_report_not_zero(self):
        result=query(service.connect,'query_suspended',{'month':'2026-10','city':'全省'},structured=True,source_reader=lambda day:None)
        self.assertFalse(result['available']);self.assertIn('缺少最后一个周五',result['reply'])

    @patch('app.summarize_query',side_effect=ValueError('offline'))
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_user_examples_city_progress_and_suspended(self,key,planner,summary):
        self.month['cities']=[{'city':name,'included':10,'qualified':5} for name in CITIES]
        self.insert()
        result=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'10月份各地市黑点解决情况'}]})
        self.assertEqual(result.status_code,200);self.assertEqual(len(result.json['table']['rows']),16)
        result=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'10月份合肥挂起库情况'}]})
        self.assertEqual(result.status_code,200);self.assertIn('7处',result.json['reply']);planner.assert_not_called()

    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_highest_blackspot_resolution_including_ties_and_zero(self,key):
        self.month['cities']=[{'city':name,'included':10,'qualified':4} for name in CITIES]
        self.month['cities'][0].update(included=10,qualified=9)
        self.month['cities'][1].update(included=20,qualified=18)
        self.month['cities'][2].update(included=0,qualified=0)
        self.insert()
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪个地市黑点解决率最高'}]})
        self.assertEqual(response.status_code,200);self.assertIn('并列90.00%',response.json['reply'])
        self.assertIn(CITIES[0],response.json['reply']);self.assertIn(CITIES[1],response.json['reply'])
        self.assertIn(CITIES[2],response.json['evidence']);self.assertEqual(len(response.json['table']['rows']),16)

    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_highest_needs_complete_data_and_actual_denominators(self,key):
        self.insert()
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪个地市黑点解决率最高'}]})
        self.assertEqual(response.status_code,400);self.assertIn('缺少部分地市',response.json['error'])

    def test_highest_uses_exact_ratio_not_rounded_display(self):
        from smart_query import highest_resolution
        self.month['cities']=[{'city':name,'included':100000,'qualified':50000} for name in CITIES]
        self.month['cities'][0]['qualified']=90000
        self.month['cities'][1]['qualified']=90001
        self.insert()
        result=highest_resolution(service.connect,'2026-10')
        self.assertIn(CITIES[1]+'市',result['reply']);self.assertNotIn(CITIES[0]+'市',result['reply'])

    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_structured_multistep_highest_then_compare(self,key):
        self.month['cities']=[{'city':name,'included':10,'qualified':5} for name in CITIES]
        self.month['cities'][0]['qualified']=9
        self.month['cities'][1]['qualified']=9
        self.insert()
        previous={'snapshot_version':2,'total':{'included':160,'qualified':80},'cities':[{'city':name,'included':10,'qualified':8} for name in CITIES],'suspended':{'count':0,'cities':[]}}
        self.insert('2026-09-25',weekly=True,monthly=False,week=previous)
        plan={'operation':'highest_compare','month':'2026-10','other_month':'2026-09','city':'全部地市','clarification':''}
        with patch('analysis_planner.create_plan',return_value=plan):
            r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪个地市黑点解决率最高，和9月相比如何'}]})
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.json['table']['rows']),2)
        self.assertEqual(r.json['table']['rows'][0][-1],'+10.00个百分点')
        self.assertIn('并列最高',r.json['reply'])

    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_structured_missing_month_does_not_invent(self,key):
        self.month['cities']=[{'city':name,'included':10,'qualified':5} for name in CITIES]
        self.insert()
        plan={'operation':'highest_compare','month':'2026-10','other_month':'2026-09','city':'全部地市','clarification':''}
        with patch('analysis_planner.create_plan',return_value=plan):
            r=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪个地市黑点解决率最高，和9月相比如何'}]})
        self.assertIn('对照数据不可用',r.json['reply']);self.assertNotIn('table',r.json)

    @patch('ranking_planner.requests.post',side_effect=__import__('requests').ConnectionError())
    @patch('credential_store.get_assistant_key',return_value='fake')
    def test_lowest_three_and_followup(self,key,post):
        self.month['cities']=[{'city':name,'included':10,'qualified':i+1 if i<9 else 9} for i,name in enumerate(CITIES)]
        self.insert()
        for messages in ([{'role':'user','content':'现在10月地市黑点解决率倒数前三'}],[{'role':'user','content':'现在10月地市黑点解决率倒数前三'},{'role':'assistant','content':'旧回答'}, {'role':'user','content':'10月倒数前三地市'}]):
            response=self.client.post('/api/assistant/query-chat',json={'messages':messages})
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.json['table']['rows']),3)

    def test_rank_ties_at_cutoff_and_zero_are_handled(self):
        from ranking_planner import execute
        self.month['cities']=[{'city':name,'included':10,'qualified':9} for name in CITIES]
        self.month['cities'][0].update(included=10,qualified=1)
        self.month['cities'][1].update(included=10,qualified=2)
        self.month['cities'][2].update(included=10,qualified=3)
        self.month['cities'][3].update(included=20,qualified=6)
        self.month['cities'][4].update(included=0,qualified=0)
        self.insert()
        result=execute({'month':'2026-10','direction':'asc','limit':3},service.connect)
        self.assertEqual(len(result['table']['rows']),4)
        self.assertEqual([x[0] for x in result['table']['rows']],['1','2','3','3'])
        self.assertIn('末位并列',result['reply']);self.assertIn(CITIES[4],result['evidence'])

    def test_zero_denominator_has_no_fabricated_rate(self):
        self.week['cities'][0].update(included=0,qualified=0)
        self.insert(weekly=True,monthly=False)
        result=query(service.connect,'query_city_metrics',{'month':'2026-10','city':'合肥','metric':'解决率'})
        self.assertIn('没有确认纳入',result)
        self.assertIn('分母为0',result)

    def test_new_metric_queries_and_distinct_complaint_populations(self):
        sample={'snapshot_version':2,'total':{},'cities':[{'city':'合肥','platform':15,'platform_complaints':44,'complaints':12,'stages':{stage:i for i,stage in enumerate(STAGES)}}],'suspended':{'count':0,'cities':[]}}
        self.insert(weekly=True,monthly=False,week=sample)
        base={'month':'2026-10','city':'合肥'}
        self.assertIn('汇聚黑点量为15处',query(service.connect,'query_city_metrics',dict(base,metric='汇聚黑点量')))
        both=query(service.connect,'query_city_metrics',dict(base,metric='关联投诉量'))
        self.assertIn('关联投诉44件',both);self.assertIn('关联投诉12件',both)
        stages=query(service.connect,'query_city_metrics',dict(base,metric='项目进展'),structured=True)
        self.assertEqual(stages['table']['rows'][0],['项目申请','0'])
        self.assertEqual(stages['table']['rows'][-1],['站点开通','6'])
        self.assertIn('地市处理节点',stages['reply'])

    def test_missing_new_fields_is_not_a_zero(self):
        self.insert(weekly=True,monthly=False)
        for metric in ('项目进展','汇聚黑点量','关联投诉量'):
            with self.subTest(metric=metric), self.assertRaisesRegex(ValueError,'未保存'):
                query(service.connect,'query_city_metrics',{'month':'2026-10','city':'合肥','metric':metric})

    def test_explicit_business_intents(self):
        examples={'合肥10月项目进展':'项目进展','合肥得关联投诉量':'关联投诉量','合肥汇聚黑点量':'汇聚黑点量','合肥已纳入关联投诉量':'已纳入关联投诉量','合肥汇聚黑点关联投诉量':'平台关联投诉量'}
        for question,expected in examples.items():
            with self.subTest(question=question): self.assertEqual(identify_explicit_metric(question),expected)

    @patch('app.summarize_query',side_effect=ValueError('skip external'))
    @patch('app.plan_query')
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_misclassified_project_progress_never_answers_resolution_rate(self,get_key,plan,summarize):
        sample={'snapshot_version':2,'total':{},'cities':[{'city':'合肥','included':20,'qualified':15,'stages':{stage:1 for stage in STAGES}}],'suspended':{'count':0,'cities':[]}}
        self.insert(weekly=True,monthly=False,week=sample)
        plan.return_value={'tool':'query_city_metrics','arguments':{'month':'2026-10','city':'合肥','metric':'解决率'}}
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'合肥10月项目进展'}]})
        self.assertEqual(response.status_code,200)
        self.assertIn('项目进展阶段合计7处',response.json['reply'])
        self.assertNotIn('解决率',response.json['reply'])
        self.assertEqual(len(response.json['table']['rows']),7)

    @patch('app.summarize_query')
    @patch('app.plan_query',side_effect=ValueError('无法连接 DeepSeek，请检查网络后重试。'))
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_connection_error_still_answers_unambiguous_local_query(self,get_key,plan,summarize):
        self.month['cities'][0]['platform']=24
        self.insert()
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月合肥汇聚黑点量是多少？'}]})
        self.assertEqual(response.status_code,200)
        self.assertIn('汇聚黑点量为24处',response.json['reply'])
        self.assertIn('DeepSeek',response.json['summary_notice'])
        summarize.assert_not_called()

    @patch('app.plan_query',side_effect=ValueError('无法连接 DeepSeek，请检查网络后重试。'))
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_connection_error_does_not_guess_unsupported_query(self,get_key,plan):
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'覆盖变差是什么原因？'}]})
        self.assertEqual(response.status_code,400)

    @patch('app.summarize_query')
    @patch('app.plan_query',side_effect=ValueError('DeepSeek 返回服务错误（HTTP 503），请稍后重试。'))
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_service_error_fallback_preserves_diagnostic_status(self,get_key,plan,summarize):
        self.month['cities'][0]['platform']=24
        self.insert()
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月合肥汇聚黑点量是多少？'}]})
        self.assertEqual(response.status_code,200)
        self.assertIn('HTTP 503',response.json['summary_notice'])
        self.assertIn('汇聚黑点量为24处',response.json['reply'])
        summarize.assert_not_called()

    @patch('app.plan_query',side_effect=ValueError('无法连接 DeepSeek，请检查网络后重试。'))
    @patch('credential_store.get_assistant_key',return_value='fake-secret')
    def test_local_fallback_never_guesses_missing_month_or_scope(self,get_key,plan):
        for question in ('合肥汇聚黑点量是多少','2026年10月汇聚黑点量是多少'):
            with self.subTest(question=question):
                response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':question}]})
                self.assertEqual(response.status_code,400)

    @patch('assistant_service.requests.post')
    def test_model_tool_selection_only_receives_conversation(self,post):
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'tool_calls':[{'function':{'name':'query_suspended','arguments':'{"month":"2026-10","city":"合肥"}'}}]}}]})
        result=assistant_service.plan_query('fake-secret',[{'role':'user','content':'10月合肥挂起多少'}])
        self.assertEqual(result['tool'],'query_suspended')
        payload=post.call_args.kwargs['json'];self.assertEqual({t['function']['name'] for t in payload['tools']},{'query_city_metrics','query_suspended','query_network_daily'})
        self.assertNotIn('snapshot_version',str(payload));self.assertFalse(post.call_args.kwargs['allow_redirects'])

    @patch('assistant_service.requests.post')
    def test_model_cannot_answer_known_metric_without_tool(self,post):
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'content':'解决率是 99%'}}]})
        result=assistant_service.plan_query('fake-secret',[{'role':'user','content':'10月合肥解决率是多少'}])
        self.assertNotIn('99%',result['reply'])
        self.assertIn('暂时无法确定',result['reply'])

    @patch('assistant_service.requests.post')
    def test_summary_checks_numbers_against_evidence(self,post):
        evidence={'reply':'截至2026-10-30，合肥市挂起库累计7处。'}
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'content':'截至2026年10月，合肥挂起7处。'}}]})
        self.assertIn('7处',assistant_service.summarize_query('fake-secret','多少处',evidence))
        payload=post.call_args.kwargs['json']
        self.assertIn('7处',str(payload))
        self.assertNotIn('workbook_rows',str(payload))
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'content':'合肥挂起99处。'}}]})
        with self.assertRaises(ValueError):assistant_service.summarize_query('fake-secret','多少处',evidence)


if __name__=='__main__': unittest.main()
