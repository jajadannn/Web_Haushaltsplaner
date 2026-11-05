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
    clock.today = lambda: date(2026, 11, 4)
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

        a=setup('Storno nach Ratenpause');l=loan(a);p=pay(l)
        req('POST',f"/loans/{l['id']}/schedule/2/skip")
        before=plan(l)
        req('DELETE',f"/loans/{l['id']}/payments/{p['id']}",expected=204)
        after=plan(l)
        results['cancel_after_skip']={'before':before[:3],'after':after[:3],'loan':getloan(l)}
        assert after[0]['seq']==2 and not any(e['seq']==1 for e in after)

        a=setup('Belastung nach Tilgung löschen');l=loan(a,loan_type='private',installment_amount=None)
        ch=charge(l);pay(l,'1100');before=getloan(l)
        req('DELETE',f"/loans/{l['id']}/charges/{ch['id']}",expected=204)
        after=getloan(l)
        results['delete_charge_after_payoff']={'before':before,'after':after}
        assert after['remaining_debt']=='-100.00'

        a=setup('Historischer Kreditbericht');l=loan(a);pay(l,'100','2026-02-28')
        result=req('GET','/reports/loans?until=2026-01-31&months=1')
        results['historical_loan_report']=result
        assert result['loans'][0]['remaining_debt']=='900.00'
        assert result['loans'][0]['remaining_by_month'][0]['remaining_debt']=='1000.00'

        a=setup('Kapitalisiert oder bezahlt');l=loan(a,loan_type='private',installment_amount=None)
        charge(l,'20')
        result=req('GET','/reports/loans?until=2026-01-31&months=1')
        year=req('GET',f"/loans/{l['id']}/summary?year=2026")
        results['capitalized_interest_label']={'report':result,'year_summary':year}
        assert Decimal(year['interest_paid'])==0 and result['loans'][0]['interest_paid_by_year'][0]['interest']=='20.00'

        a=setup('Tilgungsfortschritt');l=loan(a,annual_interest_rate='12');p=pay(l,'250')
        after=getloan(l);schedule=plan(l)
        results['progress']={'loan':after,'schedule':schedule,'payment':p,'expected_progress':0.24}
        assert p['principal']=='240.00' and schedule[0]['planned_principal']=='90.00'

        a=setup('Tilgungsdarlehen umbenennen');l=loan(a,loan_type='installment',installment_amount=None,term_months=10)
        pay(l);before=getloan(l)
        # Exact plan fields emitted by LoanFormDialog for this existing installment loan.
        after=req('PATCH',f"/loans/{l['id']}",{'name':'Neuer Name','annual_interest_rate':'0',
            'extra_amount':'0.00','fixed_principal':None,'term_months':l['term_months']})
        results['installment_rename_extends_term']={'before':before,'after':after}
        assert before['open_installments']==9 and after['open_installments']==10

        a=setup('Zahlung über Monatsgrenze');l=loan(a,first_due_date='2026-02-28')
        income(a,'2026-02-01');income(a,'2026-03-01');pay(l,'100','2026-03-01')
        results['payment_in_following_month']={'february':budget('2026-02-01'),'march':budget('2026-03-01')}

        a=setup('Private Zinsen mit Belastung im Intervall');l=loan(a,loan_type='private',installment_amount=None,
            annual_interest_rate='36.5')
        charge(l,'1000','2026-01-06');p=pay(l,'100','2026-01-11')
        results['private_charge_interest_interval']={'payment':p,'expected_interest':'15.00',
            'calculation':'1000 * .365 * 5/365 + 2000 * .365 * 5/365 = 15'}
        assert p['interest']=='20.00'

        a=setup('Private Rückzahlung vor zukünftiger Belastung');l=loan(a,loan_type='private',installment_amount=None)
        charge(l,'100','2026-03-01');pay(l,'1100','2026-02-01')
        report=req('GET','/reports/loans?until=2026-02-28&months=1')
        results['future_charge_allows_early_overpayment']=report
        assert report['loans'][0]['remaining_by_month'][0]['remaining_debt']=='-100.00'

        # Positive controls: internal transfer conserves wealth; refunds reduce expenses;
        # Categorized refunds and transfer amounts must reconcile with net wealth.
        a=setup('Positive Kontrollen')
        b=req('POST','/accounts',{'name':'Sparen','type':'savings','opening_balance':'0','opening_balance_date':'2026-01-01'},201)
        tr=req('POST','/transfers',{'from_account_id':a['id'],'to_account_id':b['id'],'booking_date':'2026-01-10','amount':'250'},201)
        cat=req('POST','/categories',{'name':'Einkauf','type':'expense'},201)
        tx(a,'-100','2026-01-11',cat['id']);tx(a,'30','2026-01-12',cat['id'])
        rep=req('GET','/reports/summary?date_from=2026-01-01&date_to=2026-01-31')
        results['controls']={'net_worth':rep['net_worth'],'expenses':rep['movements']['expenses'],'net':rep['movements']['net']}
        assert rep['net_worth']=='4930.00' and rep['movements']['expenses']=='70.00'
        req('DELETE',f"/transactions/{tr['outgoing']['id']}",expected=204)
        rep2=req('GET','/reports/summary?date_from=2026-01-01&date_to=2026-01-31')
        assert rep2['net_worth']=='4930.00'
        assert req('GET',f"/transactions/{tr['incoming']['id']}",expected=404)['error']['code']=='not_found'
        cat2=req('POST','/categories',{'name':'Weiterer Einkauf','type':'expense'},201)
        split=req('POST','/transactions',{'account_id':a['id'],'amount':'-100','booking_date':'2026-01-15',
            'description':'Aufteilung','splits':[{'amount':'-70','category_id':cat['id']},
            {'amount':'-30','category_id':cat2['id']}]},201)
        rep3=req('GET','/reports/summary?date_from=2026-01-01&date_to=2026-01-31')
        assert rep3['net_worth']=='4830.00' and rep3['movements']['expenses']=='170.00'
        results['controls'].update(transfer_delete_net_worth=rep2['net_worth'],split_net_worth=rep3['net_worth'],split_expenses=rep3['movements']['expenses'])
        a=setup('Ungeprüfter Regelvorschlag')
        cat=req('POST','/categories',{'name':'Regelziel','type':'expense'},201)
        entry=tx(a,'-15','2026-11-03')
        req('POST','/mapping-rules',{'pattern':'Prüfbuchung','target_category_id':cat['id']},201)
        req('POST','/mapping-rules/apply?dry_run=false')
        entry=req('GET',f"/transactions/{entry['id']}")
        filtered=req('GET','/transactions?review_status=needs_review')
        review=req('GET','/review')
        results['unreviewed_rule_suggestion']={'transaction':entry,'filtered_total':filtered['total'],'review_total':review['total']}
        assert entry['review_status']=='auto_categorized' and filtered['total']==0 and review['total']==1
    (out/'nachweise.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k: 'reproduced' for k in results},indent=2))
finally:
    (out/'nachweise.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    clock.today=original_today
    app.dependency_overrides.pop(get_session,None)
    if engine:engine.dispose()
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    print('Isolated audit database removed:',name)
