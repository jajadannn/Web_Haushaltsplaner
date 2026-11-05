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
        from app.models import User, Document, AiJob, Suggestion
        from app.services import assistant, ai_gateway, documents, ai_jobs, settings
        from app.config import get_settings
        from sqlmodel import select

        a=setup('income same category')
        cat=req('POST','/categories',{'name':'Lohn','type':'income'},201)
        for income_name,text,amount in [('Job A','Arbeitgeber A','2000'),('Job B','Arbeitgeber B','500')]:
            req('POST','/expected-incomes',{'name':income_name,'amount':amount,'due_day':28,'account_id':a['id'],
                'category_id':cat['id'],'match_text':text},201)
        req('POST','/transactions',{'account_id':a['id'],'amount':'2000','booking_date':'2026-11-19',
            'category_id':cat['id'],'description':'Gehalt','counterparty':'Arbeitgeber A'},201)
        result=req('GET',f"/accounts/{a['id']}/forecast?until=2026-11-30")
        results['one_income_suppresses_two']=result
        assert result['events']==[]

        a=setup('future transaction disappears');f=fc(account_id=a['id'],match_text='Internet',due_day=25)
        req('POST','/transactions',{'account_id':a['id'],'amount':'-20','booking_date':'2026-11-25',
            'description':'Internet'},201)
        result=req('GET',f"/accounts/{a['id']}/forecast?until=2026-11-30")
        results['future_booked_missing']=result
        assert result['events']==[] and result['end_balance']=='5000.00'

        a=setup('split answers')
        cat=req('POST','/categories',{'name':'Internet','type':'expense'},201)
        other=req('POST','/categories',{'name':'Telefon','type':'expense'},201)
        req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-02',
            'description':'Sammelrechnung','splits':[{'amount':'-30','category_id':cat['id']},
                {'amount':'-70','category_id':other['id']}]},201)
        with Session(engine) as db:
            u=db.get(User,int(h['X-User-Id']))
            params={'date_from':'2026-11-01','date_to':'2026-11-20','kategorie_id':cat['id']}
            results['assistant_split_sum']=assistant._execute(db,u,'transactions_search',params)[0]
            results['assistant_split_groups']=assistant._execute(db,u,'sum_by',params)[0]
        assert results['assistant_split_sum']['sum']==Decimal('-100')
        assert results['assistant_split_groups']['groups'][0]['name']=='ohne Kategorie'

        a=setup('parse fallback')
        with patch.object(ai_gateway,'enabled',return_value=False):
            results['parse_day']=req('POST','/entries/parse',{'text':'Vorgestern 18,50 Euro Mittagessen'})
            results['parse_amount']=req('POST','/entries/parse',{'text':'Heute 1.234,56 Euro Miete'})
        assert results['parse_day']['booking_date']=='2026-11-19'
        assert results['parse_amount']['amount']=='-1.23'

        req('PATCH',f"/users/{h['X-User-Id']}/settings",{'ai.enabled':False})
        answer={'betrag':'18.50','richtung':'ausgabe','datum':None,'datum_relativ':'heute',
            'kategorie_id':None,'konto_id':None,'beschreibung':'Essen'}
        with patch.object(ai_gateway,'enabled',return_value=True),patch.object(ai_gateway,'ask',return_value=answer) as mocked:
            parsed=req('POST','/entries/parse',{'text':'Heute 18,50 Euro Essen'})
            results['disabled_ai_called']={'calls':mocked.call_count,'result':parsed}
        assert results['disabled_ai_called']['calls']==1

        a=setup('foreign currency receipt');t=tx(a,'-100','2026-11-02')
        answer={'art':'beleg','haendler':'Shop','datum':'2026-11-02','betrag':'100','waehrung':'USD',
            'positionen':[],'vertrag':None,'fundstellen':[]}
        with Session(engine) as db:
            doc=Document(user_id=int(h['X-User-Id']),kind='receipt',original_filename='usd.pdf',stored_path='unused.pdf',
                sha256='a'*64,mime='application/pdf',size=1)
            db.add(doc);db.flush()
            job=AiJob(user_id=doc.user_id,kind=documents.EXTRACT,ref_type='document',ref_id=doc.id)
            db.add(job);db.flush();documents._finish(db,job,answer);db.commit()
        matches=req('GET','/suggestions?kind=receipt_match')
        results['foreign_currency_match']=matches
        assert len(matches)==1

        a=setup('amount patch ignored');f=fc()
        req('POST',f"/fixed-costs/{f['id']}/amounts",{'amount':'30','valid_from':'2026-10-01'},201)
        changed=req('PATCH',f"/fixed-costs/{f['id']}",{'amount':'40'})
        result=budget('2026-12-01')
        results['fixed_patch_ignored']={'edited':changed,'budget':result}
        assert changed['amount']=='40.00' and result['items'][0]['amount']=='30.00'

        a=setup('two refunds one purchase');cat=req('POST','/categories',{'name':'Kleidung','type':'expense'},201)
        p=req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-11-01',
            'description':'Einkauf','counterparty':'Shop','category_id':cat['id']},201)
        for day in (2,3):
            req('POST','/transactions',{'account_id':a['id'],'amount':'100','booking_date':f'2026-11-0{day}',
                'description':'Gutschrift','counterparty':'Shop'},201)
        refresh('matching');matches=req('GET','/suggestions?kind=refund_match')
        for s in matches:accept(s)
        results['over_refund']={'matches':matches,'accepted':req('GET','/suggestions?kind=refund_match')}
        assert len(matches)==2 and len({s['payload']['original_id'] for s in matches})==1

        a,ts=series('AI negative obligation');refresh();s=sug()
        with Session(engine) as db:
            obj=db.get(Suggestion,s['id']);obj.payload={**obj.payload,'ai':{'ist_verpflichtung':False}}
            db.commit()
        mode('auto');refresh()
        results['negative_ai_auto']=sug()
        assert results['negative_ai_auto']['status']=='auto_applied'

    (out/'results2.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str))
    print(json.dumps({k:'reproduced' for k in results},indent=2))
finally:
    clock.today=original_today
    app.dependency_overrides.clear()
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
