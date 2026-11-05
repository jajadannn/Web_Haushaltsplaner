import { fromCents, toCents } from '../../lib/moneyInput'

export interface TotalsLine {
  amount: string
  kind: string
  category_id: number | null
}

export interface TotalsTx {
  amount: string
  kind: string
  category_id: number | null
  excluded_at: string | null
  splits: TotalsLine[]
}

export interface Totals {
  income: string
  expenses: string
  /** Zuflüsse ohne Kategorie – weder Einnahme noch Erstattung bekannt */
  unclearInflow: string
}

/**
 * Einnahmen/Ausgaben der Liste, wie das Backend rechnet: Die Kategorie entscheidet,
 * nicht das Vorzeichen. Eine Erstattung in einer Ausgabenkategorie mindert die Ausgaben.
 * Umbuchungen und ausgeschlossene Buchungen zählen nicht; Splits zählen je Zeile.
 */
export function computeTotals(
  items: TotalsTx[],
  categoryType: (id: number | null) => 'income' | 'expense' | undefined,
): Totals {
  let income = 0n
  let expenses = 0n
  let unclear = 0n
  for (const t of items) {
    if (t.excluded_at) continue
    const lines: TotalsLine[] = t.splits.length ? t.splits : [{ amount: t.amount, kind: t.kind, category_id: t.category_id }]
    for (const line of lines) {
      if (line.kind === 'transfer') continue
      const cents = toCents(line.amount)
      const type = categoryType(line.category_id)
      if (type === 'income') income += cents
      else if (type === 'expense') expenses -= cents
      else if (cents < 0n) expenses -= cents
      else unclear += cents
    }
  }
  return { income: fromCents(income), expenses: fromCents(expenses), unclearInflow: fromCents(unclear) }
}
