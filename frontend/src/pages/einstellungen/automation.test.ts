import { describe, expect, it } from 'vitest'
import { changeSummary, changedSettings, rateLabel } from './automation'

describe('changedSettings', () => {
  it('liefert nur geänderte Schlüssel', () => {
    expect(changedSettings({ a: 'x', b: 1, c: true }, { a: 'x', b: 2, c: true })).toEqual({ b: 2 })
  })
  it('leer, wenn nichts geändert', () => {
    expect(changedSettings({ a: 1 }, { a: 1 })).toEqual({})
  })
})

describe('rateLabel', () => {
  it('formatiert Quoten als Prozent', () => {
    expect(rateLabel(0.5)).toBe('50 %')
    expect(rateLabel(0.333)).toBe('33 %')
    expect(rateLabel(null)).toBe('–')
  })
})

describe('changeSummary', () => {
  it('nennt Objekt, Aktion und Namen', () => {
    expect(changeSummary({ object_type: 'fixed_cost', action: 'create', before: null, after: { name: 'Strom' } }))
      .toBe('Fixkost angelegt: Strom')
  })
  it('nimmt bei Löschung den Namen aus before', () => {
    expect(changeSummary({ object_type: 'mapping_rule', action: 'delete', before: { name: 'Rewe' }, after: null }))
      .toBe('Regel gelöscht: Rewe')
  })
  it('fällt bei Unbekanntem auf die Rohwerte zurück', () => {
    expect(changeSummary({ object_type: 'foo', action: 'bar', before: null, after: null })).toBe('foo bar')
  })
})
