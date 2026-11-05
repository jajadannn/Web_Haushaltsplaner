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
    with TestClient(app, client=('127.0.0.1', 52000)) as client:
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

        a,ts=series('dry-run to auto');mode('dry_run');refresh();before=sug();mode('auto');refresh()
        results['dry_run_to_auto']={'before':before['status'],'after':sug()['status'],'fixed':req('GET','/fixed-costs')}
        assert results['dry_run_to_auto']['after']=='dry_run' and not results['dry_run_to_auto']['fixed']

        a,ts=series('stale amounts');refresh();s=sug()
        for t in ts:req('PATCH',f"/transactions/{t['id']}",{'amount':'-75'})
        accepted=accept(s)
        results['stale_evidence']={'suggestion_amount':s['payload']['amount'],'current_transaction_amounts':'-75.00',
            'accepted':accepted['status'],'fixed':req('GET',f"/fixed-costs/{accepted['result_id']}")}
        assert results['stale_evidence']['fixed']['amount']=='20.00'

        a,ts=series('duplicate manual');refresh();s=sug();fc(name='Schon manuell angelegt',match_text='Anbieter')
        accept(s)
        results['manual_duplicate']={'fixed':req('GET','/fixed-costs')}
        assert len(results['manual_duplicate']['fixed'])==2

        a=setup('price revert');f=fc()
        for m in (10,11):
            t=tx(a,'-30',f'2026-{m}-02')
            req('POST',f"/fixed-costs/{f['id']}/payments",{'transaction_id':t['id'],'due_month':f'2026-{m}-01'},201)
        refresh('fixed_cost_changes');s=sug('fixed_cost_change');accept(s)
        r=client.post(f"/suggestions/{s['id']}/revert",headers=h)
        results['amount_revert']={'status':r.status_code,'body':r.json(),'history':req('GET',f"/fixed-costs/{f['id']}/amounts")}
        assert r.status_code==409

        a=setup('transfer revert')
        req('PATCH',f"/accounts/{a['id']}",{'iban':'DE89370400440532013000'})
        b=req('POST','/accounts',{'name':'Zweitkonto','type':'checking','opening_balance':'0',
            'opening_balance_date':'2026-01-01','iban':'DE02120300000000202051'},201)
        t=req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-02',
            'description':'Transfer','counterparty_iban':b['iban']},201)
        u=tx(b,'100','2026-11-02')
        refresh('matching');s=sug('transfer_match');accept(s)
        reverted=req('POST',f"/suggestions/{s['id']}/revert")
        results['transfer_fake_revert']={'status':reverted['status'],'transaction':req('GET',f"/transactions/{t['id']}")}
        assert reverted['status']=='reverted' and results['transfer_fake_revert']['transaction']['kind']=='transfer'

        a=setup('transfer stale amount');req('PATCH',f"/accounts/{a['id']}",{'iban':'DE89370400440532013000'})
        b=req('POST','/accounts',{'name':'Zweitkonto','type':'checking','opening_balance':'0',
            'opening_balance_date':'2026-01-01','iban':'DE02120300000000202051'},201)
        t=req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-02',
            'description':'Transfer','counterparty_iban':b['iban']},201)
        u=tx(b,'100','2026-11-02');refresh('matching');s=sug('transfer_match')
        req('PATCH',f"/transactions/{u['id']}",{'amount':'200'});accept(s)
        results['unbalanced_transfer']=[req('GET',f"/transactions/{i['id']}") for i in (t,u)]
        assert all(t['kind']=='transfer' for t in results['unbalanced_transfer'])

        a=setup('fixed account ignored');b=req('POST','/accounts',{'name':'Zweitkonto','type':'checking',
            'opening_balance':'0','opening_balance_date':'2026-01-01'},201)
        f=fc(account_id=a['id'],match_text='Internet')
        req('POST','/transactions',{'account_id':b['id'],'amount':'-20','booking_date':'2026-11-02',
            'description':'Internet'},201)
        results['wrong_account_payment']=budget('2026-11-01')['items'][0]
        assert results['wrong_account_payment']['status']=='paid'

        a=setup('linked payment becomes income');f=fc();t=tx(a,'-20','2026-11-02')
        req('POST',f"/fixed-costs/{f['id']}/payments",{'transaction_id':t['id'],'due_month':'2026-11-01'},201)
        req('PATCH',f"/transactions/{t['id']}",{'amount':'20'})
        results['positive_fixed_payment']=budget('2026-11-01')
        assert results['positive_fixed_payment']['items'][0]['paid_amount']=='-20.00'

        a=setup('off still suggests');a,ts=series('off still suggests series');mode('off');refresh()
        results['off_still_suggests']={'suggestions':req('GET','/suggestions?kind=fixed_cost_new')}
        assert results['off_still_suggests']['suggestions']

    (out/'results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
