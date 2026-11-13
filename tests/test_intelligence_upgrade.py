import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app as service
import intelligence_brief
import evaluation_suite
from core import CITIES,STAGES

class IntelligenceUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'test.sqlite3';service.app.testing=True
        self.client=service.app.test_client()
        for period,base in [('2026-08-28',5),('2026-09-25',4),('2026-10-30',3)]:
            cities=[{'city':city,'included':10,'qualified':base if i==0 else 8,'stages':{stage:(2 if j==0 and i==0 else 0) for j,stage in enumerate(STAGES)}} for i,city in enumerate(CITIES)]
            snap={'snapshot_version':2,'cities':cities,'total':{'included':160,'qualified':100},'suspended':{'count':0,'cities':[]}}
            with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',(period,json.dumps(snap,ensure_ascii=False),'{}','周报',''))
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing;self.tmp.cleanup()
    def test_brief_uses_real_dates_and_due_uncompleted_only(self):
        self.client.post('/api/city-followups',json={'month':'2026-10','city':CITIES[0],'issue':'测试跟进','status':'推进中','next_date':'2026-11-02'})
        def suspended(month):
            return {'period':month+'-25','kind':'weekly','city_note':'','cities':[{'name':c,'value':3 if month=='2026-10' and i==0 else 1} for i,c in enumerate(CITIES)]}
        with patch('network_query.query',return_value={'available':False}):
            result=intelligence_brief.build(service.connect,'2026-10',suspension_reader=suspended,today=date(2026,11,10))
        kinds={r['kind']:r for r in result['observations']}
        self.assertEqual(kinds['resolution']['period'],'2026-10-30')
        self.assertEqual(kinds['decline']['items'][0]['city'],CITIES[0])
        self.assertEqual(kinds['suspension']['items'][0]['change'],2)
        self.assertEqual(result['due'][0]['issue'],'测试跟进')
    def test_knowledge_remains_scoped_to_field_and_local(self):
        result=self.client.get('/api/suspension/knowledge').json
        self.assertIn('涉及7+9',result['labels']['suspension'])
        self.assertEqual(self.client.post('/api/suspension/knowledge',json={'kind':'issue','label':'涉及玻璃','advice':'评估室分方案'}).status_code,200)
        self.assertEqual(self.client.post('/api/suspension/knowledge',json={'kind':'issue','label':'不存在','advice':'建议'}).status_code,400)
        import suspension_knowledge
        matches=suspension_knowledge.match(service.connect,{'reasons':[{'reason':'涉及玻璃'}],'issues':[]})
        self.assertEqual(matches,[])
        matches=suspension_knowledge.match(service.connect,{'reasons':[],'issues':[{'reason':'涉及玻璃'}]})
        self.assertEqual(matches[0]['advice'],'评估室分方案')
    def test_offline_evaluation_and_user_case(self):
        result=evaluation_suite.run(service.connect)
        self.assertEqual(result['failed'],0,str([x for x in result['items'] if not x['passed']]))
        r=self.client.post('/api/assistant/evaluation',json={'category':'其他','question':'你好','expected_route':'general'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(evaluation_suite.run(service.connect)['custom_count'],1)
    def test_evaluation_compares_successive_explicit_runs(self):
        first=self.client.post('/api/assistant/evaluation/run').json
        self.assertFalse(first['has_previous'])
        original=evaluation_suite.intent_router.route
        def changed(messages):
            if messages[0]['content']==evaluation_suite.BUILTIN[0][1]:return 'general',None
            return original(messages)
        with patch.object(evaluation_suite.intent_router,'route',side_effect=changed):
            second=self.client.post('/api/assistant/evaluation/run').json
        self.assertTrue(second['has_previous'])
        self.assertEqual(second['comparison']['newly_failed'],1)
        third=self.client.post('/api/assistant/evaluation/run').json
        self.assertEqual(third['comparison']['newly_passed'],1)
    def test_progress_summary_uses_same_matter_history(self):
        payload={'month':'2026-10','city':CITIES[0],'issue':'测试事项','status':'推进中','action':'推动协调'}
        created=self.client.post('/api/city-followups',json=payload).json
        payload.update(id=created['id'],action='形成方案')
        self.client.post('/api/city-followups',json=payload)
        import city_followups
        record=city_followups.list_records(service.connect)[0]
        self.assertEqual([x['action'] for x in record['progress_summary']],['形成方案','推动协调'])
        payload.update(issue='新事项',action='启动新事项')
        self.client.post('/api/city-followups',json=payload)
        record=city_followups.list_records(service.connect)[0]
        self.assertEqual([x['action'] for x in record['progress_summary']],['启动新事项'])
    def test_multiturn_ranking_then_stage_and_prepare(self):
        def ask(texts,context=None):
            messages=[]
            for text in texts:
                if messages:messages.append({'role':'assistant','content':'上一轮已执行统计查询，具体结果不随历史记录再次发送。'})
                messages.append({'role':'user','content':text})
            return self.client.post('/api/assistant/query-chat',json={'messages':messages,'query_context':context})
        with patch('app.send_report') as send:
            first=ask(['2026年10月哪些地市黑点解决情况需要关注'])
            self.assertEqual(first.status_code,200);self.assertEqual(first.json['table']['rows'][0][1],CITIES[0])
            stage=ask(['2026年10月哪些地市黑点解决情况需要关注','第一个地市主要卡在哪个环节'],first.json['query_context'])
            self.assertEqual(stage.status_code,200);self.assertIn(CITIES[0],stage.json['reply']);self.assertIn('项目阶段',stage.json['table']['headers'])
            mismatch=ask(['2026年10月哪些地市黑点解决情况需要关注','第一个地市合肥主要卡在哪个环节'],first.json['query_context'])
            self.assertIn('不一致',mismatch.json['reply'])
            action=ask(['2026年10月哪些地市黑点解决情况需要关注','第一个地市主要卡在哪个环节','把它加入推进跟踪，并准备一封提醒邮件'],stage.json['query_context'])
            self.assertEqual(action.status_code,200);self.assertEqual(action.json['action']['city'],CITIES[0]);send.assert_not_called()
    def test_ambiguous_tie_never_guesses_city(self):
        with service.connect() as c:
            row=c.execute('SELECT data FROM reports WHERE period=?',('2026-10-30',)).fetchone();snapshot=json.loads(row[0]);snapshot['cities'][1]['qualified']=3
            c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(snapshot,ensure_ascii=False),'2026-10-30'))
        first=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪些地市黑点解决情况需要关注'}]})
        response=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'2026年10月哪些地市黑点解决情况需要关注'},{'role':'assistant','content':'上一轮已执行统计查询'},{'role':'user','content':'第一个地市主要卡在哪个环节'}],'query_context':first.json['query_context']})
        self.assertIn('并列',response.json['reply']);self.assertNotIn('action',response.json)

    def test_changed_ranking_or_missing_context_requires_new_query(self):
        q='2026年10月哪些地市黑点解决情况需要关注'
        first=self.client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':q}]})
        messages=[{'role':'user','content':q},{'role':'assistant','content':'已查询'},{'role':'user','content':'第一个地市主要卡在哪个环节'}]
        missing=self.client.post('/api/assistant/query-chat',json={'messages':messages})
        self.assertIn('重新查询',missing.json['reply'])
        with service.connect() as c:
            snapshot=json.loads(c.execute('SELECT data FROM reports WHERE period=?',('2026-10-30',)).fetchone()[0]);snapshot['cities'][0]['qualified']=7
            c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(snapshot,ensure_ascii=False),'2026-10-30'))
        changed=self.client.post('/api/assistant/query-chat',json={'messages':messages,'query_context':first.json['query_context']})
        self.assertIn('数据已发生变化',changed.json['reply']);self.assertNotIn('action',changed.json)

