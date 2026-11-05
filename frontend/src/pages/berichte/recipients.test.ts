import { describe, expect, it } from 'vitest'
import { topRecipients, type RecipientTx } from './recipients'

const tx = (amount: string, counterparty: string, splits: RecipientTx['splits'], category_id: number | null = null): RecipientTx =>
  ({ amount, counterparty, description: 'x', category_id, splits })

describe('topRecipients', () => {
  it('summiert nur den Splitanteil der gewählten Kategorie', () => {
    const t = tx('-12.50', 'Markt', [
      { amount: '-8.00', kind: 'regular', category_id: 1 },
      { amount: '-4.50', kind: 'regular', category_id: 2 },
    ])
    expect(topRecipients([t], new Set([1]), 'expense')).toEqual([['Markt', 800n]])
    expect(topRecipients([t], new Set([2]), 'expense')).toEqual([['Markt', 450n]])
  })

  it('zählt Unterkategorien mit und ignoriert Transferanteile', () => {
    const t = tx('-20.00', 'Shop', [
      { amount: '-5.00', kind: 'regular', category_id: 1 },
      { amount: '-7.00', kind: 'regular', category_id: 3 },
      { amount: '-8.00', kind: 'transfer', category_id: 1 },
    ])
    expect(topRecipients([t], new Set([1, 3]), 'expense')).toEqual([['Shop', 1200n]])
  })

  it('nutzt ohne Splits den Buchungsbetrag, wenn die Kategorie passt', () => {
    const a = tx('-9.00', 'A', [], 1)
    const b = tx('-9.00', 'B', [], 2)
    expect(topRecipients([a, b], new Set([1]), 'expense')).toEqual([['A', 900n]])
  })

  it('Einnahmen positiv, Erstattungen mindern, Top 5 absteigend', () => {
    const list = ['a', 'b', 'c', 'd', 'e', 'f'].map((n, i) => tx(String(10 + i), n, [], 1))
    const res = topRecipients(list, new Set([1]), 'income')
    expect(res.map((r) => r[0])).toEqual(['f', 'e', 'd', 'c', 'b'])
    const refunded = [tx('-10.00', 'X', [], 1), tx('3.00', 'X', [], 1)]
    expect(topRecipients(refunded, new Set([1]), 'expense')).toEqual([['X', 700n]])
  })
})
