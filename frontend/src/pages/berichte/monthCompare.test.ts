import { describe, expect, it } from 'vitest'
import { askPeriodText, deltaText, deltaTone, mainCategories, toolLabel, transactionLink } from './monthCompare'

describe('deltaText', () => {
  it('zeigt mehr, weniger und unverändert', () => {
    expect(deltaText('120.00')).toBe('+120,00\u00a0€ mehr')
    expect(deltaText('-30.50')).toBe('\u221230,50\u00a0€ weniger')
    expect(deltaText('0.00')).toBe('unverändert')
  })
})

describe('deltaTone', () => {
  it('mehr Ausgaben sind ungünstig', () => {
    expect(deltaTone('10.00')).toBe('worse')
    expect(deltaTone('-10.00')).toBe('better')
    expect(deltaTone('0.00')).toBe('same')
  })
})

describe('mainCategories', () => {
  const cat = (name: string, delta: string, current = '10.00') =>
    ({ category_id: 1, name, current, previous: '0.00', average_3: '0.00', delta })
  it('sortiert nach größter Abweichung und kürzt', () => {
    const out = mainCategories([cat('a', '5.00'), cat('b', '-50.00'), cat('c', '20.00'), cat('d', '0.00', '0.00')], 2)
    expect(out.map((c) => c.name)).toEqual(['b', 'c'])
  })
  it('lässt leere Kategorien weg', () => {
    expect(mainCategories([cat('x', '0.00', '0.00')], 5)).toEqual([])
  })
})

describe('Antwortkarte', () => {
  it('schreibt den Zeitraum aus', () => {
    expect(askPeriodText({ from: '2026-10-01', to: '2026-10-31' })).toBe('01.10.2026 – 31.10.2026')
    expect(askPeriodText(null)).toBeNull()
  })
  it('benennt Werkzeuge, unbekannte bleiben lesbar', () => {
    expect(toolLabel('sum_by_category')).not.toBe('sum_by_category')
    expect(toolLabel('foo_bar')).toBe('foo bar')
  })
  it('verlinkt Belege in die Buchungsliste', () => {
    expect(transactionLink(42)).toBe('/buchungen?id=42')
  })
})
