import unittest
from html.parser import HTMLParser
from pathlib import Path

class Layout(HTMLParser):
    void={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self): super().__init__();self.stack=[];self.nodes=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);self.nodes.append((tag,attrs,[p[1].get('id') for p in self.stack]))
        if tag not in self.void:self.stack.append((tag,attrs))
    def handle_endtag(self,tag):
        if tag not in self.void:
            if not self.stack or self.stack[-1][0]!=tag: raise AssertionError('元素嵌套不匹配：'+tag)
            self.stack.pop()

class ReportLayoutTest(unittest.TestCase):
    def test_mail_settings_and_buttons_live_in_report(self):
        parser=Layout();parser.feed((Path(__file__).resolve().parents[1]/'templates'/'index.html').read_text(encoding='utf-8-sig'))
        self.assertFalse(parser.stack)
        panel=next(n for n in parser.nodes if n[1].get('id')=='mail-panel')
        self.assertIn('result',panel[2])
        for kind in ('weekly','monthly'):
            button=next(n for n in parser.nodes if n[1].get('data-send')==kind)
            self.assertEqual(button[0],'button');self.assertIn(kind+'-panel',button[2])
        ids=[node[1]['id'] for node in parser.nodes if 'id' in node[1]]
        self.assertEqual(len(ids),len(set(ids)))
        for required in ('form','history','summary','result','result-empty','weekly','monthly','mail-form','database-form','database-status'):
            self.assertIn(required,ids)
        empty=next(n for n in parser.nodes if n[1].get('id')=='result-empty')
        self.assertNotIn('hidden',empty[1])
        result=next(n for n in parser.nodes if n[1].get('id')=='result')
        self.assertIn('hidden',result[1])

    def test_charts_have_empty_states_and_load_before_main_script(self):
        text=(Path(__file__).resolve().parents[1]/'templates'/'index.html').read_text(encoding='utf-8-sig')
        parser=Layout();parser.feed(text)
        ids={node[1].get('id') for node in parser.nodes}
        for name in ('city-chart','city-chart-empty','city-chart-data','trend-chart','trend-chart-empty','trend-chart-data','trend-month','trend-city','trend-city-legend'):
            self.assertIn(name,ids)
        self.assertLess(text.index('/static/charts.js'),text.index('/static/trend.js'))
        self.assertLess(text.index('/static/trend.js'),text.index('/static/app.js'))
        self.assertLess(text.index('/static/charts.js'),text.index('/static/app.js'))

if __name__=='__main__':unittest.main()
