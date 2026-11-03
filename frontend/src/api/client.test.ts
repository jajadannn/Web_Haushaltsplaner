import { describe, expect, it } from 'vitest'
import { toQuery } from './client'

describe('toQuery', () => {
  it('leer → leerer String', () => {
    expect(toQuery()).toBe('')
    expect(toQuery({})).toBe('')
  })
  it('überspringt undefined, null und leere Strings', () => {
    expect(toQuery({ a: undefined, b: null, c: '' })).toBe('')
  })
  it('behält false und 0', () => {
    expect(toQuery({ a: false, b: 0 })).toBe('?a=false&b=0')
  })
  it('Arrays werden wiederholt', () => {
    expect(toQuery({ account_ids: [1, 2] })).toBe('?account_ids=1&account_ids=2')
  })
  it('kodiert Umlaute und Leerzeichen', () => {
    const q = toQuery({ q: 'Müller & Co' })
    expect(q.startsWith('?q=')).toBe(true)
    expect(q).not.toContain(' ')
    expect(new URLSearchParams(q).get('q')).toBe('Müller & Co')
  })
})
