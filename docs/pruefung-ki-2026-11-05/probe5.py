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

        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import threading
        from app.models import User, Suggestion, MappingRule
        from app.services import suggestions as service
        from app.config import get_settings
        from sqlmodel import select

        a,ts=series('rejected fingerprint changes');refresh();s=sug();req('POST',f"/suggestions/{s['id']}/reject")
        for m in (9,10,11):
            req('POST','/transactions',{'account_id':a['id'],'amount':'-70','booking_date':f'2026-{m:02d}-05',
                'description':'Zweiter Vertrag','counterparty':'Anbieter','counterparty_iban':'DE02120300000000202051',
                'category_id':ts[0]['category_id']},201)
        refresh();found=req('GET','/suggestions?kind=fixed_cost_new')
        results['rejected_reappears_after_second_contract']={'before':s,'after':found}
        assert any(x['status']=='open' and Decimal(x['payload']['amount'])==20 for x in found)

        a,ts=series('automation name collision');fc(name='Anbieter',active=False)
        mode('auto');r=client.post('/suggestions/refresh?detector=fixed_costs',headers=h)
        results['auto_collision_breaks_savepoint']={'status':r.status_code,'body':r.text}
        assert r.status_code==500

        a,ts=series('rule manual field lost');refresh('rules');s=sug('rule');accepted=accept(s)
        req('PATCH',f"/mapping-rules/{accepted['result_id']}",{'case_sensitive':True})
        reverted=req('POST',f"/suggestions/{s['id']}/revert")
        results['rule_revert_loses_manual_case']={'status':reverted['status'],'rules':req('GET','/mapping-rules')}
        assert not results['rule_revert_loses_manual_case']['rules']

        a,ts=series('concurrent manual automatic rule')
        for m in (7,8):
            req('POST','/transactions',{'account_id':a['id'],'amount':'-20','booking_date':f'2026-{m:02d}-02',
                'description':'Vertrag','counterparty':'Anbieter','category_id':ts[0]['category_id']},201)
        refresh('rules');s=sug('rule');uid=int(h['X-User-Id'])
        req('PATCH',f'/users/{uid}/settings',{'automation.rules':'auto'})
        selected=threading.Event();release=threading.Event();outcomes=[]
        handler=service.HANDLERS['rule'];original_clear=handler.is_clear
        def delayed_clear(suggestion):
            selected.set()
            assert release.wait(15),'manual accept did not complete'
            return original_clear(suggestion)
        def run_auto():
            try:
                with Session(engine) as db:
                    service._automate(db,db.get(User,uid),'rule');db.commit()
                outcomes.append('ok')
            except Exception as exc:outcomes.append(type(exc).__name__+': '+str(exc))
        handler.is_clear=delayed_clear
        worker=threading.Thread(target=run_auto)
        try:
            worker.start();assert selected.wait(10)
            manual=accept(s)
        finally:
            release.set();worker.join(15);handler.is_clear=original_clear
        assert not worker.is_alive()
        rules=req('GET','/mapping-rules')
        results['auto_manual_duplicate_rules']={'outcomes':outcomes,'manual_status':manual['status'],'rules':rules,
            'suggestion':req('GET','/suggestions?kind=rule')}
        assert outcomes==['ok'] and len(rules)==2

        a=setup('malformed imports')
        csv=b'Datum;Betrag;Verwendungszweck\n02.11.2026;-20,00;Test\n'
        cases={}
        for label,body in [('not_csv',b'Keine CSV Tabelle'),('empty_header',b'1;2;3\n4;5;6\n')]:
            r=client.post('/import-profiles/draft',files={'file':('a.csv',body,'text/csv')},headers=h)
            cases[label]={'status':r.status_code,'body':r.text}
        for label,options in [('json_list','[]'),('json_null','null'),('column_map_null','{"column_map":null}')]:
            r=client.post('/import-profiles/preview',files={'file':('a.csv',csv,'text/csv')},
                data={'settings':options},headers=h)
            cases[label]={'status':r.status_code,'body':r.text}
        results['import_errors_500']=cases
        assert cases['not_csv']['status']==500 and cases['json_list']['status']==500

        a=setup('AI draft raw examples absent')
        from app.services import ai_gateway
        captured={}
        def fake_ask(task,data,schema,**kw):
            captured.update(data)
            return {'zuordnung':[]}
        with patch.object(ai_gateway,'enabled',return_value=True),patch.object(ai_gateway,'ask',side_effect=fake_ask):
            r=client.post('/import-profiles/draft?ai=true',files={'file':('x.csv',
                b'Tag;Wert;Partner;Notiz\n02.11.2026;-20,00;Laden;Einkauf\n','text/csv')},headers=h)
            assert r.status_code==200
        results['ai_draft_no_samples']=captured
        assert captured['beispielzeilen']==[]

    (out/'results5.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
