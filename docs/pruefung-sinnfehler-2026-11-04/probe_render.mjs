// Run from frontend/: node --input-type=module < ../docs/pruefung-sinnfehler-2026-11-04/probe_render.mjs
import { createServer } from 'vite'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const moduleSource = `
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {ProfileProvider} from '/src/app/ProfileContext.tsx'
import {AddEntryProvider} from '/src/app/AddEntry.tsx'
import {ToastProvider} from '/src/ui/overlay.tsx'
import {TransactionsPage} from '/src/pages/buchungen/TransactionsPage.tsx'
export function render(items) {
  const client = new QueryClient({defaultOptions:{queries:{staleTime:Infinity,retry:false,gcTime:0}}})
  const p=['p',1]
  client.setQueryData([...p,'accounts','/accounts',{include_archived:true}],[{id:1,name:'Giro',type:'checking',archived_at:null}])
  client.setQueryData([...p,'categories','/categories',null],[{id:999,name:'Einkauf',parent_id:null,type:'expense'}])
  client.setQueryData([...p,'transactions','/transactions',{date_from:'2026-11-01',date_to:'2026-11-30',limit:100,offset:0}],{items,total:items.length,limit:100,offset:0})
  const h=React.createElement
  const html=renderToStaticMarkup(h(QueryClientProvider,{client},h(ProfileProvider,null,h(MemoryRouter,{initialEntries:['/buchungen?monat=2026-11-01']},h(ToastProvider,null,h(AddEntryProvider,null,h(TransactionsPage)))))))
  client.clear()
  return html
}
`
const server=await createServer({configFile:false,appType:'custom',server:{middlewareMode:true},plugins:[{
  name:'audit-render',resolveId(id){if(id==='virtual:audit-render')return '\0audit-render'},
  load(id){if(id==='\0audit-render')return moduleSource}
}]})
const out=new URL('../docs/pruefung-sinnfehler-2026-11-04/',`file://${process.cwd()}/`)
globalThis.window={localStorage:{getItem:()=>JSON.stringify({id:1,name:'Audit'})}}
try {
 const {render}=await server.ssrLoadModule('virtual:audit-render')
 const evidence=JSON.parse(await fs.readFile(new URL('nachweise.json',out),'utf8'))
 const base={...evidence.unreviewed_rule_suggestion.transaction,account_id:1,category_id:999,booking_date:'2026-11-03'}
 const html=render([{...base,id:1,amount:'-100.00',review_status:'confirmed'}, {...base,id:2,amount:'30.00',review_status:'confirmed'}])
 assert.ok(html.includes('30,00')&&html.includes('100,00'))
 const ruleHtml=render([{...base,id:3,amount:'-15.00'}])
 assert.ok(ruleHtml.includes('title="geprüft"'))
 assert.ok(!ruleHtml.includes('class="review-badge"'))
 const summary=html.match(/<div class="tx-summary">([\s\S]*?)<div class="tx-days">/)?.[1].replace(/<[^>]+>/g,' ')
 const result={refund_summary_text:summary,unconfirmed_source_status:base.review_status,unconfirmed_rendered_title:'geprüft'}
 await fs.writeFile(new URL('render-nachweise.json',out),JSON.stringify(result,null,2)+'\n')
 console.log(JSON.stringify(result,null,2))
} finally {delete globalThis.window;await server.close()}
