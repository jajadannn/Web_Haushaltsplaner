import { describe, expect, it } from 'vitest'
import { filterCandidates, fixedCostCandidates, type CandidateTx } from './fixedCostCandidates'

let id = 0
const tx = (booking_date: string, amount: string, counterparty: string | null, description = 'Lastschrift', category_id: number | null = null): CandidateTx =>
  ({ id: ++id, booking_date, amount, counterparty, description, category_id })

describe('fixedCostCandidates', () => {
  const data = [
    tx('2026-09-03', '-45.00', 'Stadtwerke Musterhausen', 'Abschlag Strom', 7),
    tx('2026-10-03', '-45.00', 'Stadtwerke  musterhausen', 'Abschlag Strom', 7),
    tx('2026-11-03', '-48.00', 'Stadtwerke Musterhausen', 'Abschlag Strom', 7),
    tx('2026-11-01', '-12.99', 'NETFLIX', 'Abo'),
    tx('2026-10-01', '-12.99', 'NETFLIX', 'Abo'),
    tx('2026-11-02', '-54.23', 'ARAL STATION', 'Kartenzahlung'),
    tx('2026-10-12', '-31.10', 'EDEKA', 'Kartenzahlung', 3),
    tx('2026-10-20', '-12.40', 'EDEKA', 'Kartenzahlung', 3),
    tx('2026-11-05', '-48.75', 'EDEKA', 'Kartenzahlung', 3),
    tx('2026-10-01', '-850.00', 'Hausverwaltung', 'Miete', 9),
    tx('2026-11-01', '-850.00', 'Hausverwaltung', 'Miete', 9),
    tx('2026-11-02', '2500.00', 'Arbeitgeber', 'Gehalt'),
    tx('2026-11-04', '-9.80', null, 'PayPal Europe Zahlung'),
  ]

  it('eine Zeile je Empfänger, monatliche zuerst, Einnahmen nicht', () => {
    const result = fixedCostCandidates(data)
    expect(result.map((c) => [c.name, c.months, c.monthly])).toEqual([
      ['Stadtwerke Musterhausen', 3, true], // 45 → 48 €: innerhalb der Toleranz
      ['NETFLIX', 2, true],
      ['Hausverwaltung', 2, true],
      ['EDEKA', 2, false], // mehrmals im Monat, schwankende Beträge
      ['PayPal Europe Zahlung', 1, false],
      ['ARAL STATION', 1, false],
    ])
  })

  it('lässt Buchungen weg, die Betrag und Kategorie einer Fixkost haben', () => {
    const names = fixedCostCandidates(data, [{ match_text: null, amount: '850.00', category_id: 9 }]).map((c) => c.name)
    expect(names).not.toContain('Hausverwaltung')
    expect(fixedCostCandidates(data, [{ match_text: null, amount: '850.00', category_id: null }]).map((c) => c.name))
      .toContain('Hausverwaltung')
  })

  it('belegt aus der jüngsten Buchung vor', () => {
    const [strom] = fixedCostCandidates(data)
    expect(strom).toMatchObject({ amount: '48.00', dueDay: 3, matchText: 'Stadtwerke Musterhausen', count: 3 })
    expect(strom.latest.category_id).toBe(7)
  })

  it('lässt Kreditraten weg', () => {
    const rate = { ...tx('2026-10-30', '-234.98', 'Autobank', 'Rate 12'), splits: [{}, {}] }
    const loanTx = { ...tx('2026-10-30', '-5.00', 'Autobank Gebühr', 'Gebühr'), source: 'loan' }
    expect(fixedCostCandidates([...data, rate, loanTx]).map((c) => c.name)).not.toContain('Autobank')
    expect(fixedCostCandidates([...data, rate, loanTx]).map((c) => c.name)).not.toContain('Autobank Gebühr')
  })

  it('ohne Empfänger kein Erkennungstext', () => {
    const paypal = fixedCostCandidates(data).find((c) => c.name.startsWith('PayPal'))
    expect(paypal?.matchText).toBe('')
  })

  it('lässt bereits erfasste Fixkosten weg', () => {
    const names = fixedCostCandidates(data, [
      { match_text: 'stadtwerke', amount: '1.00', category_id: null },
      { match_text: '', amount: '2.00', category_id: null },
    ]).map((c) => c.name)
    expect(names).not.toContain('Stadtwerke Musterhausen')
    expect(names).toContain('NETFLIX')
  })

  it('sucht in Name und Verwendungszweck', () => {
    const all = fixedCostCandidates(data)
    expect(filterCandidates(all, 'strom').map((c) => c.name)).toEqual(['Stadtwerke Musterhausen'])
    expect(filterCandidates(all, '  ').length).toBe(all.length)
  })

  describe('Intervall', () => {
    it('Quartalszahlungen sind nicht monatlich und werden auf den Monat umgerechnet', () => {
      const [q] = fixedCostCandidates([
        tx('2026-07-15', '-90.00', 'Versicherung Quartal'),
        tx('2026-10-15', '-90.00', 'Versicherung Quartal'),
      ])
      expect(q.monthly).toBe(false)
      expect(q.interval).toBe('quarterly')
      expect(q.amount).toBe('90.00')
      expect(q.monthlyAmount).toBe('30.00')
    })

    it('jährliche Zahlung: Zwölftel als Monatsbetrag', () => {
      const [y] = fixedCostCandidates([
        tx('2025-03-10', '-120.00', 'KFZ Steuer'),
        tx('2026-03-10', '-120.00', 'KFZ Steuer'),
      ])
      expect(y.interval).toBe('yearly')
      expect(y.monthlyAmount).toBe('10.00')
    })

    it('Monate mit Lücke sind unregelmäßig, nicht monatlich', () => {
      const [g] = fixedCostCandidates([
        tx('2026-07-15', '-20.00', 'Lücke'),
        tx('2026-08-15', '-20.00', 'Lücke'),
        tx('2026-11-15', '-20.00', 'Lücke'),
      ])
      expect(g.monthly).toBe(false)
      expect(g.interval).toBe('irregular')
    })

    it('aufeinanderfolgende Monate mit Abstand von rund einem Monat sind monatlich', () => {
      const [m] = fixedCostCandidates([
        tx('2026-09-15', '-20.00', 'Abo'),
        tx('2026-10-15', '-20.00', 'Abo'),
      ])
      expect(m).toMatchObject({ monthly: true, interval: 'monthly', monthlyAmount: '20.00' })
    })

    it('Monatsletzter und Monatsanfang hintereinander sind kein Monatsabstand', () => {
      const [m] = fixedCostCandidates([
        tx('2026-09-01', '-20.00', 'Nah'),
        tx('2026-10-31', '-20.00', 'Nah'),
      ])
      expect(m.monthly).toBe(false)
    })
  })
})
