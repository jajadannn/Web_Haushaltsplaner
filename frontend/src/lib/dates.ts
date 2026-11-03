/** Kalenderdaten kommen als "YYYY-MM-DD" – ohne Zeitzone, deshalb nie über new Date(string). */

export interface CalendarDate {
  year: number
  month: number // 1–12
  day: number
}

export function parseDate(value: string): CalendarDate {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) throw new Error(`Kein gültiges Datum: ${value}`)
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) }
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

const MONTHS_LONG = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
]
const MONTHS_SHORT = [
  'Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni',
  'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.',
]

/** "2026-11-01" → "November 2026" */
export function monthLabel(value: string): string {
  const { year, month } = parseDate(value)
  return `${MONTHS_LONG[month - 1]} ${year}`
}

/** "2029-12-30" → "Dez. 2029" */
export function shortMonthLabel(value: string): string {
  const { year, month } = parseDate(value)
  return `${MONTHS_SHORT[month - 1]} ${year}`
}

const pad = (n: number) => String(n).padStart(2, '0')

/** Zeitstempel (ISO mit Zone) → "18.11. · 21:04" in der Ortszeit des Displays */
export function standLabel(iso: string): string {
  const at = new Date(iso)
  return `${pad(at.getDate())}.${pad(at.getMonth() + 1)}. · ${pad(at.getHours())}:${pad(at.getMinutes())}`
}

/** "noch 13 Tage" / "noch 1 Tag" / "Monat vorbei" */
export function daysLeftLabel(days: number): string {
  if (days <= 0) return 'Monat vorbei'
  return days === 1 ? 'letzter Tag' : `noch ${days} Tage`
}

/** Heutiges Datum in der Ortszeit als "YYYY-MM-DD". */
export function todayISO(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** "2026-11-18" → "18.11." */
export function shortDate(value: string): string {
  const { month, day } = parseDate(value)
  return `${pad(day)}.${pad(month)}.`
}

/** "2026-11-18" → "18.11.2026" */
export function fullDate(value: string): string {
  const { year, month, day } = parseDate(value)
  return `${pad(day)}.${pad(month)}.${year}`
}

/** Erster Tag des Monats von `value` ± `delta` Monate, als "YYYY-MM-01". */
export function shiftMonth(value: string, delta: number): string {
  const { year, month } = parseDate(value)
  const index = year * 12 + (month - 1) + delta
  return `${Math.floor(index / 12)}-${pad((index % 12) + 1)}-01`
}

/** Letzter Tag des Monats von `value` als "YYYY-MM-DD". */
export function monthEnd(value: string): string {
  const { year, month } = parseDate(value)
  return `${year}-${pad(month)}-${pad(daysInMonth(year, month))}`
}

const WEEKDAYS = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag']

/** Tagesüberschrift für Listen: "Heute", "Gestern" oder "Mittwoch, 18.11." */
export function dayHeading(value: string, today: string = todayISO()): string {
  if (value === today) return 'Heute'
  const { year, month, day } = parseDate(value)
  const date = new Date(year, month - 1, day)
  const t = parseDate(today)
  const diff = Math.round((new Date(t.year, t.month - 1, t.day).getTime() - date.getTime()) / 86_400_000)
  if (diff === 1) return 'Gestern'
  return `${WEEKDAYS[date.getDay()]}, ${pad(day)}.${pad(month)}.${year === t.year ? '' : year}`
}

/** Datum ± Tage als "YYYY-MM-DD" (Kalenderrechnung ohne Zeitzone). */
export function addDays(value: string, days: number): string {
  const { year, month, day } = parseDate(value)
  const date = new Date(Date.UTC(year, month - 1, day + days))
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}
