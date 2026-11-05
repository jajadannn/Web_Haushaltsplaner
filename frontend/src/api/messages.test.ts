import { describe, expect, it } from 'vitest'
import { fieldErrors, messageFor } from './messages'

const GENERIC_500 = 'Im Finanzplaner ist ein Fehler aufgetreten. Bitte noch einmal versuchen.'

describe('messageFor', () => {
  it('network ist generisch', () => {
    expect(messageFor('network')).toContain('Keine Verbindung')
    expect(messageFor('network', 'x')).toContain('Keine Verbindung')
  })
  it('fachliche Servertexte bleiben', () => {
    expect(messageFor('category_in_use', 'Kategorie wird verwendet')).toBe('Kategorie wird verwendet')
  })
  it('http_500 ignoriert Servertext', () => {
    expect(messageFor('http_500', 'x')).toBe(GENERIC_500)
  })
  it('neue Codes haben einen deutschen Ersatztext', () => {
    for (const code of ['suggestion_not_open', 'suggestion_stale', 'changed_since', 'payment_already_linked', 'due_month_already_paid', 'payment_not_linkable']) {
      expect(messageFor(code)).not.toBe('Das hat nicht geklappt.')
    }
  })
  it('unbekannter Code ohne Text', () => {
    expect(messageFor('whatever')).toBe('Das hat nicht geklappt.')
  })
  it('validation_error: ein Feld', () => {
    expect(messageFor('validation_error', 's', [{ loc: ['body', 'amount'], msg: '..' }])).toBe('Bitte „Betrag“ prüfen.')
  })
  it('validation_error: mehrere Felder', () => {
    const d = [{ loc: ['body', 'amount'] }, { loc: ['body', 'booking_date'] }]
    expect(messageFor('validation_error', 's', d)).toBe('Bitte diese Felder prüfen: „Betrag“, „Datum“.')
  })
  it('unbekanntes Feld nutzt Rohnamen', () => {
    expect(messageFor('validation_error', 's', [{ loc: ['body', 'foo_bar'] }])).toBe('Bitte „foo_bar“ prüfen.')
  })
  it('leere Details → Servertext', () => {
    expect(messageFor('validation_error', 'Server sagt nein', [])).toBe('Server sagt nein')
  })
})

describe('fieldErrors', () => {
  it('ordnet loc den Feldnamen zu', () => {
    expect(fieldErrors([{ loc: ['body', 'amount'] }, { loc: ['query', 'name'] }])).toEqual({
      amount: 'Bitte prüfen', name: 'Bitte prüfen',
    })
  })
  it('ignoriert Nicht-Arrays', () => {
    expect(fieldErrors(null)).toEqual({})
  })
})
