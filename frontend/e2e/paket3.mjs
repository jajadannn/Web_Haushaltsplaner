// Durchklick Paket 3 (Import, Prüfen, Berichte) gegen die Demo-API: node e2e/paket3.mjs
import { chromium } from 'playwright'
import { writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE = process.env.BASE ?? 'http://localhost:5173'
const OUT = process.env.OUT ?? '../.impeccable/review'
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, timezoneId: 'Europe/Berlin' })
await page.addInitScript(() => localStorage.setItem('finanzplaner.profile', JSON.stringify({ id: 1, name: 'Fabian' })))
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('response', (r) => r.status() >= 500 && errors.push(`${r.status()} ${r.url()}`))
const step = (msg) => console.log('•', msg)
const H = { 'X-User-Id': '1' }

// --- Vorbereitung über die API: Importprofil für die Sparkasse
const banks = await (await page.request.get(`${BASE}/api/institutions`, { headers: H })).json()
const sparkasse = banks.find((b) => b.name === 'Sparkasse')
const accounts = await (await page.request.get(`${BASE}/api/accounts`, { headers: H })).json()
const giro = accounts.find((a) => a.name === 'Girokonto')
const profile = await (await page.request.post(`${BASE}/api/import-profiles`, { headers: H, data: {
  name: 'E2E Sparkasse CSV', institution_id: sparkasse.id, format: 'csv',
  column_map: { booking_date: 'Buchungstag', counterparty: 'Empfänger', description: 'Verwendungszweck', amount: 'Betrag' },
} })).json()
if (!profile.id) throw new Error('Importprofil nicht angelegt: ' + JSON.stringify(profile))

// Eine vorhandene Buchung (Dublette per Fingerabdruck) und eine neue
const existing = (await (await page.request.get(`${BASE}/api/transactions?account_ids=${giro.id}&amount_max=-0.01&kind=regular&limit=50`, { headers: H })).json())
  .items.find((t) => t.source === 'manual' && t.counterparty && !t.splits.length)
const de = (iso) => iso.split('-').reverse().join('.')
const amountDe = (v) => v.replace('.', ',')
const today = new Date().toISOString().slice(0, 10)
const csv = ['Buchungstag;Empfänger;Verwendungszweck;Betrag',
  `${de(existing.booking_date)};${existing.counterparty};${existing.description};${amountDe(existing.amount)}`,
  `${de(today)};E2E Bioladen;Einkauf E2E;-17,35`].join('\n') + '\n'
const dir = mkdtempSync(join(tmpdir(), 'e2e-'))
const file = join(dir, `e2e_${Date.now()}.csv`)
writeFileSync(file, csv)

// --- Import über die Oberfläche
await page.goto(BASE + '/import')
await page.getByLabel('Importprofil').selectOption({ label: 'E2E Sparkasse CSV (CSV)' })
await page.getByLabel('Konto').selectOption({ label: 'Girokonto' })
await page.locator('input[type=file]').setInputFiles(file)
await page.getByText(/hochgeladen/).waitFor()
step('CSV hochgeladen')
// Kein Worker im Test: Verarbeitung über den Knopf „Jetzt verarbeiten“ anstoßen
await page.getByRole('button', { name: 'Jetzt verarbeiten' }).click({ timeout: 20000 })
await page.getByText('Klärung nötig').first().waitFor({ timeout: 15000 })
step('Import verarbeitet – Klärung nötig')
await page.screenshot({ path: `${OUT}/e2e-import.png` })
const detail = page.locator('.batch-detail')
await detail.getByRole('tab', { name: /Unklar \(1\)/ }).waitFor()
await detail.locator('.import-line', { hasText: existing.counterparty }).getByRole('button', { name: 'Ist Dublette' }).click()
await page.getByText('Als Dublette markiert').waitFor()
await detail.getByText('Alles geklärt').waitFor()
step('unklare Zeile als Dublette geklärt')
await detail.getByRole('button', { name: 'Import abschließen' }).click()
await page.getByText(/Import abgeschlossen: 1 Buchungen übernommen/).waitFor()
await page.getByText('erledigt').first().waitFor()
step('Import abgeschlossen – genau 1 neue Buchung')
const found = await (await page.request.get(`${BASE}/api/transactions?search=E2E%20Bioladen`, { headers: H })).json()
if (found.total !== 1) throw new Error(`E2E Bioladen ${found.total}× statt 1×`)

// --- Prüfen: neue Buchung steht ohne Kategorie in der Liste → einzeln bestätigen
await page.goto(BASE + '/pruefen')
const row = page.locator('.review-table tr', { hasText: 'E2E Bioladen' })
await row.waitFor()
const select = row.getByLabel('Kategorie', { exact: true })
const value = await select.evaluate((el) => [...el.options].find((o) => o.text === 'Lebensmittel')?.value)
await select.selectOption(value)
await row.getByRole('button', { name: 'Bestätigen' }).click()
await page.getByText('„E2E Bioladen“ bestätigt').waitFor()
await row.waitFor({ state: 'detached' })
step('Buchung in „Prüfen“ mit Kategorie bestätigt')

// Sammelbestätigung: alle markieren, Umbuchung? nein – Kategorie wählen und bestätigen
const before = await page.locator('.review-table tbody tr').count()
await page.getByLabel('Alle markieren').check()
const bulk = page.getByLabel('Kategorie für alle markierten')
const freizeit = await bulk.evaluate((el) => [...el.options].find((o) => o.text === 'Freizeit & Hobby')?.value)
await bulk.selectOption(freizeit)
await page.screenshot({ path: `${OUT}/e2e-pruefen-bulk.png` })
await page.locator('.bulk-bar').getByRole('button', { name: 'Bestätigen' }).click()
await page.getByText(`${before} Buchungen bestätigt`).waitFor()
await page.getByText('Alles geprüft').waitFor()
step(`Sammelbestätigung für ${before} Buchungen – Prüfliste leer`)

// --- Berichte: Ansichten wechseln, Kategorie wählen
await page.goto(BASE + '/berichte?ansicht=kategorien')
await page.locator('.category-bar', { hasText: 'Lebensmittel' }).click()
await page.locator('.category-detail h3', { hasText: 'Lebensmittel' }).waitFor()
await page.locator('.detail-top').getByText('E2E Bioladen').waitFor()
step('Bericht Kategorien: Detail Lebensmittel mit dem importierten Empfänger')
for (const tab of ['Verlauf', 'Konten', 'Kredite', 'Überblick']) {
  await page.getByRole('tab', { name: tab }).click()
  await page.waitForURL(new RegExp(`ansicht=`))
}
await page.locator('.pair-group').first().hover()
step('alle Berichtsansichten laden ohne Fehler')

// --- Aufräumen: Importprofil bleibt (in Verwendung), Demo-DB wird ohnehin neu befüllt
if (errors.length) throw new Error('Fehler:\n' + errors.join('\n'))
console.log('OK – Paket-3-Durchklick bestanden')
await browser.close()
