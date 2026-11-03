import { describe, expect, it } from 'vitest'
import { formatEuro, isNegative } from './money'

describe('formatEuro', () => {
  it.each([
    ['1749.21', '1.749,21\u00a0€'],
    ['412.3', '412,30\u00a0€'],
    ['-15.00', '\u221215,00\u00a0€'],
    ['0.00', '0,00\u00a0€'],
    ['-0.00', '0,00\u00a0€'],
    ['1234567.89', '1.234.567,89\u00a0€'],
    ['7840.12', '7.840,12\u00a0€'],
  ])('%s -> %s', (input, expected) => {
    expect(formatEuro(input)).toBe(expected)
  })

  it.each(['1,5', 'abc', '1.234', ''])('wirft bei %j', (input) => {
    expect(() => formatEuro(input)).toThrow()
  })
})

describe('isNegative', () => {
  it('erkennt Vorzeichen', () => {
    expect(isNegative('-15.00')).toBe(true)
    expect(isNegative('15.00')).toBe(false)
    expect(isNegative('0.00')).toBe(false)
    expect(isNegative('-0.00')).toBe(false)
  })
})
