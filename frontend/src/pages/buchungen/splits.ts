import { fromCents, toCents } from '../../lib/moneyInput'

/** Eine Zeile beim Aufteilen: Betrag mit gleichem Vorzeichen wie die Buchung. */
export interface SplitDraft {
  amount: string | null // Betrag als positiver Dezimalstring (Vorzeichen kommt von der Buchung)
  categoryId: number | null
  transfer: boolean
}

/** Rest, der noch zu verteilen ist (positiv = fehlt noch, negativ = zu viel), als Dezimalstring. */
export function splitRemainder(total: string, drafts: SplitDraft[]): string {
  const target = toCents(total.replace('-', ''))
  const used = drafts.reduce((sum, d) => sum + (d.amount ? toCents(d.amount) : 0n), 0n)
  return fromCents(target - used)
}

export type SplitProblem = 'too_few' | 'missing_amount' | 'missing_category' | 'sum' | null

export function splitProblem(total: string, drafts: SplitDraft[]): SplitProblem {
  if (drafts.length < 2) return 'too_few'
  if (drafts.some((d) => !d.amount || toCents(d.amount) <= 0n)) return 'missing_amount'
  if (drafts.some((d) => !d.transfer && !d.categoryId)) return 'missing_category'
  if (splitRemainder(total, drafts) !== '0.00') return 'sum'
  return null
}

/** Entwürfe → API-Splits mit dem Vorzeichen der Buchung. */
export function toApiSplits(total: string, drafts: SplitDraft[]) {
  const negative = total.startsWith('-')
  return drafts.map((d) => ({
    amount: negative ? `-${d.amount}` : d.amount!,
    kind: d.transfer ? 'transfer' : 'regular',
    category_id: d.transfer ? null : d.categoryId,
  }))
}

export const SPLIT_PROBLEM_TEXT: Record<Exclude<SplitProblem, null>, string> = {
  too_few: 'Eine Aufteilung braucht mindestens zwei Zeilen.',
  missing_amount: 'Jede Zeile braucht einen Betrag.',
  missing_category: 'Jede Zeile braucht eine Kategorie (oder „Umbuchung“).',
  sum: 'Die Zeilen müssen zusammen den Betrag der Buchung ergeben.',
}
