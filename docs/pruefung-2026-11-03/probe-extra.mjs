import { chromium } from 'playwright'
import { readFileSync,writeFileSync } from 'node:fs'
const root='/tmp/finanz-review-20261103-uyaft4iq', s=JSON.parse(readFileSync(root+'/ui-state.json','utf8'))
const base='http://127.0.0.1:8017',H={'X-User-Id':String(s.user_id)}
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome'})
const page=await browser.newPage({viewport:{width:1440,height:960},timezoneId:'Europe/Berlin'})
await page.addInitScript(id=>localStorage.setItem('finanzplaner.profile',JSON.stringify({id,name:'Audit UI'})),s.user_id)
const out={}
async function post(path,data,headers=H){const r=await page.request.post(base+'/api'+path,{headers,data});if(!r.ok())throw Error(await r.text());return r.json()}
try {
 const a=await post('/categories',{name:'Audit Split A',type:'expense'}),b=await post('/categories',{name:'Audit Split B',type:'expense'})
 await post('/transactions',{account_id:s.account_id,booking_date:'2026-11-03',amount:'-12.50',description:'Audit Split Probe',counterparty:'Audit Händler',splits:[{amount:'-8',category_id:a.id},{amount:'-4.50',category_id:b.id}]})
 await page.goto(base+'/berichte?ansicht=kategorien&von=2026-11-01&bis=2026-11-01')
 await page.locator('.category-bar',{hasText:'Audit Split A'}).click()
 await page.locator('.detail-top',{hasText:'Audit Händler'}).waitFor()
 out.categoryDetail={net:await page.locator('.detail-figures .is-net dd').textContent(),payee:await page.locator('.detail-top li',{hasText:'Audit Händler'}).textContent()}
 await page.screenshot({path:root+'/screenshots/split-report.png'})
 await page.goto(base+`/buchungen?monat=alle&kategorie=${a.id}`)
 await page.locator('.tx-row').waitFor()
 out.filteredExpense=await page.locator('.tx-sum',{hasText:'Ausgaben'}).textContent()
 const bank=await post('/institutions',{name:'Audit Importbank'})
 const profile=await post('/import-profiles',{name:'Audit CSV',institution_id:bank.id,format:'csv',column_map:{booking_date:'Datum',description:'Text',amount:'Betrag'}})
 const upload=async(name,csv)=>{const r=await page.request.post(base+'/api/imports',{headers:H,multipart:{import_profile_id:String(profile.id),account_id:String(s.account_id),file:{name,mimeType:'text/csv',buffer:Buffer.from(csv)}}});if(!r.ok())throw Error(await r.text());return r.json()}
 const old=await upload('Audit Alt offen.csv','Datum;Text;Betrag\n02.11.2026;PagingProbe 203;-1,00\n')
 await post('/imports/process',undefined)
 const oldStatus=await (await page.request.get(base+'/api/imports/'+old.id,{headers:H})).json()
 for(let i=0;i<30;i++)await upload(`Audit Neu ${i}.csv`,`Datum;Text;Betrag\n03.11.2026;Neuer Probeimport ${i};-2,00\n`)
 await page.goto(base+'/import?id='+old.id)
 await page.locator('.import-row').first().waitFor()
 out.oldImport={id:old.id,status:oldStatus.status,shown:await page.getByText('Audit Alt offen.csv',{exact:true}).count(),rowCount:await page.locator('.import-row').count(),detailCount:await page.locator('.batch-detail').count(),directGet:(await page.request.get(base+'/api/imports/'+old.id,{headers:H})).status()}
 await page.screenshot({path:root+'/screenshots/old-import-hidden.png'})
 // Existing demo test confirmed a manual transaction as duplicate of a bank import.
 const H1={'X-User-Id':'1'}
 const batches=await (await page.request.get(base+'/api/imports',{headers:H1})).json()
 let tx
 for(const batch of batches){const rows=await (await page.request.get(base+`/api/imports/${batch.id}/rows`,{headers:H1})).json();for(const row of rows){if(row.resolution==='duplicate'&&row.matched_transaction_id){const candidate=await (await page.request.get(base+'/api/transactions/'+row.matched_transaction_id,{headers:H1})).json();if(candidate.source==='manual')tx=candidate}}}
 if(!tx)throw Error('No manually matched transaction from Paket 3')
 const ctx=await browser.newContext({viewport:{width:1440,height:960}})
 const p=await ctx.newPage()
 await p.addInitScript(()=>localStorage.setItem('finanzplaner.profile',JSON.stringify({id:1,name:'Fabian'})))
 await p.goto(base+`/buchungen?monat=alle&id=${tx.id}`)
 await p.locator('.tx-editor').waitFor()
 out.matchedManual={id:tx.id,source:tx.source,excludeButtons:await p.locator('.tx-editor').getByRole('button',{name:'Ausschließen',exact:true}).count(),deleteButtons:await p.locator('.tx-editor').getByRole('button',{name:'Löschen',exact:true}).count()}
 await p.locator('.tx-editor').getByRole('button',{name:'Löschen',exact:true}).click()
 const del=p.waitForResponse(r=>r.request().method()==='DELETE'&&r.url().endsWith('/transactions/'+tx.id))
 await p.getByRole('dialog').getByRole('button',{name:'Löschen',exact:true}).click()
 const dr=await del;out.matchedManual.deleteStatus=dr.status();out.matchedManual.error=await dr.json()
 await p.getByRole('dialog').waitFor({state:'hidden'})
 await p.screenshot({path:root+'/screenshots/manual-match-no-exclude.png'})
 console.log(JSON.stringify(out,null,2));writeFileSync(root+'/extra-evidence.json',JSON.stringify(out,null,2))
}finally{await browser.close()}
