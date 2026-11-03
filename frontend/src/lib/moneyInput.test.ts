import { describe, expect, it } from 'vitest'
import { fromCents, moneyToInput, negate, parseMoneyInput, toCents } from './moneyInput'

describe('parseMoneyInput', () => {
  it.each([
    ['12', '12.00'], ['12,5', '12.50'], ['12,50', '12.50'], ['1.234,56', '1234.56'],
    ['1234.56', '1234.56'], ['1.234', '1234.00'], ['0,99', '0.99'], [',5', '0.50'],
    ['-12,30', '-12.30'], ['−12,30', '-12.30'], ['+5', '5.00'], [' 12,50 € ', '12.50'],
    ['-0,00', '0.00'],
  ])('parst %j zu %j', (input, expected) => {
    expect(parseMoneyInput(input)).toBe(expected)
  })

  it.each([
    '', 'abc', '12,345', '1,2,3', '12.345,6.7', '1.23.4,00', '12.3456', '1.2345,00', '12345678901,00',
  ])('lehnt %j ab', (input) => {
    expect(parseMoneyInput(input)).toBeNull()
  })
})

describe('moneyToInput', () => {
  it('formatiert', () => {
    expect(moneyToInput('1234.5')).toBe('1234,50')
    expect(moneyToInput('-3.00')).toBe('-3,00')
    expect(moneyToInput(null)).toBe('')
  })
})

describe('Cents', () => {
  it.each(['0.00', '0.05', '12.30', '-12.30', '-0.05', '1234.56'])('Round-Trip %s', (v) => {
    expect(fromCents(toCents(v))).toBe(v)
  })
  it('toCents', () => {
    expect(toCents('0.05')).toBe(5n)
    expect(toCents('-1.50')).toBe(-150n)
  })
})

describe('negate', () => {
  it('kehrt das Vorzeichen um', () => {
    expect(negate('12.00')).toBe('-12.00')
    expect(negate('-1.00')).toBe('1.00')
    expect(negate('0.00')).toBe('0.00')
  })
})
