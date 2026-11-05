import { describe, expect, it } from 'vitest'
import { assignmentFromColumnMap, columnMapFromAssignment, isUncertainColumn, ROLE_LABELS } from './importDraft'

const header = ['Datum', 'Betrag', 'Zweck', 'Text', 'Name', 'Notiz']

describe('assignmentFromColumnMap', () => {
  it('kehrt Rolle→Spalte zu Spalte→Rolle um', () => {
    const a = assignmentFromColumnMap({ booking_date: 'Datum', amount: 'Betrag', counterparty: 'Name' }, header)
    expect(a).toEqual({ Datum: 'booking_date', Betrag: 'amount', Name: 'counterparty' })
  })
  it('verteilt Listen auf mehrere Spalten derselben Rolle', () => {
    const a = assignmentFromColumnMap({ description: ['Zweck', 'Text'] }, header)
    expect(a).toEqual({ Zweck: 'description', Text: 'description' })
  })
  it('ignoriert Sonderformen und unbekannte Spalten', () => {
    const a = assignmentFromColumnMap({ counterparty: { debit: 'Name', credit: 'Zweck' }, amount: 'Gibtsnicht' }, header)
    expect(a).toEqual({})
  })
})

describe('columnMapFromAssignment', () => {
  it('baut die column_map in Spaltenreihenfolge', () => {
    const m = columnMapFromAssignment({ Betrag: 'amount', Datum: 'booking_date', Name: 'counterparty' }, header, {})
    expect(m).toEqual({ booking_date: 'Datum', amount: 'Betrag', counterparty: 'Name' })
  })
  it('fasst mehrere Beschreibungsspalten zur Liste zusammen', () => {
    const m = columnMapFromAssignment({ Zweck: 'description', Text: 'description' }, header, {})
    expect(m.description).toEqual(['Zweck', 'Text'])
  })
  it('nimmt bei anderen Rollen nur die erste Spalte', () => {
    const m = columnMapFromAssignment({ Datum: 'booking_date', Notiz: 'booking_date' }, header, {})
    expect(m.booking_date).toBe('Datum')
  })
  it('lässt Spalten ohne Rolle weg', () => {
    expect(columnMapFromAssignment({ Datum: '' }, header, {})).toEqual({})
  })
  it('behält Sonderformen, solange die Rolle nicht neu vergeben wird', () => {
    const prev = { counterparty: { debit: 'Name', credit: 'Zweck' } }
    expect(columnMapFromAssignment({ Datum: 'booking_date' }, header, prev).counterparty).toEqual(prev.counterparty)
    expect(columnMapFromAssignment({ Notiz: 'counterparty' }, header, prev).counterparty).toBe('Notiz')
  })
})

describe('isUncertainColumn', () => {
  it('markiert Spalten, deren Rolle unsicher ist', () => {
    const map = { booking_date: 'Datum', amount: 'Betrag' }
    expect(isUncertainColumn('Datum', map, ['booking_date'])).toBe(true)
    expect(isUncertainColumn('Datum', map, ['date_format'])).toBe(true)
    expect(isUncertainColumn('Betrag', map, ['booking_date'])).toBe(false)
    expect(isUncertainColumn('Notiz', map, ['amount'])).toBe(false)
  })
})

describe('ROLE_LABELS', () => {
  it('hat deutsche Namen', () => {
    expect(ROLE_LABELS.booking_date).toBe('Buchungsdatum')
  })
})
