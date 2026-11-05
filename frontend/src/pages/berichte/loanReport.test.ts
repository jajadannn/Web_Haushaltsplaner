import { describe, expect, it } from 'vitest'
import { currentStateNote, interestBreakdown } from './loanReport'

describe('currentStateNote', () => {
  it('kennzeichnet den aktuellen Stand, wenn der Zeitraum in der Vergangenheit liegt', () => {
    expect(currentStateNote('2026-01-31', '2026-11-05')).toBe('aktueller Stand (05.11.2026)')
  })
  it('bleibt leer, wenn der Zeitraum bis heute reicht', () => {
    expect(currentStateNote('2026-11-30', '2026-11-05')).toBeNull()
    expect(currentStateNote('2026-11-05', '2026-11-05')).toBeNull()
  })
})

describe('interestBreakdown', () => {
  it('trennt gezahlte und der Schuld zugeschlagene Zinsen', () => {
    expect(interestBreakdown({ year: 2026, interest: '20.00', paid: '0.00', charged: '20.00' }))
      .toEqual({ year: 2026, total: '20.00', paid: null, charged: '20.00' })
    expect(interestBreakdown({ year: 2025, interest: '30.00', paid: '30.00', charged: '0.00' }))
      .toEqual({ year: 2025, total: '30.00', paid: '30.00', charged: null })
  })
})
