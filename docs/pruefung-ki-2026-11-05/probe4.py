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

        from app.models import Transaction
        a=setup('split template already suggested category')
        cats=[req('POST','/categories',{'name':n,'type':'expense'},201) for n in ['Internet','Telefon']]
        for m in (9,10):
            req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':f'2026-{m:02d}-02',
                'description':'Sammelvertrag','counterparty':'Provider',
                'splits':[{'amount':'-30','category_id':cats[0]['id']},{'amount':'-70','category_id':cats[1]['id']}]},201)
        t=req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-02',
            'description':'Sammelvertrag','counterparty':'Provider'},201)
        with Session(engine) as db:
            obj=db.get(Transaction,t['id']);obj.category_id=cats[0]['id'];obj.category_source='ai';obj.review_status='auto_categorized';db.commit()
        refresh('matching');s=sug('split_template')
        r=client.post(f"/suggestions/{s['id']}/accept",json={},headers=h)
        results['split_categorized_rejected']={'status':r.status_code,'error':r.json()}
        assert r.status_code==422 and r.json()['error']['code']=='split_on_line_level'

        a=setup('two fixed splits same payment')
        cats=[req('POST','/categories',{'name':n,'type':'expense'},201) for n in ['Internet','Telefon']]
        for m in (9,10,11):
            req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':f'2026-{m:02d}-02',
                'description':'Sammelvertrag','counterparty':'Provider',
                'splits':[{'amount':'-30','category_id':cats[0]['id']},{'amount':'-70','category_id':cats[1]['id']}]},201)
        refresh();ss=req('GET','/suggestions?kind=fixed_cost_new');assert len(ss)==2
        req('POST',f"/suggestions/{ss[0]['id']}/accept",{'name':'Internet'})
        r=client.post(f"/suggestions/{ss[1]['id']}/accept",json={'name':'Telefon'},headers=h)
        results['second_split_fixed_rejected']={'status':r.status_code,'body':r.json(),'proposals':ss}
        assert r.status_code==409

        a=setup('income update range')
        i=req('POST','/expected-incomes',{'name':'Gehalt','amount':'1500','due_day':28,'amount_min':'1000','amount_max':'2000',
            'account_id':a['id']},201)
        changed=req('PATCH',f"/expected-incomes/{i['id']}",{'amount_min':'3000'})
        results['income_inverted_range']={'changed':changed,'forecast':req('GET',f"/accounts/{a['id']}/forecast?until=2026-11-30")}
        assert changed['amount_min']=='3000.00' and changed['amount_max']=='2000.00'

        a,ts=series('invalid override server error');refresh();s=sug()
        r=client.post(f"/suggestions/{s['id']}/accept",json={'amount':'0'},headers=h)
        results['invalid_override_500']={'status':r.status_code,'body':r.text}
        assert r.status_code==500

        a=setup('refund overrides manual decision')
        cat=req('POST','/categories',{'name':'Kleidung','type':'expense'},201)
        wage=req('POST','/categories',{'name':'Gehalt','type':'income'},201)
        req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-01',
            'description':'Einkauf','counterparty':'Shop','category_id':cat['id']},201)
        t=req('POST','/transactions',{'account_id':a['id'],'amount':'100','booking_date':'2026-11-02',
            'description':'Gutschrift','counterparty':'Shop'},201)
        refresh('matching');s=sug('refund_match')
        manual=req('PATCH',f"/transactions/{t['id']}",{'category_id':wage['id']})
        accept(s);after=req('GET',f"/transactions/{t['id']}")
        results['refund_overwrites_manual']={'before':manual,'after':after}
        assert manual['review_status']=='confirmed' and after['category_id']==cat['id']

    (out/'results4.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
