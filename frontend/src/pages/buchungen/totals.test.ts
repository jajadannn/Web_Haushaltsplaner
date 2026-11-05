import { describe, expect, it } from 'vitest'
import { computeTotals, type TotalsTx } from './totals'

const types: Record<number, 'income' | 'expense'> = { 1: 'expense', 2: 'income' }
const type = (id: number | null) => (id ? types[id] : undefined)
const tx = (amount: string, category_id: number | null, extra: Partial<TotalsTx> = {}): TotalsTx => ({
  amount, category_id, kind: 'regular', excluded_at: null, splits: [], ...extra,
})

describe('computeTotals', () => {
  it('Erstattung mindert die Ausgaben der Kategorie', () => {
    const t = computeTotals([tx('-100.00', 1), tx('30.00', 1)], type)
    expect(t).toEqual({ income: '0.00', expenses: '70.00', unclearInflow: '0.00' })
  })
  it('Einnahmenkategorie zählt als Einnahme', () => {
    expect(computeTotals([tx('1200.00', 2)], type).income).toBe('1200.00')
  })
  it('Umbuchung und Ausgeschlossene zählen nicht', () => {
    const t = computeTotals([tx('-50.00', null, { kind: 'transfer' }), tx('-9.00', 1, { excluded_at: '2026-11-01T00:00:00Z' })], type)
    expect(t).toEqual({ income: '0.00', expenses: '0.00', unclearInflow: '0.00' })
  })
  it('unkategorisierter Abfluss ist Ausgabe, Zufluss ungeklärt', () => {
    const t = computeTotals([tx('-20.00', null), tx('15.00', null)], type)
    expect(t).toEqual({ income: '0.00', expenses: '20.00', unclearInflow: '15.00' })
  })
  it('Splits werden einzeln nach Kategorie und Art gezählt', () => {
    const t = computeTotals([tx('-100.00', null, { splits: [
      { amount: '-60.00', kind: 'regular', category_id: 1 },
      { amount: '-40.00', kind: 'transfer', category_id: null },
    ] })], type)
    expect(t.expenses).toBe('60.00')
  })
})
