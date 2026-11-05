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
