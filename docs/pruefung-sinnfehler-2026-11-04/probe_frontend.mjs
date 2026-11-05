// Run from frontend/: node --input-type=module < ../docs/pruefung-sinnfehler-2026-11-04/probe_frontend.mjs
import { createServer } from 'vite'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const out = new URL('../docs/pruefung-sinnfehler-2026-11-04/', `file://${process.cwd()}/`)
const server = await createServer({ configFile: false, server: { middlewareMode: true }, appType: 'custom' })
try {
  const { loanProgress } = await server.ssrLoadModule('/src/lib/loanProgress.ts')
  const { fixedCostCandidates } = await server.ssrLoadModule('/src/pages/einstellungen/fixedCostCandidates.ts')
  const { filterToQuery, parseFilter } = await server.ssrLoadModule('/src/pages/buchungen/filters.ts')
  const evidence = JSON.parse(await fs.readFile(new URL('nachweise.json',out),'utf8'))
  const progress = loanProgress(evidence.progress.loan,evidence.progress.schedule)
  assert.ok(Math.abs(progress - (90/850)) < 1e-12)
  const quarterly = fixedCostCandidates([
    {id:1,booking_date:'2026-07-15',amount:'-90.00',counterparty:'Quartalsbeitrag',description:'Quartal 3',category_id:1},
    {id:2,booking_date:'2026-10-15',amount:'-90.00',counterparty:'Quartalsbeitrag',description:'Quartal 4',category_id:1},
  ])
  assert.equal(quarterly[0].monthly,true)
  const filter=filterToQuery(parseFilter(new URLSearchParams('pruefen=1'),'2026-11-01'))
  assert.equal(filter.review_status,'needs_review')
  const results={progress:{actual:progress,expected:.24,aria_percent:Math.round(progress*100)},quarterly,unreviewed_filter:filter}
  await fs.writeFile(new URL('frontend-nachweise.json',out),JSON.stringify(results,null,2)+'\n')
  console.log(JSON.stringify(results,null,2))
} finally { await server.close() }
