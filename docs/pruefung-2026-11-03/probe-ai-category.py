import json
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine
from sqlmodel import Session
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import app
from app.db import get_session
from app.services import ai_review
s=json.loads(Path('/tmp/finanz-review-20261103-uyaft4iq/state.json').read_text())
u=make_url(Settings().database_url).set(database=s['database'])
cfg=Config('alembic.ini');cfg.set_main_option('sqlalchemy.url',u.render_as_string(hide_password=False));command.upgrade(cfg,'head')
e=create_engine(u)
def sessions():
 with Session(e) as db:yield db
app.dependency_overrides[get_session]=sessions
result=[]
with TestClient(app,client=('127.0.0.1',51000)) as c:
 user=c.post('/users',json={'name':'Audit KI Kategorien'}).json();h={'X-User-Id':str(user['id'])}
 def post(path,data):
  r=c.post(path,json=data,headers=h);assert r.status_code<300,r.text;return r.json()
 account=post('/accounts',{'name':'Test','type':'checking','opening_balance':'0','opening_balance_date':'2026-01-01'})
 for changes in [{'active':False},{'type':'income'}]:
  cat=post('/categories',{'name':str(changes),'type':'expense'})
  tx=post('/transactions',{'account_id':account['id'],'amount':'-50','booking_date':'2026-11-03','description':'Prüfung'})
  def answer(messages):
   r=c.patch(f"/categories/{cat['id']}",json=changes,headers=h);assert r.status_code==200,r.text
   return json.dumps({'kategorie_id':cat['id'],'sicherheit':'hoch','begruendung':'Test'})
  ai_review.chat=answer
  with Session(e) as db:ai_review.review_one(db,tx['id'])
  t=c.get(f"/transactions/{tx['id']}",headers=h).json()
  confirm=c.post('/review/confirm-all',headers=h).json()
  result.append({'category_change_while_ai_pending':changes,'assigned_category_id':t['category_id'],'expected_category_id':cat['id'],'review_status':t['review_status'],'confirm_all':confirm})
app.dependency_overrides.clear();e.dispose()
p=Path('/tmp/finanz-review-20261103-uyaft4iq/ai-category-evidence.json');p.write_text(json.dumps(result,indent=2));print(p.read_text())
