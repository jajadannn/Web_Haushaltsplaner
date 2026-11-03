import { describe, expect, it } from 'vitest'
import { dayHeading, fullDate, monthEnd, shiftMonth, shortDate, todayISO } from './dates'

describe('dates extra', () => {
  it('todayISO', () => expect(todayISO(new Date(2026, 10, 3))).toBe('2026-11-03'))
  it('shortDate/fullDate', () => {
    expect(shortDate('2026-11-03')).toBe('03.11.')
    expect(fullDate('2026-11-03')).toBe('03.11.2026')
  })
  it.each([
    ['2026-11-18', -1, '2026-10-01'], ['2026-01-05', -1, '2025-12-01'],
    ['2026-12-01', 1, '2027-01-01'], ['2026-11-18', 0, '2026-11-01'],
  ])('shiftMonth(%s,%i)', (v, d, e) => expect(shiftMonth(v, d)).toBe(e))
  it('monthEnd', () => {
    expect(monthEnd('2028-02-10')).toBe('2028-02-29')
    expect(monthEnd('2026-02-10')).toBe('2026-02-28')
    expect(monthEnd('2026-12-01')).toBe('2026-12-31')
  })
  describe('dayHeading', () => {
    const today = '2026-11-18'
    it('Heute/Gestern', () => {
      expect(dayHeading('2026-11-18', today)).toBe('Heute')
      expect(dayHeading('2026-11-17', today)).toBe('Gestern')
    })
    it('Wochentag', () => expect(dayHeading('2026-11-16', today)).toBe('Montag, 16.11.'))
    it('anderes Jahr mit Jahr', () => expect(dayHeading('2025-11-16', today)).toBe('Sonntag, 16.11.2025'))
    it('Gestern über Monatsgrenze', () => expect(dayHeading('2026-10-31', '2026-11-01')).toBe('Gestern'))
  })
})
