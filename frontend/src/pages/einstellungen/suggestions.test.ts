import { describe, expect, it } from 'vitest'
import {
  intervalLabel, parseEvidence, parseFixedCostPayload, sortSuggestions, statusNote,
} from './suggestions'

describe('intervalLabel', () => {
  it('benennt die Rhythmen', () => {
    expect(intervalLabel(1)).toBe('monatlich')
    expect(intervalLabel(3)).toBe('vierteljährlich')
    expect(intervalLabel(6)).toBe('halbjährlich')
    expect(intervalLabel(12)).toBe('jährlich')
    expect(intervalLabel(2)).toBe('alle 2 Monate')
  })
})

describe('parseFixedCostPayload', () => {
  it('liest vollständige Werte', () => {
    const p = parseFixedCostPayload({
      name: 'Hausrat', amount: '90.00', interval_months: 12, due_day: 15,
      first_due_date: '2027-01-15', category_id: 4, account_id: 2, match_text: 'Allianz',
    })
    expect(p).toEqual({
      name: 'Hausrat', amount: '90.00', intervalMonths: 12, dueDay: 15,
      firstDueDate: '2027-01-15', categoryId: 4, accountId: 2, matchText: 'Allianz',
    })
  })
  it('füllt fehlende Werte mit Vorgaben', () => {
    const p = parseFixedCostPayload({})
    expect(p.intervalMonths).toBe(1)
    expect(p.dueDay).toBe(1)
    expect(p.firstDueDate).toBeNull()
    expect(p.name).toBe('')
    expect(p.amount).toBeNull()
  })
  it('wandelt Zahlenbeträge in Text', () => {
    expect(parseFixedCostPayload({ amount: 12.5 }).amount).toBe('12.5')
  })
})

describe('parseEvidence', () => {
  it('liefert Belegbuchungen und Betragsflag', () => {
    const e = parseEvidence({ transactions: [{ id: 1, split_id: null, date: '2026-10-01', amount: '-9.99' }], identical_amount: true })
    expect(e.transactions).toHaveLength(1)
    expect(e.identicalAmount).toBe(true)
  })
  it('kommt mit fehlenden Daten klar', () => {
    expect(parseEvidence({}).transactions).toEqual([])
    expect(parseEvidence({ transactions: 'x' }).transactions).toEqual([])
  })
})

describe('sortSuggestions', () => {
  it('zeigt offene vor Probelauf vor dem Rest, dann nach Priorität', () => {
    const mk = (id: number, status: string, priority: number) => ({ id, status, priority })
    const sorted = sortSuggestions([mk(1, 'auto_applied', 9), mk(2, 'dry_run', 5), mk(3, 'open', 1), mk(4, 'open', 7)])
    expect(sorted.map((s) => s.id)).toEqual([4, 3, 2, 1])
  })
})

describe('statusNote', () => {
  it('erklärt Probelauf und Automatik', () => {
    expect(statusNote('dry_run')).toBe('wäre automatisch angelegt worden')
    expect(statusNote('auto_applied')).toMatch(/automatisch angelegt/)
    expect(statusNote('open')).toBeNull()
  })
})

import { parseAnnualCost, parseIncomeSeries, parseUnusual, parseMissingPayment } from './suggestions'

describe('parseIncomeSeries', () => {
  it('liest Einnahmenserie mit Spanne', () => {
    const p = parseIncomeSeries({
      name: 'Gehalt', amount: '2900.00', amount_min: '2800.00', amount_max: '3000.00', interval_months: 1,
      due_day: 28, first_due_date: '2026-11-28', account_id: 1, category_id: 9, match_text: 'ACME',
    })
    expect(p).toMatchObject({ name: 'Gehalt', amount: '2900.00', amountMin: '2800.00', amountMax: '3000.00', intervalMonths: 1, dueDay: 28, accountId: 1, categoryId: 9, matchText: 'ACME' })
  })
  it('Vorgaben bei leerem Payload', () => {
    expect(parseIncomeSeries({})).toMatchObject({ name: '', amount: null, amountMin: null, intervalMonths: 1, dueDay: 1 })
  })
})

describe('parseAnnualCost', () => {
  it('liest Jahresposten', () => {
    const p = parseAnnualCost({ name: 'KFZ-Steuer', amount: 250, interval_months: 12, due_day: 3, first_due_date: '2027-03-03', expected_date: '2027-03-03' })
    expect(p).toMatchObject({ name: 'KFZ-Steuer', amount: '250', dueDay: 3, expectedDate: '2027-03-03' })
  })
})

describe('parseUnusual / parseMissingPayment', () => {
  it('Dopplung und hohe Zahlung', () => {
    expect(parseUnusual({ type: 'duplicate', name: 'Strom', month: '2026-10-01', amount: '80.00' })).toMatchObject({ type: 'duplicate', name: 'Strom' })
    expect(parseUnusual({ type: 'high', name: 'Strom', amount: '80.00', paid_amount: '160.00' }).paidAmount).toBe('160.00')
    expect(parseUnusual({ type: 'weird' }).type).toBe('high')
  })
  it('fehlende Zahlung', () => {
    expect(parseMissingPayment({ fixed_cost_id: 2, name: 'Miete', amount: '700.00', due_date: '2026-11-01', month: '2026-11-01' }))
      .toMatchObject({ fixedCostId: 2, name: 'Miete', dueDate: '2026-11-01' })
  })
})
