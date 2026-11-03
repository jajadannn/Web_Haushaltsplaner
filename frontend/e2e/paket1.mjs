// Durchklick Paket 1 gegen die Demo-API: node e2e/paket1.mjs
// Voraussetzung: Vite auf :5173, API mit finanzplaner_demo auf :8000 (scripts/seed_demo.py)
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://localhost:5173'
const OUT = process.env.OUT ?? '../.impeccable/review'
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, timezoneId: 'Europe/Berlin' })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

const cents = (text) => {
  const m = /(−|-)?([\d.]+),(\d\d)/.exec(text)
  return (m[1] ? -1 : 1) * (Number(m[2].replace(/\./g, '')) * 100 + Number(m[3]))
}
const step = (msg) => console.log('•', msg)

// 1. Ohne Profil → Profilwahl
await page.goto(BASE + '/')
await page.waitForURL('**/profil')
step('ohne Profil landet man auf /profil')
await page.getByRole('button', { name: /Fabian/ }).click()
await page.waitForURL(BASE + '/')
step('Profil Fabian gewählt')

// 2. Spielraum ablesen
const amount = page.locator('.available-amount')
await amount.waitFor()
const beforeText = (await amount.textContent()).trim()
const before = cents(beforeText)
const spentBefore = cents(await page.locator('.breakdown div', { hasText: 'Ausgaben bisher' }).locator('dd').textContent())
step(`frei verfügbar vorher ${before / 100}`)

// 3. Ausgabe erfassen
await page.getByRole('button', { name: 'Ausgabe hinzufügen' }).first().click()
const dialog = page.getByRole('dialog')
await dialog.getByLabel('Betrag').fill('12,5')
await dialog.getByRole('radio', { name: 'Lebensmittel' }).click()
await dialog.getByLabel('Wofür (optional)').fill('E2E Testkauf')
await page.screenshot({ path: `${OUT}/e2e-dialog.png` })
await dialog.getByRole('button', { name: 'Speichern' }).click()
await dialog.waitFor({ state: 'hidden' })
await page.getByText('Ausgabe über 12,50 € gespeichert').waitFor()
step('Ausgabe 12,50 € gespeichert, Meldung erscheint')

// 4. Spielraum sinkt genau um 12,50 €, Ausgabe steht oben in der Liste
await page.waitForFunction((b) => {
  const t = document.querySelector('.available-amount')?.textContent ?? ''
  return !t.includes(b)
}, beforeText)
const after = cents(await amount.textContent())
const spentAfter = cents(await page.locator('.breakdown div', { hasText: 'Ausgaben bisher' }).locator('dd').textContent())
if (before - after !== 1250) throw new Error(`Spielraum sank um ${(before - after) / 100} statt 12,50`)
if (spentAfter - spentBefore !== 1250) throw new Error(`Ausgaben stiegen um ${(spentAfter - spentBefore) / 100}`)
step('Spielraum −12,50 €, Ausgaben bisher +12,50 €')
await page.getByText('E2E Testkauf').first().waitFor()
step('Ausgabe steht in „Letzte Ausgaben“')

// 5. Fehlerfall: ohne Betrag speichern
await page.keyboard.press('n')
await dialog.waitFor()
await dialog.getByRole('button', { name: 'Speichern' }).click()
await dialog.getByText('Bitte einen Betrag eingeben').waitFor()
step('Taste N öffnet Erfassung; ohne Betrag erscheint die Feldmeldung')
await page.keyboard.press('Escape')

await page.screenshot({ path: `${OUT}/e2e-start-nachher.png` })

// 6. Buchungen: Testkauf aufteilen (8,00 Lebensmittel + 4,50 Drogerie)
await page.getByRole('link', { name: 'Buchungen' }).first().click()
await page.waitForURL('**/buchungen')
const row = page.locator('.tx-row', { hasText: 'E2E Testkauf' })
await row.locator('.tx-line').click()
const editor = row.locator('.tx-editor')
await editor.getByRole('button', { name: 'Aufteilen' }).click()
await editor.getByRole('textbox', { name: 'Teil 1', exact: true }).fill('8')
await editor.getByRole('textbox', { name: 'Teil 2', exact: true }).fill('4,5')
await editor.getByText('Vollständig verteilt').waitFor()
const selects = editor.locator('.split-row select')
// Optionen tragen ggf. die Oberkategorie davor („Einkäufe › Lebensmittel“)
const pick = async (select, name) => {
  const value = await select.evaluate((el, n) => [...el.options].find((o) => o.text.endsWith(n))?.value, name)
  if (!value) throw new Error(`Kategorie ${name} nicht gefunden`)
  await select.selectOption(value)
}
await pick(selects.nth(0), 'Lebensmittel')
await pick(selects.nth(1), 'Drogerie & Friseur')
await page.screenshot({ path: `${OUT}/e2e-aufteilen.png` })
await editor.getByRole('button', { name: 'Speichern' }).click()
await page.getByText('Buchung gespeichert').waitFor()
await row.getByText('aufgeteilt in 2 Teile').waitFor()
await row.locator('.tx-splits').getByText('Drogerie & Friseur').waitFor()
step('Buchung in 2 Teile aufgeteilt, Teile erscheinen eingerückt')

// 7. Suche und „Nur ungeprüfte“
await page.getByPlaceholder('Suchen …').fill('PayPal')
await page.waitForURL(/q=PayPal/)
await page.locator('.tx-row').first().getByText('PayPal').waitFor()
if (await page.locator('.tx-row', { hasText: 'E2E Testkauf' }).count()) throw new Error('Suche filtert nicht')
await page.getByPlaceholder('Suchen …').fill('')
await page.waitForURL((u) => !u.search.includes('q='))
await page.getByText('Nur ungeprüfte').click()
await page.waitForURL(/pruefen=1/)
await page.waitForFunction(() => {
  const rows = document.querySelectorAll('.tx-row').length
  return rows > 0 && rows === document.querySelectorAll('.review-badge').length
}, null, { timeout: 10000 }).catch(() => {})
const badges = await page.locator('.review-badge').count()
const rows = await page.locator('.tx-row').count()
if (badges !== rows) throw new Error(`Nur ungeprüfte zeigt ${rows} Zeilen, davon ${badges} ungeprüft`)
step(`Suche und Filter „Nur ungeprüfte“ (${rows} Zeilen) funktionieren`)
await page.getByText('Nur ungeprüfte').click()
await page.waitForURL((u) => !u.search.includes('pruefen'))

// 8. Manuelle Buchung löschen
await page.locator('.tx-row', { hasText: 'E2E Testkauf' }).locator('.tx-line').click()
await page.locator('.tx-editor').getByRole('button', { name: 'Löschen' }).click()
await page.getByRole('dialog').getByRole('button', { name: 'Löschen' }).click()
await page.getByText('Buchung gelöscht').waitFor()
if (await page.locator('.tx-row', { hasText: 'E2E Testkauf' }).count()) throw new Error('Buchung nicht gelöscht')
step('manuelle Buchung gelöscht')
await page.screenshot({ path: `${OUT}/e2e-buchungen.png` })
if (errors.length) throw new Error('Konsolenfehler:\n' + errors.join('\n'))
console.log('OK – Paket-1-Durchklick bestanden')
await browser.close()
