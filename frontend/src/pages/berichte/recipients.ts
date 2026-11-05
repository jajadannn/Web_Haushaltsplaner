import { toCents } from '../../lib/moneyInput'

export interface RecipientTx {
  amount: string
  counterparty: string | null
  description: string
  category_id: number | null
  splits?: { amount: string; kind: string; category_id: number | null }[]
}

/**
 * Größte Empfänger einer Kategorie: je Buchung zählen nur die regulären Splitanteile,
 * deren Kategorie zur gewählten (inkl. Unterkategorien) gehört – nicht der volle
 * Buchungsbetrag. Ohne Splits gilt der Buchungsbetrag, falls die Kategorie passt.
 * Ausgaben werden positiv ausgewiesen; Erstattungen mindern den Empfänger.
 */
export function topRecipients(
  txs: RecipientTx[],
  categoryIds: ReadonlySet<number>,
  type: 'expense' | 'income',
  limit = 5,
): [string, bigint][] {
  const sums = new Map<string, bigint>()
  for (const t of txs) {
    const parts = t.splits?.length
      ? t.splits.filter((s) => s.kind !== 'transfer' && s.category_id !== null && categoryIds.has(s.category_id))
      : t.category_id !== null && categoryIds.has(t.category_id) ? [t] : []
    if (parts.length === 0) continue
    const name = t.counterparty || t.description
    let value = 0n
    for (const p of parts) value += type === 'expense' ? -toCents(p.amount) : toCents(p.amount)
    sums.set(name, (sums.get(name) ?? 0n) + value)
  }
  return [...sums.entries()].filter(([, v]) => v > 0n).sort((a, b) => Number(b[1] - a[1])).slice(0, limit)
}
