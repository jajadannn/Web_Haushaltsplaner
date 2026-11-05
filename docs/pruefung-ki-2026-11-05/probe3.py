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

        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        from app.models import User, AiJob, Document, Suggestion
        from app.services import ai_jobs, ai_gateway, merchants, documents
        from app.config import get_settings
        from sqlmodel import select

        a=setup('contract same reference alias')
        m=req('POST','/merchants',{'name':'Mobilfunk'},201)
        req('POST',f"/merchants/{m['id']}/aliases",{'match_type':'iban','value':'DE02120300000000202051'},201)
        c=req('POST',f"/merchants/{m['id']}/contracts",{'label':'Ein Vertrag','reference':'ABCD'},201)
        req('POST',f"/merchants/{m['id']}/aliases",{'match_type':'reference','value':'EFGH','contract_id':c['id']},201)
        with Session(engine) as db:
            resolver=merchants.Resolver(db,int(h['X-User-Id']))
            first=resolver.resolve('Mobilfunk','DE02120300000000202051','Referenz ABCD')
            second=resolver.resolve('Mobilfunk','DE02120300000000202051','Referenz EFGH')
            results['iban_hides_contract_alias']={'first_contract':first.contract.id,'second_contract':second.contract}
        assert second.contract is None

        a=setup('reference substring')
        m=req('POST','/merchants',{'name':'Mobilfunk'},201)
        c=req('POST',f"/merchants/{m['id']}/contracts",{'label':'Erster','reference':'1234'},201)
        d=req('POST',f"/merchants/{m['id']}/contracts",{'label':'Zweiter','reference':'12345'},201)
        with Session(engine) as db:
            resolved=merchants.Resolver(db,int(h['X-User-Id'])).resolve('Mobilfunk',None,'Vertrag 12345')
            results['reference_prefix_wrong_contract']={'wanted':d['id'],'actual':resolved.contract.id}
            assert resolved.contract.id==c['id']

        a=setup('questions starvation')
        for n in range(4):
            m=req('POST','/merchants',{'name':f'Anbieter {n}'},201)
            req('POST',f"/merchants/{m['id']}/aliases",{'match_type':'name','value':f'Anbieter {n}'},201)
            for day,ref in [(1,'ABCD'),(2,'EFGH'),(3,'ABCD')]:
                req('POST','/transactions',{'account_id':a['id'],'amount':'-20','booking_date':f'2026-11-0{day}',
                    'description':f'Vertrag {ref}','counterparty':f'Anbieter {n}'},201)
        refresh('questions');before=req('GET','/suggestions?kind=question')
        for s in before:req('POST',f"/suggestions/{s['id']}/reject")
        refresh('questions');after=req('GET','/suggestions?kind=question')
        results['questions_starved']={'before':len(before),'after':[(s['payload']['merchant'],s['status']) for s in after]}
        assert len(after)==3 and all(s['status']=='rejected' for s in after)

        a=setup('doc failed remains pending')
        answer={'art':'beleg','haendler':None,'datum':None,'betrag':None,'waehrung':'EUR',
            'positionen':[],'vertrag':None,'fundstellen':[]}
        with TemporaryDirectory(prefix='fin-doc-probe-') as tmp, patch.object(get_settings(),'document_dir',Path(tmp)):
            r=client.post('/documents',files={'file':('test.png',b'\x89PNG\r\n\x1a\n','image/png')},headers=h)
            assert r.status_code==201,r.text
            document_id=r.json()['id']
            with Session(engine) as db,patch.object(ai_gateway,'ask_vision',side_effect=ai_gateway.AiInvalidAnswer('probe')):
                for _ in range(3):ai_jobs.run_one(db)
                job=db.exec(select(AiJob).where(AiJob.ref_id==document_id)).one()
                results['failed_document_pending']={'job':job.status,'document':req('GET',f'/documents/{document_id}')}
                assert job.status=='failed' and results['failed_document_pending']['document']['status']=='pending'
            with Session(engine) as db:
                job=db.exec(select(AiJob).where(AiJob.ref_id==document_id)).one();job.status='queued';db.commit()
            req('PATCH',f"/users/{h['X-User-Id']}/settings",{'ai.enabled':False})
            with Session(engine) as db,patch.object(ai_gateway,'ask_vision',return_value=answer) as call:
                ai_jobs.run_one(db)
                results['disabled_queued_job_runs']={'calls':call.call_count,'document':req('GET',f'/documents/{document_id}')}
                assert call.call_count==1

        a=setup('price change nonconsecutive');f=fc()
        for m in (8,11):
            t=tx(a,'-30',f'2026-{m:02d}-02')
            req('POST',f"/fixed-costs/{f['id']}/payments",{'transaction_id':t['id'],'due_month':f'2026-{m:02d}-01'},201)
        req('PATCH',f"/users/{h['X-User-Id']}/settings",{'automation.fixed_cost_change':'auto'})
        refresh('fixed_cost_changes')
        results['nonconsecutive_price_auto']=sug('fixed_cost_change')
        assert results['nonconsecutive_price_auto']['status']=='auto_applied'

        a,ts=series('metrics revert fraction');refresh();s=sug();accept(s)
        req('POST',f"/suggestions/{s['id']}/revert")
        results['all_reverted_rate']=req('GET','/suggestions/metrics?kind=fixed_cost_new')
        assert results['all_reverted_rate']['items'][0]['revert_rate'] is None

    (out/'results3.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
