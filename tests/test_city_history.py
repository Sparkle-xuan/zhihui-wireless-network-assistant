import json
import tempfile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app

class CityHistoryTests(unittest.TestCase):
    def test_month_filter_weekly_precedence_and_no_detail_leakage(self):
        old_db=app.DB;old_testing=app.app.testing;app.app.testing=True
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            app.DB=Path(tmp)/'history.sqlite3'
            try:
                weekly={'cities':[{'city':'安庆','included':10,'qualified':7,'address':'private-detail'},{'city':'未知','included':1,'qualified':1}]}
                monthly={'cities':[{'city':'安庆','included':15,'qualified':12}]}
                with app.connect() as c:
                    c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',('2026-10-23',json.dumps(weekly),'{}','weekly','monthly',json.dumps(monthly)))
                    c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',('2026-10-30',json.dumps(weekly),'{}','','monthly',json.dumps(monthly)))
                    c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',('2026-11-06',json.dumps(weekly),'{}','weekly','',None))
                client=app.app.test_client();response=client.get('/api/history/cities?month=2026-10')
                self.assertEqual(response.status_code,200)
                self.assertEqual([p['period'] for p in response.json['points']],['2026-10-23','2026-10-30'])
                self.assertEqual(response.json['points'][0]['cities'],[{'city':'安庆','included':10,'qualified':7}])
                self.assertEqual(response.json['points'][1]['cities'],[{'city':'安庆','included':15,'qualified':12}])
                self.assertNotIn('private-detail',response.get_data(as_text=True))
                self.assertEqual(client.get('/api/history/cities?month=2026-13').status_code,400)
                self.assertEqual(client.get('/api/history/cities?month=2026-09').json['points'],[])
            finally: app.DB=old_db;app.app.testing=old_testing

if __name__=='__main__':unittest.main()
