// Screenshot mit dem installierten Chrome:
//   node scripts/shot.mjs <url> <ausgabe.png> [breite] [höhe] [--profil id:Name] [--voll]
import { chromium } from 'playwright'
const args = process.argv.slice(2)
const flag = (name) => {
  const i = args.indexOf(name)
  return i >= 0 ? args.splice(i, 2)[1] : undefined
}
const profile = flag('--profil')
const full = args.includes('--voll') && args.splice(args.indexOf('--voll'), 1)
const [url, out, w = '1536', h = '1024'] = args
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' })
const page = await browser.newPage({ viewport: { width: Number(w), height: Number(h) }, timezoneId: 'Europe/Berlin' })
if (profile) {
  const [id, ...name] = profile.split(':')
  await page.addInitScript((p) => localStorage.setItem('finanzplaner.profile', JSON.stringify(p)),
    { id: Number(id), name: name.join(':') })
}
await page.goto(url, { waitUntil: 'networkidle' })
await page.evaluate(() => document.fonts.ready)
await page.waitForTimeout(500)
await page.screenshot({ path: out, fullPage: Boolean(full) })
await browser.close()
