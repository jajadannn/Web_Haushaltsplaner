import { describe, expect, it } from 'vitest'
import { loanProgress } from './loanProgress'

type P = Parameters<typeof loanProgress>[0]
const loan = (o: Partial<P>) => ({ principal_original: null, principal_repaid: '0.00', remaining_debt: '1000.00', ...o }) as P

describe('loanProgress', () => {
  it('nutzt die tatsächlich gezahlte Tilgung statt Planwerte (S5)', () => {
    expect(loanProgress(loan({ principal_repaid: '240.00', remaining_debt: '760.00' }))).toBeCloseTo(0.24)
  })
  it('nimmt die ursprüngliche Summe als Gesamt, falls vorhanden', () => {
    expect(loanProgress(loan({ principal_original: '2000.00', principal_repaid: '500.00', remaining_debt: '1000.00' }))).toBeCloseTo(0.25)
  })
  it('liefert 0 ohne Zahlungen', () => {
    expect(loanProgress(loan({}))).toBe(0)
  })
  it('fängt Division durch 0 ab', () => {
    expect(loanProgress(loan({ principal_repaid: '0.00', remaining_debt: '0.00' }))).toBeNull()
    expect(loanProgress(loan({ principal_original: '0.00' }))).toBeNull()
  })
  it('begrenzt auf 0 bis 1', () => {
    expect(loanProgress(loan({ principal_original: '100.00', principal_repaid: '300.00' }))).toBe(1)
    expect(loanProgress(loan({ principal_repaid: '-50.00', remaining_debt: '100.00' }))).toBe(0)
  })
})
