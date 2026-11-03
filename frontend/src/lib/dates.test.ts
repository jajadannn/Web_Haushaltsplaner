import { describe, expect, it } from 'vitest'
import { daysInMonth, daysLeftLabel, monthLabel, parseDate, shortMonthLabel, standLabel } from './dates'

describe('dates', () => {
  it('parseDate', () => {
    expect(parseDate('2026-11-03')).toEqual({ year: 2026, month: 11, day: 3 })
    expect(() => parseDate('2026-1-3')).toThrow()
  })
  it('daysInMonth', () => {
    expect(daysInMonth(2028, 2)).toBe(29)
    expect(daysInMonth(2026, 2)).toBe(28)
    expect(daysInMonth(2026, 11)).toBe(30)
  })
  it('Monatslabels', () => {
    expect(monthLabel('2026-11-01')).toBe('November 2026')
    expect(shortMonthLabel('2029-12-30')).toBe('Dez. 2029')
  })
  it('daysLeftLabel', () => {
    expect(daysLeftLabel(13)).toBe('noch 13 Tage')
    expect(daysLeftLabel(1)).toBe('letzter Tag')
    expect(daysLeftLabel(0)).toBe('Monat vorbei')
  })
  it('standLabel', () => {
    const iso = '2026-11-18T12:00:00Z'
    const out = standLabel(iso)
    expect(out).toMatch(/^\d\d\.\d\d\. · \d\d:\d\d$/)
    const d = new Date(iso)
    expect(out.slice(0, 6)).toBe(
      `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`,
    )
    expect(out.slice(0, 6)).toMatch(/^1[78]\.11\.$/)
  })
})
