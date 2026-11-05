import { describe, expect, it } from 'vitest'
import { draftFromParsed } from './entryParse'

const base = {
  amount: '-12.50', booking_date: '2026-11-04', account_id: 3, category_id: 7, description: 'Rewe',
  questions: [], possible_duplicate: null, ai_used: true,
}

describe('draftFromParsed', () => {
  it('Ausgabe: Betrag ohne Vorzeichen', () => {
    const d = draftFromParsed(base)
    expect(d).toMatchObject({ mode: 'expense', amount: '12.50', date: '2026-11-04', accountId: '3', categoryId: 7, text: 'Rewe' })
    expect(d.missing).toEqual([])
  })
  it('Einnahme bei positivem Betrag', () => {
    expect(draftFromParsed({ ...base, amount: '1500.00' })).toMatchObject({ mode: 'income', amount: '1500.00' })
  })
  it('Zahl als Betrag', () => {
    expect(draftFromParsed({ ...base, amount: -3 }).amount).toBe('3')
  })
  it('fehlende Angaben bleiben leer und werden gemeldet', () => {
    const d = draftFromParsed({ ...base, amount: null, booking_date: null, account_id: null, questions: ['amount', 'date', 'account'] })
    expect(d.mode).toBeNull()
    expect(d.amount).toBeNull()
    expect(d.date).toBeNull()
    expect(d.accountId).toBeNull()
    expect(d.missing).toEqual(['amount', 'date', 'account'])
  })
  it('ignoriert unbekannte Fragen', () => {
    expect(draftFromParsed({ ...base, questions: ['amount', 'zzz'] }).missing).toEqual(['amount'])
  })
})
