import json,os,threading,urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine,text
from app.config import Settings
from sqlmodel import Session
from app.models import User,Loan
from app.services.loans import payments,core
from app.schemas.loan import LoanPaymentCreate
root=Path('/tmp/finanz-review-20261103-uyaft4iq')
state=json.loads((root/'state.json').read_text())
url=make_url(Settings().database_url).set(database=state['database'])
assert url.database.startswith('finanzplaner_review_')
engine=create_engine(url)
def post(path,body,uid=None):
 h={'Content-Type':'application/json'}
 if uid:h['X-User-Id']=str(uid)
 r=urllib.request.Request('http://127.0.0.1:8017/api'+path,data=json.dumps(body).encode(),headers=h,method='POST')
 with urllib.request.urlopen(r) as resp:return json.load(resp)
u=post('/users',{'name':'Audit parallele Tilgung'})['id']
a=post('/accounts',{'name':'Giro','type':'checking','opening_balance':'2000','opening_balance_date':'2026-01-01'},u)['id']
l=post('/loans',{'name':'Privatkredit Race','lender_name':'Oma','loan_type':'private','annual_interest_rate':'0','current_balance':'1000','balance_date':'2026-10-01','payment_account_id':a},u)['id']
barrier=threading.Barrier(2)
original=payments.remaining_debt
def read_then_sync(*args,**kw):
 value=original(*args,**kw)
 barrier.wait(timeout=8)
 return value
payments.remaining_debt=read_then_sync
def worker(i):
 with Session(engine) as session:
  session.execute(text("SET LOCAL statement_timeout='10s'"))
  try:
   p=payments.record_payment(session,session.get(User,u),session.get(Loan,l),LoanPaymentCreate(booking_date='2026-11-03',amount='750'))
   pid=p.id
   session.commit()
   return {'request':i,'committed_payment_id':pid}
  except Exception as e:
   session.rollback()
   return {'request':i,'error':type(e).__name__,'message':str(e).split('\n')[0]}
with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,[1,2]))
with Session(engine) as s:
 debt=str(core.remaining_debt(s,s.get(Loan,l)))
out={'results':results,'remaining_debt':debt,'loan_id':l,'setup':'1000 EUR private loan; two concurrent payments of 750 EUR; barrier after existing remaining-debt reads only'}
(root/'race-evidence.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
