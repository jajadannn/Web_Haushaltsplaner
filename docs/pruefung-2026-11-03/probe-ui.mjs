import { chromium } from 'playwright'
import { readFileSync, writeFileSync } from 'node:fs'
const root='/tmp/finanz-review-20261103-uyaft4iq'
const s=JSON.parse(readFileSync(root+'/ui-state.json','utf8'))
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome'})
const page=await browser.newPage({viewport:{width:1440,height:960},timezoneId:'Europe/Berlin'})
await page.addInitScript((id)=>localStorage.setItem('finanzplaner.profile',JSON.stringify({id,name:'Audit UI'})),s.user_id)
const base='http://127.0.0.1:8017', H={'X-User-Id':String(s.user_id)}
const output={}
try {
 await page.goto(base+'/buchungen?monat=alle')
 await page.locator('.tx-row').first().waitFor()
 output.firstPage=await page.locator('.tx-row').count()
 await page.getByRole('button',{name:/Weitere.*laden/}).click()
 await page.waitForFunction(()=>document.querySelectorAll('.tx-row').length===200)
 const bad=page.waitForResponse(r=>r.url().includes('limit=300'))
 await page.getByRole('button',{name:/Weitere.*laden/}).click()
 const resp=await bad
 output.thirdPage={status:resp.status(),body:await resp.json()}
 await page.getByRole('alert').first().waitFor()
 output.rowsAfterThirdPage=await page.locator('.tx-row').count()
 await page.screenshot({path:root+'/screenshots/paging-422.png'})
 await page.goto(base+'/einstellungen/kategorien')
 await page.locator('.settings-row').filter({has:page.locator('strong',{hasText:/^Audit Quelle$/})}).click()
 await page.locator('.settings-form').getByRole('button',{name:'Zusammenführen',exact:true}).click()
 const mergeDialog=page.getByRole('dialog',{name:'In andere Kategorie zusammenführen'})
 await mergeDialog.getByLabel('Zielkategorie').selectOption(String(s.target_category.id))
 const mergeResponse=page.waitForResponse(r=>r.url().endsWith(`/categories/${s.source_category.id}/merge`))
 await mergeDialog.getByRole('button',{name:'Zusammenführen',exact:true}).click()
 output.mergeStatus=(await mergeResponse).status()
 await page.reload()
 await page.locator('.settings-row').filter({has:page.locator('strong',{hasText:/^Audit Wurzel$/})}).waitFor()
 const categories=await (await page.request.get(base+'/api/categories',{headers:H})).json()
 output.nestedCategory={api:categories.find(c=>c.id===s.child_category.id),visibleRows:await page.locator('.settings-row',{hasText:'Audit Kind'}).count()}
 await page.screenshot({path:root+'/screenshots/category-hidden.png'})
 await page.goto(base+'/einstellungen/fixkosten')
 await page.getByRole('button',{name:'Fixkost anlegen'}).first().click()
 await page.locator('.settings-form').getByLabel('Name',{exact:true}).fill('Ungespeicherter Entwurf')
 await page.locator('.settings-form').getByLabel('Betrag',{exact:true}).fill('123,45')
 await page.setViewportSize({width:1000,height:960})
 const d=page.getByRole('dialog',{name:'Neue Fixkost'})
 await d.waitFor()
 output.resizeDraft={name:await d.getByLabel('Name',{exact:true}).inputValue(),amount:await d.getByLabel('Betrag',{exact:true}).inputValue()}
 await page.screenshot({path:root+'/screenshots/resize-reset.png'})
 await page.setViewportSize({width:1440,height:960})
 const created=await (await page.request.post(base+'/api/transactions',{headers:H,data:{account_id:s.account_id,booking_date:'2026-11-03',amount:'-3.21',description:'AuditDeleteProbe'}})).json()
 await page.goto(base+'/buchungen?monat=alle&q=AuditDeleteProbe')
 await page.locator('.tx-row .tx-line').click()
 await page.locator('.tx-editor').getByRole('button',{name:'Löschen',exact:true}).click()
 const delResponse=page.waitForResponse(r=>r.request().method()==='DELETE'&&r.url().endsWith('/transactions/'+created.id))
 await page.getByRole('dialog').getByRole('button',{name:'Löschen',exact:true}).click()
 output.deleteStatus=(await delResponse).status()
 await page.locator('.tx-row').waitFor({state:'detached'})
 output.deleteToast={count:await page.getByText('Buchung gelöscht',{exact:true}).count(),url:page.url(),apiStatus:(await page.request.get(base+'/api/transactions/'+created.id,{headers:H})).status()}
 await page.screenshot({path:root+'/screenshots/delete-without-toast.png'})
 console.log(JSON.stringify(output,null,2))
 writeFileSync(root+'/ui-evidence.json',JSON.stringify(output,null,2))
} finally {await browser.close()}
