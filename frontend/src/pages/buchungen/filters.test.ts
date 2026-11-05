import { describe, expect, it } from 'vitest'
import { filterToQuery, parseFilter } from './filters'

describe('filterToQuery', () => {
  it('„Nur ungeprüfte“ sendet unconfirmed statt review_status', () => {
    const f = parseFilter(new URLSearchParams('pruefen=1'), '2026-11-01')
    const q = filterToQuery(f)
    expect(q.unconfirmed).toBe(true)
    expect(q.review_status).toBeUndefined()
  })
  it('ohne Filter kein unconfirmed', () => {
    expect(filterToQuery(parseFilter(new URLSearchParams(''), '2026-11-01')).unconfirmed).toBeUndefined()
  })
})
