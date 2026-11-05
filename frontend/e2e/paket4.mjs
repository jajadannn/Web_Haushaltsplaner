// Durchklick Paket 4 (KI-Ausbau: Vorschläge, Automatik, Belege, Vorschau, Assistent) gegen die Demo-API:
// node e2e/paket4.mjs  – erwartet frische Demodaten (scripts/seed_demo.py) und läuft ohne KI-Server.
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://localhost:5173'
const OUT = process.env.OUT ?? '../.impeccable/review'
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, timezoneId: 'Europe/Berlin' })
await page.addInitScript(() => localStorage.setItem('finanzplaner.profile', JSON.stringify({ id: 1, name: 'Fabian' })))
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('response', (r) => r.status() >= 500 && r.status() !== 503 && errors.push(`${r.status()} ${r.url()}`))
const step = (msg) => console.log('•', msg)
const H = { 'X-User-Id': '1' }
const api = async (method, path, data) => {
  const r = await page.request.fetch(`${BASE}/api${path}`, { method, headers: H, data })
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()} ${await r.text()}`)
  return r.status() === 204 ? null : r.json()
}

// 1. Auswertung anstoßen – die Demodaten enthalten einen Internetvertrag ohne Fixkost, eine Retoure und Stammhändler
const refreshed = await api('POST', '/suggestions/refresh')
const summary = await api('GET', '/suggestions/summary')
if (!summary.fixed_cost_new || !summary.rule || !summary.refund_match) {
  throw new Error('Erwartete Vorschläge fehlen: ' + JSON.stringify(summary))
}
step(`Auswertung: ${refreshed.new} neue Vorschläge (${Object.entries(summary).map(([k, v]) => `${k} ${v}`).join(', ')})`)

// 2. Erkannte Fixkost in den Einstellungen übernehmen
await page.goto(`${BASE}/einstellungen/fixkosten`)
await page.getByText('Erkannte Fixkosten').first().waitFor()
await page.getByText('Netzwelt GmbH').first().waitFor()
const [fixed] = await api('GET', '/suggestions?kind=fixed_cost_new&status=open')
const accepted = await api('POST', `/suggestions/${fixed.id}/accept`, {})
const fc = await api('GET', `/fixed-costs/${accepted.result_id}`)
if (fc.amount !== '39.99') throw new Error('Fixkost falsch übernommen: ' + JSON.stringify(fc))
await page.reload()
await page.getByText('Netzwelt GmbH').first().waitFor()
step('erkannte Fixkost sichtbar und übernommen')

// 3. Prüfliste: Vorschlagsbereich mit Regel- und Erstattungsvorschlägen
await page.goto(`${BASE}/pruefen`)
await page.getByText('Vorschläge').first().waitFor()
await page.getByText('Modehaus Nord').first().waitFor({ timeout: 10000 })
step('Prüfliste zeigt Vorschläge (Regeln, Erstattung)')

// 4. Automatik & KI, Verlauf, Anbieter, Einnahmen: Seiten laden ohne Fehler
for (const [path, text] of [
  ['/einstellungen/automatik', 'Automatik'],
  ['/einstellungen/verlauf', 'Verlauf'],
  ['/einstellungen/anbieter', 'Anbieter'],
  ['/einstellungen/einnahmen', 'Einnahmen'],
]) {
  await page.goto(BASE + path)
  await page.getByText(text).first().waitFor()
}
step('Automatik, Verlauf, Anbieter und Einnahmen laden')

// 5. Beleg hochladen (ohne KI bleibt er „wird gelesen“) und wieder löschen
await page.goto(`${BASE}/belege`)
await page.getByText('Belege & Verträge').first().waitFor()
const png = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(64)])
const upload = await page.request.post(`${BASE}/api/documents`, { headers: H, multipart: {
  kind: 'receipt', file: { name: 'e2e-beleg.png', mimeType: 'image/png', buffer: png } } })
if (upload.status() !== 201) throw new Error('Beleg-Upload: ' + upload.status())
const doc = await upload.json()
await page.reload()
await page.getByText('e2e-beleg.png').first().waitFor()
await api('DELETE', `/documents/${doc.id}`)
step('Beleg hochgeladen, angezeigt und gelöscht')

// 6. Start: Kontovorschau; Berichte: Monatsvergleich und Frage (ohne KI: freundlicher Hinweis)
await page.goto(`${BASE}/`)
await page.getByText('Vorschau').first().waitFor()
await page.goto(`${BASE}/berichte`)
await page.getByText('Monatsvergleich').first().waitFor()
step('Kontovorschau und Monatsvergleich sichtbar')

// 7. Natürliche Eingabe ohne KI: Regel erkennt Betrag und Datum, gespeichert wird nichts
const draft = await api('POST', '/entries/parse', { text: 'heute 4,20 € Bäcker' })
if (draft.amount !== '-4.20' || draft.ai_used) throw new Error('Entwurf falsch: ' + JSON.stringify(draft))
step('Buchungsentwurf aus Text (ohne KI) erkannt')

// 8. Übernahme zurücknehmen über den Verlauf
await api('POST', `/suggestions/${fixed.id}/revert`)
const after = await page.request.get(`${BASE}/api/fixed-costs/${accepted.result_id}`, { headers: H })
if (after.status() !== 404) throw new Error('Rücknahme hat die Fixkost nicht entfernt')
step('Übernahme zurückgenommen')

await page.screenshot({ path: `${OUT}/e2e-ki.png` })
await browser.close()
if (errors.length) throw new Error('Konsolenfehler:\n' + errors.join('\n'))
console.log('OK – Paket-4-Durchklick bestanden')
