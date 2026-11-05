/**
 * Fixkosten aus den letzten Buchungen vorschlagen: eine Zeile je Empfänger. „Monatlich“
 * (typische Fixkost) heißt: in mindestens zwei aufeinanderfolgenden Monaten, im Abstand
 * von etwa einem Monat und in ähnlicher Höhe – Supermarkt oder Tankstelle sind das nicht.
 * Regelmäßige größere Abstände (Quartal, Halbjahr, Jahr) werden erkannt, aber nicht als
 * monatlich geführt; ihr Betrag wird auf einen Monatsbetrag umgerechnet (Fixkosten sind
 * im Backend ausschließlich monatlich). Monatliche zuerst.
 * Was schon als Fixkost erfasst ist (Erkennungstext oder gleicher Betrag in gleicher
 * Kategorie), fällt heraus – ebenso Kreditraten (aufgeteilte bzw. Kreditbuchungen), die
 * der Spielraum ohnehin einplant.
 */

export interface CandidateTx {
  id: number
  booking_date: string
  amount: string
  description: string
  counterparty: string | null
  category_id: number | null
  source?: string
  splits?: unknown[]
}

export interface Candidate {
  key: string
  /** jüngste Buchung dieses Empfängers – daraus wird das Formular vorbelegt */
  latest: CandidateTx
  name: string
  /** Betrag ohne Vorzeichen, z. B. "54.23" */
  amount: string
  dueDay: number
  matchText: string
  /** Anzahl verschiedener Monate mit einer Buchung */
  months: number
  count: number
  monthly: boolean
  /** erkannter Abstand der Zahlungen */
  interval: Interval
  /** Betrag pro Monat (bei nicht-monatlichen Zahlungen umgerechnet), z. B. "30.00" */
  monthlyAmount: string
}

export type Interval = 'monthly' | 'quarterly' | 'semiannual' | 'yearly' | 'irregular'

/** Monate je Zahlung; Basis der Umrechnung auf den Monatsbetrag. */
export const INTERVAL_MONTHS: Record<Exclude<Interval, 'irregular'>, number> = {
  monthly: 1, quarterly: 3, semiannual: 6, yearly: 12,
}

export interface ExistingFixedCost {
  match_text: string | null
  amount: string
  category_id: number | null
}

const AMOUNT_TOLERANCE = 0.15 // ±15 % gilt noch als „gleicher Betrag“ (z. B. Stromabschlag angepasst)

const cents = (amount: string) => Math.abs(Math.round(Number(amount) * 100))

const normalize = (text: string) => text.toLowerCase().replace(/\s+/g, ' ').trim()

function keyOf(tx: CandidateTx): string {
  return tx.counterparty?.trim() ? `c:${normalize(tx.counterparty)}` : `d:${normalize(tx.description).slice(0, 40)}`
}

const dayNumber = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) / 86_400_000
const monthIndex = (iso: string) => Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1

function similarAmounts(list: CandidateTx[]): boolean {
  const values = list.map((t) => cents(t.amount))
  const max = Math.max(...values)
  return max > 0 && (max - Math.min(...values)) / max <= AMOUNT_TOLERANCE
}

/**
 * Abstand der Zahlungen: nur wenn es höchstens eine Buchung je Monat gibt (monatlich
 * zusätzlich: bis eine Zusatzbuchung), alle Monatsabstände gleich sind und die Tagesabstände
 * zum Intervall passen. Sonst „unregelmäßig“.
 */
export function detectInterval(list: CandidateTx[], months: number): Interval {
  if (months < 2 || !similarAmounts(list)) return 'irregular'
  // je Monat die jüngste Buchung, aufsteigend
  const perMonth = new Map<number, string>()
  for (const t of list) {
    const m = monthIndex(t.booking_date)
    if (!perMonth.has(m) || t.booking_date > perMonth.get(m)!) perMonth.set(m, t.booking_date)
  }
  const idx = [...perMonth.keys()].sort((a, b) => a - b)
  const gaps = idx.slice(1).map((m, i) => m - idx[i])
  if (gaps.some((g) => g !== gaps[0])) return 'irregular'
  const step = gaps[0]
  const kind = (Object.entries(INTERVAL_MONTHS).find(([, n]) => n === step)?.[0] ?? null) as Interval | null
  if (!kind || kind === 'irregular') return 'irregular'
  if (kind === 'monthly' ? list.length > months + 1 : list.length !== months) return 'irregular'
  const dates = idx.map((m) => perMonth.get(m)!)
  const expected = step * 30.44
  const tolerance = step === 1 ? 10 : 12
  const ok = dates.slice(1).every((d, i) => Math.abs(dayNumber(d) - dayNumber(dates[i]) - expected) <= tolerance)
  return ok ? kind : 'irregular'
}

/** Betrag je Zahlung (ohne Vorzeichen) auf einen Monat umgerechnet, auf Cent gerundet. */
function perMonth(amount: string, interval: Interval): string {
  const divisor = interval === 'irregular' ? 1 : INTERVAL_MONTHS[interval]
  return (Math.round(cents(amount) / divisor) / 100).toFixed(2)
}

export function fixedCostCandidates(
  transactions: CandidateTx[],
  existing: ExistingFixedCost[] = [],
): Candidate[] {
  const taken = existing.map((f) => f.match_text).filter((t): t is string => Boolean(t?.trim())).map(normalize)
  const sameAsExisting = (tx: CandidateTx) =>
    existing.some((f) => f.category_id !== null && f.category_id === tx.category_id && cents(f.amount) === cents(tx.amount))
  const groups = new Map<string, CandidateTx[]>()
  for (const tx of transactions) {
    if (!tx.amount.startsWith('-') || tx.source === 'loan' || tx.splits?.length) continue
    const list = groups.get(keyOf(tx)) ?? []
    list.push(tx)
    groups.set(keyOf(tx), list)
  }
  const result: Candidate[] = []
  for (const [key, list] of groups) {
    const latest = list.reduce((a, b) => (b.booking_date > a.booking_date || (b.booking_date === a.booking_date && b.id > a.id) ? b : a))
    const label = (latest.counterparty?.trim() || latest.description.trim()).replace(/\s+/g, ' ')
    const haystack = normalize(`${latest.counterparty ?? ''} ${latest.description}`)
    if (taken.some((t) => haystack.includes(t)) || sameAsExisting(latest)) continue
    const months = new Set(list.map((t) => t.booking_date.slice(0, 7))).size
    const interval = detectInterval(list, months)
    result.push({
      key,
      latest,
      name: label.slice(0, 100),
      amount: latest.amount.replace(/^-/, ''),
      dueDay: Number(latest.booking_date.slice(8, 10)),
      matchText: latest.counterparty?.trim() ? latest.counterparty.trim().replace(/\s+/g, ' ').slice(0, 100) : '',
      months,
      count: list.length,
      monthly: interval === 'monthly',
      interval,
      monthlyAmount: perMonth(latest.amount, interval),
    })
  }
  return result.sort((a, b) =>
    Number(b.monthly) - Number(a.monthly) || (a.monthly && b.months - a.months)
    || (b.latest.booking_date > a.latest.booking_date ? 1 : b.latest.booking_date < a.latest.booking_date ? -1 : 0))
}

/** Freitextsuche über Name und Verwendungszweck. */
export function filterCandidates(candidates: Candidate[], search: string): Candidate[] {
  const needle = normalize(search)
  if (!needle) return candidates
  return candidates.filter((c) => normalize(`${c.name} ${c.latest.description}`).includes(needle))
}
