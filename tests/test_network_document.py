import json, sqlite3, unittest
from contextlib import contextmanager
from unittest.mock import patch
import app, network_daily, network_document as doc

class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');network_daily.schema(self.db)
        @contextmanager
        def connection():
            with self.db: yield self.db
        self.patch=patch.object(app,'connect',connection);self.patch.start();app.app.testing=True;self.client=app.app.test_client()
    def tearDown(self):self.patch.stop();self.db.close()
    def test_interleaving_and_original_preservation(self):
        source='\n'.join(['标题','一、业务','叙述','类型','指标','2026-10-21','较上月对比','5G','流量','20','2%','地市','4G用户数','5G用户数','4G MME附着用户（万户）','Volte在网用户数（万户）','5G终端用户数（万户）','5G活跃用户数（万户）','VONR活跃用户数(万户)','合肥','1','2','3','4','5','二、质量','质量叙述'])
        self.db.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','id',source,'s','pending_review'))
        result=self.client.get('/api/network/day/2026-10-21/document').json;blocks=result['blocks'];types=[b['type'] for b in blocks]
        self.assertEqual(types[:7],['text','text','text','table','table','text','text'])
        self.assertEqual(blocks[-2:], [{'type':'text','text':'投诉预警情况'},{'type':'text','text':''}])
        blocks[3]['rows'][0][2]='21';r=self.client.post('/api/network/day/2026-10-21/document',json={'blocks':blocks});self.assertEqual(r.status_code,200)
        self.assertEqual(self.db.execute('SELECT content FROM network_daily_reports').fetchone()[0],source)
        self.assertEqual(self.client.get('/api/network/day/2026-10-21/document').json['blocks'][3]['rows'][0][2],'21')
    def test_document_only_date_is_in_history(self):
        doc.save(self.db,'2026-10-20',[{'type':'text','text':'内容'}])
        self.assertIn('2026-10-20',network_daily.dates(self.db))
    def test_legacy_text_draft_is_preserved(self):
        network_daily.save(self.db,'2026-10-21','旧版编辑文字')
        data=self.client.get('/api/network/day/2026-10-21/document').json
        self.assertEqual(data['source'],'legacy');self.assertEqual(data['blocks'][0]['text'],'旧版编辑文字')
        self.assertEqual(self.db.execute('SELECT content FROM network_daily_drafts').fetchone()[0],'旧版编辑文字')
    @patch('app.send_report')
    def test_mail_contains_current_text_and_tables_safely(self,send):
        blocks=[{'type':'text','text':'文字 <unsafe>'},{'type':'table','title':'质量','headers':['地市','指标'],'rows':[['合肥','<script>']]}]
        with patch('credential_store.get_for_sender',return_value='fake'):
            r=self.client.post('/api/network/day/2026-10-21/document-email',json={'sender':'a@example.com','recipient':'b@example.com','subject':'日报','auth_code':'','blocks':blocks})
        self.assertEqual(r.status_code,200);self.assertIn('合肥',send.call_args.args[-1]);html=send.call_args.kwargs['html_body'];self.assertIn('<table',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
    def test_formatted_text_survives_save_reload_and_mail(self):
        blocks=[{'type':'text','text':'甲乙','runs':[{'text':'甲','size':20,'color':'#a12b3c','bold':True,'font':'SimSun'},{'text':'乙','italic':True,'underline':True}]}]
        r=self.client.post('/api/network/day/2026-10-21/document',json={'blocks':blocks});self.assertEqual(r.status_code,200)
        loaded=self.client.get('/api/network/day/2026-10-21/document').json['blocks'];self.assertEqual(loaded,blocks)
        plain,rich=doc.email_parts(loaded);self.assertEqual(plain,'甲乙');self.assertIn('font-size:20px',rich);self.assertIn('color:#a12b3c',rich);self.assertIn('font-family:SimSun',rich);self.assertIn('font-weight:bold',rich);self.assertIn('text-decoration:underline',rich)
    def test_rejects_unsafe_or_inconsistent_styles(self):
        for run in ({'text':'甲','color':'red; background:url(x)'},{'text':'甲','font':'Arial;display:none'},{'text':'乙','bold':True},{'text':'甲','size':999}):
            with self.subTest(run=run),self.assertRaises(ValueError):doc.validate([{'type':'text','text':'甲','runs':[run]}])

    def test_reject_malformed_table(self):
        with self.assertRaises(ValueError):doc.validate([{'type':'table','title':'x','headers':['a','b'],'rows':[['1']]}])
    def test_metric_generated_document_interleaves_quality(self):
        self.db.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',('s','2026-10-21','安徽省','h',json.dumps({'nr_upoct':'2'}),'unreviewed'))
        r=self.client.post('/api/network/day/2026-10-21/generate');blocks=r.json['blocks'];self.assertEqual(sum(b['type']=='table' for b in blocks),4)
        quality=next(i for i,b in enumerate(blocks) if b['type']=='text' and '无线网络运行质量' in b['text']);self.assertEqual(blocks[quality+1]['title'],'各地市网络质量');self.assertNotIn('【数据未接入，请补充并核对】',blocks[-1]['text'])

if __name__=='__main__':unittest.main()
