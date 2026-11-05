import json, urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8017/api'
def req(method,path,body=None,uid=None):
 headers={'X-User-Id':str(uid)} if uid else {}
 if body is not None: headers['Content-Type']='application/json'
 r=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
 with urllib.request.urlopen(r,timeout=20) as response:
  raw=response.read()
  return json.loads(raw) if raw else None
def setup(name):
 u=req('POST','/users',{'name':name})['id']
 a=req('POST','/accounts',{'name':'Prüfkonto','type':'checking','opening_balance':'0','opening_balance_date':'2026-01-01'},u)['id']
 cat=req('POST','/categories',{'name':'Prüfeinnahmen','type':'income'},u)['id']
 req('POST','/transactions',{'account_id':a,'booking_date':'2026-11-01','amount':'1000','description':'Einnahme','category_id':cat},u)
 return u,a
def budget(u):return req('GET','/budget/month?month=2026-11-01',uid=u)
def loan(u,a,**extra):
 return req('POST','/loans',{'name':'Prüfkredit','lender_name':'Prüfbank','loan_type':'private','annual_interest_rate':'0','current_balance':'1000','balance_date':'2026-10-01','first_due_date':'2026-11-02','payment_account_id':a,**extra},u)
results={}
u,a=setup('Audit ohne Kreditplan');l=loan(u,a)
before=budget(u)
p=req('POST',f"/loans/{l['id']}/payments",{'booking_date':'2026-11-02','amount':'250'},u)
after=budget(u)
results['private_no_schedule']={'payment':p,'before':before,'after':after}
u,a=setup('Audit Fixkost Abweichung')
cat=req('POST','/categories',{'name':'Stromtest','type':'expense'},u)['id']
req('POST','/fixed-costs',{'name':'Strom','amount':'100','due_day':2,'category_id':cat},u)
req('POST','/transactions',{'account_id':a,'booking_date':'2026-11-02','amount':'-150','description':'Strom','category_id':cat},u)
results['fixed_above_plan']=budget(u)
u,a=setup('Audit Kredit Abweichung');l=loan(u,a,loan_type='annuity',annual_interest_rate='12',installment_amount='100')
req('POST',f"/loans/{l['id']}/payments",{'booking_date':'2026-11-02','amount':'250'},u)
results['loan_above_plan']=budget(u)
u,a=setup('Audit Doppelerkennung');l=loan(u,a,loan_type='annuity',annual_interest_rate='12',installment_amount='100')
req('POST',f"/loans/{l['id']}/payments",{'booking_date':'2026-11-02','amount':'100'},u)
cats=req('GET','/categories',uid=u)
cat=next(x['id'] for x in cats if x['system_key']=='loan_interest')
req('POST','/fixed-costs',{'name':'Andere Fixkosten','amount':'50','due_day':3,'category_id':cat},u)
results['fixed_matches_loan']=budget(u)
u,a=setup('Audit UI')
for i in range(204):
 req('POST','/transactions',{'account_id':a,'booking_date':'2026-11-02','amount':'-1','description':f'PagingProbe {i:03d}'},u)
A=req('POST','/categories',{'name':'Audit Quelle','type':'expense'},u)
B=req('POST','/categories',{'name':'Audit Kind','type':'expense','parent_id':A['id']},u)
R=req('POST','/categories',{'name':'Audit Wurzel','type':'expense'},u)
T=req('POST','/categories',{'name':'Audit Ziel','type':'expense','parent_id':R['id']},u)
state={'user_id':u,'account_id':a,'source_category':A,'child_category':B,'target_category':T}
Path('/tmp/finanz-review-20261103-uyaft4iq/ui-state.json').write_text(json.dumps(state))
Path('/tmp/finanz-review-20261103-uyaft4iq/budget-evidence.json').write_text(json.dumps(results,indent=2))
for name,r in results.items():
 if name=='private_no_schedule': print(name,'before',r['before']['available'],'after',r['after']['available'],'payment_principal',r['payment']['principal'])
 else: print(name,json.dumps({k:r[k] for k in ['income','fixed_total','fixed_paid','variable_spent','available','items']}))
print('UI',state)
