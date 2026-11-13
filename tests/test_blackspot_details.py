import io
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime
from openpyxl import Workbook
import pytest
from unittest.mock import patch
import app
import blackspot_details as details


def workbook(name='示例区域'):
    wb=Workbook();ws=wb.active;ws.title='汇聚黑点-汇总'
    ws.append(['是否已生成黑点编号','地市','黑点名称','黑点类型','入库时间','当前节点名称-2','联系人','工单Id'])
    ws.append(['是','合肥',name,'覆盖',datetime(2026,10,29,12,30),'地市处理','不应保存','secret-id'])
    ws.append(['是','安庆','旧区域','容量',datetime(2026,8,1),'归档','不应保存','secret-id'])
    ws.append(['否','池州','不纳入','覆盖',datetime(2026,10,30),'挂起','不应保存','secret-id'])
    stream=io.BytesIO();wb.save(stream);stream.seek(0);return stream


def test_extracts_only_authorized_fields():
    rows=details.extract(workbook())
    assert len(rows)==2
    assert rows[0]=={'city':'合肥','name':'示例区域','kind':'覆盖','entered':'2026-10-29 12:30','status':'地市处理'}
    assert 'secret-id' not in str(rows) and '不应保存' not in str(rows)


def test_date_pagination_and_missing_are_not_fabricated():
    c=sqlite3.connect(':memory:');details.save(c,'2026-10-30',details.extract(workbook()))
    recent=details.read(c,'2026-10-30','30')
    assert recent['start']=='2026-10-01' and recent['total']==1 and recent['items'][0]['city']=='合肥'
    assert details.read(c,'2026-10-30','all')['total']==2
    assert details.read(c,'2026-09-25')['available'] is False
    assert details.read(c,'2026-10-30','all',5)['items']==[]
    with pytest.raises(ValueError):details.read(c,'2026-10-30','all',-1)


def test_no_silent_overwrite_and_revision_guard():
    c=sqlite3.connect(':memory:');rows=details.extract(workbook());details.save(c,'2026-10-30',rows)
    changed=[dict(rows[0],name='更新区域')]
    with pytest.raises(details.Conflict) as exc:details.save(c,'2026-10-30',changed)
    assert details.read(c,'2026-10-30','all')['total']==2
    with pytest.raises(details.Conflict):details.save(c,'2026-10-30',changed,'obsolete')
    details.save(c,'2026-10-30',changed,exc.value.revision)
    assert details.read(c,'2026-10-30','all')['total']==1
    c.execute('UPDATE blackspot_detail_snapshots SET stale=1 WHERE period=?',('2026-10-30',))
    assert details.read(c,'2026-10-30')['available'] is False
    details.save(c,'2026-10-30',changed)
    assert details.read(c,'2026-10-30')['available'] is True


def test_filename_dates():
    assert details.filename_date('2026黑点工单进展详情-2026-1030.xlsx')=='2026-10-30'
    with pytest.raises(ValueError):details.filename_date('工单.xlsx')
    with pytest.raises(ValueError):details.filename_date('2026-1030-2026-1023.xlsx')


def test_report_generation_populates_details_and_conflicts_become_stale():
    c=sqlite3.connect(':memory:')
    c.execute('CREATE TABLE reports (period TEXT PRIMARY KEY,data TEXT,notes TEXT,weekly TEXT,monthly TEXT,monthly_data TEXT,weekly_generated_at TEXT,weekly_updated_at TEXT,monthly_generated_at TEXT,monthly_updated_at TEXT)')
    @contextmanager
    def connect():
        with c:yield c
    fake={'total':{'included':2,'qualified':1}}
    client=app.app.test_client()
    def generate(name,revision=''):
        return client.post('/api/generate',base_url='http://localhost:5088',headers={'Origin':'http://localhost:5088'},data={
            'period':'2026-10-30','kind':'weekly','overwrite_revision':revision,'current':(workbook(name),'2026黑点-2026-1030.xlsx')})
    with patch.object(app,'connect',connect),patch.object(app,'analyze',return_value=fake),patch.object(app,'compact_snapshot',side_effect=lambda x:x),patch.object(app,'reports',return_value=('周报',None)):
        assert generate('示例区域').status_code==200
        assert details.read(c,'2026-10-30','all')['total']==2
        revision=hashlib.sha256('周报'.encode()).hexdigest()
        response=generate('不同区域',revision)
        assert response.status_code==200
        assert any('版本不同' in warning for warning in response.get_json()['warnings'])
        assert details.read(c,'2026-10-30','all')['available'] is False
    c.close()


def test_manual_import_requires_matching_selected_snapshot_and_counts():
    c=sqlite3.connect(':memory:')
    @contextmanager
    def connect():
        with c:yield c
    cities=[{'name':name,'included':2 if i==0 else 0} for i,name in enumerate(details.CITIES)]
    selected={'source_info':{'period':'2026-10-30'},'cities':cities}
    client=app.app.test_client()
    def upload():
        return client.post('/api/dashboard/blackspot-details',base_url='http://localhost:5088',headers={'Origin':'http://localhost:5088'},data={'period':'2026-10-30','file':(workbook(),'工单-2026-1030.xlsx')})
    with patch.object(app,'connect',connect),patch.object(app.dashboard_data,'monthly',return_value=selected):
        selected['source_info']['period']='2026-10-23'
        assert upload().status_code==400
        selected['source_info']['period']='2026-10-30'
        cities[0]['included']=3
        assert upload().status_code==400
        cities[0]['included']=2
        assert upload().status_code==200
        assert details.read(c,'2026-10-30','all')['total']==2
    c.close()
