/**
 * Fixkosten aus den letzten Buchungen vorschlagen: eine Zeile je Empfänger. „Monatlich“
 * (typische Fixkost) heißt: in mindestens zwei Monaten, etwa einmal pro Monat und in
 * ähnlicher Höhe – Supermarkt oder Tankstelle sind das nicht. Monatliche zuerst.
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

function isMonthly(list: CandidateTx[], months: number): boolean {
  if (months < 2 || list.length > months + 1) return false
  const values = list.map((t) => cents(t.amount))
  const max = Math.max(...values)
  return max > 0 && (max - Math.min(...values)) / max <= AMOUNT_TOLERANCE
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
    result.push({
      key,
      latest,
      name: label.slice(0, 100),
      amount: latest.amount.replace(/^-/, ''),
      dueDay: Number(latest.booking_date.slice(8, 10)),
      matchText: latest.counterparty?.trim() ? latest.counterparty.trim().replace(/\s+/g, ' ').slice(0, 100) : '',
      months,
      count: list.length,
      monthly: isMonthly(list, months),
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
