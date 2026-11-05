import json, urllib.request
from pathlib import Path
base='http://127.0.0.1:8017/api'
def req(method,path,body=None,uid=None):
 h={'X-User-Id':str(uid)} if uid else {}
 if body is not None:h['Content-Type']='application/json'
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=h,method=method)
 with urllib.request.urlopen(r) as s:return json.load(s)
u=req('POST','/users',{'name':'Audit Laufzeiterhalt'})['id']
loans=[]
for name in ['Kontrolle','Umbenannt']:
 loans.append(req('POST','/loans',{'name':name,'lender_name':'Test','loan_type':'annuity','annual_interest_rate':'0','current_balance':'10000','balance_date':'2026-11-01','first_due_date':'2026-11-30','term_months':48},u))
l=loans[1]
renamed=req('PATCH',f"/loans/{l['id']}",{'name':'Nur Name geändert','lender_name':'Test','annual_interest_rate':'0','payment_account_id':None,'lender_iban':None,'payment_reference':None,'fixed_rate_until':None,'extra_amount':'0.00','installment_amount':l['installment_amount'],'term_months':None},u)
result=[]
for l in loans:
 after=req('PATCH',f"/loans/{l['id']}",{'annual_interest_rate':'6'},u)
 result.append({k:after[k] for k in ['name','term_months','installment_amount','open_installments','final_due_date']})
Path('/tmp/finanz-review-20261103-uyaft4iq/term-followup-evidence.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
