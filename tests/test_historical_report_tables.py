import unittest
from historical_report_tables import parse

class HistoricalTableTests(unittest.TestCase):
    def test_recovers_comparison_city_and_detail_from_original(self):
        text='\n'.join(['类型','指标','2026-10-21','较上月对比','5G','5G流量','20','2.3%','地市','4G用户数','5G用户数','4G MME附着用户（万户）','Volte在网用户数（万户）','5G终端用户数（万户）','5G活跃用户数（万户）','VONR活跃用户数(万户)','合肥','1','2','3','4','5','安徽省','1','2','3','4','5','二、质量','地市','小区名','CGI','规则','原因分析','处理措施','5G','HF','测试小区','460-00-1-1','规则','原因','处理','三、结束'])
        tables=parse(text);self.assertEqual([t['id'] for t in tables],['province','users','cells'])
        self.assertEqual(tables[0]['rows'][0][-1],'2.3%')
        self.assertEqual(tables[1]['rows'][0],['合肥','1','2','3','4','5'])
        self.assertEqual(tables[2]['rows'][0],['5G','HF','测试小区','460-00-1-1','规则','原因','处理'])
    def test_refuses_incomplete_rows_instead_of_shifting_values(self):
        text='\n'.join(['地市','3CC开通站点数','3CC开通小区数','5G-A套餐用户数','安庆','1','2','合肥','3','4','5'])
        self.assertEqual(parse(text),[])
    def test_valid_special_table(self):
        text='\n'.join(['地市','设备厂商','通感基站数','扇区数','安庆','华为','2/7','6/21','合肥','中兴','5','10'])
        tables=parse(text);self.assertEqual(tables[0]['id'],'sensing');self.assertEqual(tables[0]['rows'][0],['安庆','华为','2/7','6/21'])

if __name__=='__main__':unittest.main()
