import { describe, expect, it } from 'vitest'
import { aliasesFromCounterparty, parseAiHint } from './merchants'

describe('aliasesFromCounterparty', () => {
  it('liefert IBAN (ohne Leerzeichen) und Namen', () => {
    expect(aliasesFromCounterparty('Netflix', 'DE89 3704 0044 0532 0130 00')).toEqual([
      { match_type: 'iban', value: 'DE89370400440532013000' },
      { match_type: 'name', value: 'Netflix' },
    ])
  })
  it('lässt fehlende IBAN weg', () => {
    expect(aliasesFromCounterparty(' Netflix ', null)).toEqual([{ match_type: 'name', value: 'Netflix' }])
  })
  it('leer bei fehlender Gegenpartei', () => {
    expect(aliasesFromCounterparty('  ', null)).toEqual([])
  })
})

describe('parseAiHint', () => {
  it('null ohne ai-Block', () => {
    expect(parseAiHint({})).toBeNull()
    expect(parseAiHint({ ai: 'x' })).toBeNull()
  })
  it('liest Anbieter und Verpflichtung', () => {
    expect(parseAiHint({ ai: { anbieter: 'Netflix', ist_verpflichtung: false } }))
      .toEqual({ provider: 'Netflix', obligation: false })
  })
  it('unbekannte Verpflichtung bleibt null', () => {
    expect(parseAiHint({ ai: {} })).toEqual({ provider: null, obligation: null })
  })
})
