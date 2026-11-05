"""Isolated semantic audit: creates and finally drops its own PostgreSQL database.
Run from the repository root: PYTHONPATH=. .venv/bin/python <this file>
No production rows or application files are changed.
"""
import json
import uuid
from pathlib import Path
from datetime import date
from decimal import Decimal
import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlmodel import Session
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import app
from app.db import get_session
from app import clock

out = Path(__file__).resolve().parent
name = 'fin_logic_review_' + uuid.uuid4().hex[:12]
url = make_url(Settings().database_url)
admin = url.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)
engine = None
restore_db = 'fin_restore_probe_' + uuid.uuid4().hex[:12]
original_today = clock.today
results = {}
with psycopg.connect(admin, autocommit=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
try:
    test_url = url.set(database=name)
    cfg = Config('alembic.ini')
    cfg.set_main_option('sqlalchemy.url', test_url.render_as_string(hide_password=False))
    command.upgrade(cfg, 'head')
    engine = create_engine(test_url)
    def sessions():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = sessions
    clock.today = lambda: date(2026, 11, 20)
    with TestClient(app, client=('127.0.0.1', 52000), raise_server_exceptions=False) as client:
        h = {}
        def req(method, path, body=None, expected=200):
            r = client.request(method, path, json=body, headers=h)
            assert r.status_code == expected, (path, r.status_code, r.text)
            return r.json() if r.content else None
        def setup(label):
            h.clear()
            user = req('POST', '/users', {'name':label}, 201)
            h['X-User-Id'] = str(user['id'])
            return req('POST','/accounts', {'name':'Giro','type':'checking','opening_balance':'5000',
                'opening_balance_date':'2026-01-01'},201)
        def loan(account, **kw):
            return req('POST','/loans', {'name':'Kredit','lender_name':'Bank','loan_type':'annuity',
                'annual_interest_rate':'0','current_balance':'1000','balance_date':'2026-01-01',
                'first_due_date':'2026-01-31','installment_amount':'100','payment_account_id':account['id'], **kw},201)
        def pay(l, amount='100', day='2026-01-31'):
            return req('POST',f"/loans/{l['id']}/payments",{'amount':amount,'booking_date':day},201)
        def charge(l, amount='100', day='2026-01-10'):
            return req('POST',f"/loans/{l['id']}/charges",{'amount':amount,'booking_date':day,'charge_type':'interest'},201)
        def getloan(l):return req('GET',f"/loans/{l['id']}")
        def plan(l):return req('GET',f"/loans/{l['id']}/schedule")
        def budget(month):return req('GET',f'/budget/month?month={month}')
        def tx(a, amount, day, category=None):
            return req('POST','/transactions',{'account_id':a['id'],'amount':amount,'booking_date':day,
                'description':'Prüfbuchung','category_id':category},201)
        def income(a, day):
            cat=req('POST','/categories',{'name':'Gehalt '+day,'type':'income'},201)
            tx(a,'1000',day,cat['id'])

        def series(label):
            a=setup(label)
            cat=req('POST','/categories',{'name':'Vertrag','type':'expense'},201)
            ts=[]
            for m in (9,10,11):
                ts.append(req('POST','/transactions',{'account_id':a['id'],'amount':'-20',
                    'booking_date':f'2026-{m:02d}-02','description':'Vertrag','counterparty':'Anbieter',
                    'counterparty_iban':'DE02120300000000202051','category_id':cat['id']},201))
            return a,ts
        def refresh(kind='fixed_costs'):
            return req('POST','/suggestions/refresh?detector='+kind)
        def sug(kind='fixed_cost_new'):
            return req('GET','/suggestions?kind='+kind)[0]
        def mode(value):
            return req('PATCH',f"/users/{h['X-User-Id']}/settings",{'automation.fixed_cost':value})
        def accept(s): return req('POST',f"/suggestions/{s['id']}/accept",{})
        def fc(**kw):return req('POST','/fixed-costs',{'name':'Vertrag','amount':'20','due_day':2,**kw},201)

        import os,subprocess,tarfile
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from app.config import get_settings
        with TemporaryDirectory(prefix='fin-backup-probe-') as tmp:
            root=Path(tmp);imports=root/'imports';docs=root/'belege';docs.mkdir();imports.mkdir()
            a=setup('isolated backup docs')
            with patch.object(get_settings(),'document_dir',docs):
                r=client.post('/documents',headers=h,files={'file':('beleg.png',b'\x89PNG\r\n\x1a\nOriginal','image/png')})
                assert r.status_code==201,r.text
            original=next(docs.iterdir());original_content=original.read_bytes()
            env=dict(os.environ,DATABASE_URL=test_url.render_as_string(hide_password=False),
                IMPORT_DIR=str(imports),DOCUMENT_DIR=str(docs))
            target=root/'backup1'
            run=subprocess.run(['bash','scripts/backup.sh',str(target)],env=env,text=True,capture_output=True)
            assert run.returncode==0,run.stdout+run.stderr
            archive=next(target.glob('*.tar.gz'))
            with tarfile.open(archive) as tf:members=tf.getnames()
            results['backup_without_imports_omits_documents']={'exit':run.returncode,'archive_members':members,
                'original_document_exists':original.exists()}
            assert members==[]

            (imports/'archive').mkdir();target=root/'backup2'
            run=subprocess.run(['bash','scripts/backup.sh',str(target)],env=env,text=True,capture_output=True)
            assert run.returncode==0,run.stdout+run.stderr
            archive=next(target.glob('*.tar.gz'));dump=next(target.glob('*.dump'))
            with tarfile.open(archive) as tf:members=tf.getnames()
            assert 'documents/'+original.name in members
            restore_imports=root/'restore-imports';restore_docs=root/'restore-docs';restore_docs.mkdir()
            existing=restore_docs/original.name;existing.write_bytes(b'NEW_EXISTING_DOCUMENT_MUST_NOT_OVERWRITE')
            env.update(IMPORT_DIR=str(restore_imports),DOCUMENT_DIR=str(restore_docs))
            run=subprocess.run(['bash','scripts/restore.sh',str(dump),str(archive),'--target-db',restore_db],
                env=env,text=True,capture_output=True,input='')
            results['restore_overwrites_document_without_yes']={'exit':run.returncode,
                'restored_original':existing.read_bytes()==original_content,'used_yes_flag':False,
                'stdout':run.stdout,'stderr':run.stderr}
            assert run.returncode==0 and existing.read_bytes()==original_content

    (out/'results6.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        for probe_db in (name,restore_db):
            c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(probe_db)))
