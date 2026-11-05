import unittest
from io import BytesIO
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from unittest.mock import patch
from contextlib import contextmanager
import sqlite3
import app
import network_document as doc
import network_word

class ReportWordTests(unittest.TestCase):
    def setUp(self):
        self.blocks=[{'type':'text','text':'全省无线网络运行日报（测试）'}, {'type':'text','text':'正文','runs':[{'text':'正','bold':True,'size':20,'color':'#a12b3c','font':'SimSun'},{'text':'文'}]}, {'type':'table','title':'地市数据','headers':['地市','值'],'rows':[['合肥','123']]}, {'type':'text','text':'后续内容'}]
    def test_email_title_has_default_format(self):
        _,out=doc.email_parts(self.blocks)
        self.assertIn('text-align:center;font-size:18px;font-weight:bold',out)
        self.assertIn('<strong>全省无线网络运行日报（测试）</strong>',out)
        self.assertIn('<table',out)
    def test_word_keeps_text_table_order_and_format(self):
        result=Document(network_word.export_word(self.blocks))
        items=[x.tag.split('}')[-1] for x in result.element.body if x.tag.split('}')[-1] in ('p','tbl')]
        self.assertEqual(items[:4],['p','p','p','tbl'])
        self.assertEqual(result.paragraphs[0].alignment,WD_ALIGN_PARAGRAPH.CENTER)
        self.assertTrue(result.paragraphs[0].runs[0].bold)
        self.assertEqual(result.paragraphs[0].runs[0].font.size.pt,13.5)
        run=result.paragraphs[1].runs[0];self.assertTrue(run.bold);self.assertEqual(run.font.name,'SimSun');self.assertEqual(run.font.size.pt,15);self.assertEqual(str(run.font.color.rgb),'A12B3C')
        self.assertEqual(result.tables[0].cell(1,0).text,'合肥')
        self.assertEqual(result.tables[0].cell(1,1).text,'123')
    def test_wide_table_uses_landscape(self):
        result=Document(network_word.export_word([self.blocks[0],{'type':'table','title':'宽表','headers':[str(i) for i in range(10)],'rows':[['值']*10]}]))
        self.assertEqual(result.sections[0].orientation,WD_ORIENT.LANDSCAPE)
    def test_endpoint_uses_current_request_without_saving(self):
        db=sqlite3.connect(':memory:')
        @contextmanager
        def connect():
            with db: yield db
        with patch.object(app,'connect',connect):
            app.app.testing=True;client=app.app.test_client()
            response=client.post('/api/network/day/2026-11-02/document-word',json={'blocks':self.blocks})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            result=Document(BytesIO(response.data));self.assertEqual(result.tables[0].cell(1,1).text,'123')
        db.close()
    def test_invalid_block_rejected(self):
        with self.assertRaises(ValueError):network_word.export_word([{'type':'table','headers':['a','b'],'rows':[['a']]}])

if __name__=='__main__':unittest.main()
