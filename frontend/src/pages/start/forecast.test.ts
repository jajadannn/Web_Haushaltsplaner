import { describe, expect, it } from 'vitest'
import { eventKindLabel, eventRangeText, forecastHorizon, forecastUntil, isLowestEvent, pickForecastAccount } from './forecast'

describe('forecastHorizon', () => {
  it('nimmt den Wert aus den Einstellungen', () => {
    expect(forecastHorizon({ 'forecast.horizon_days': 60 })).toBe(60)
    expect(forecastHorizon({ 'forecast.horizon_days': '30' })).toBe(30)
  })
  it('fällt auf 45 Tage zurück', () => {
    expect(forecastHorizon(undefined)).toBe(45)
    expect(forecastHorizon({})).toBe(45)
    expect(forecastHorizon({ 'forecast.horizon_days': 'x' })).toBe(45)
    expect(forecastHorizon({ 'forecast.horizon_days': 0 })).toBe(45)
  })
})

describe('forecastUntil', () => {
  it('rechnet Tage auf das Heute', () => {
    expect(forecastUntil('2026-11-05', 45)).toBe('2026-12-20')
  })
})

describe('pickForecastAccount', () => {
  const accounts = [
    { id: 1, type: 'savings', archived_at: null },
    { id: 2, type: 'checking', archived_at: null },
    { id: 3, type: 'checking', archived_at: null },
    { id: 4, type: 'loan', archived_at: null },
  ]
  it('nimmt das erste Girokonto', () => expect(pickForecastAccount(accounts)).toBe(2))
  it('sonst das erste Zahlkonto', () => expect(pickForecastAccount(accounts.slice(0, 1))).toBe(1))
  it('Kredit- und archivierte Konten zählen nicht', () => {
    expect(pickForecastAccount([accounts[3], { ...accounts[0], archived_at: 'x' }])).toBeNull()
  })
})

describe('Ereignisse', () => {
  it('benennt die Arten', () => {
    expect(eventKindLabel('fixed_cost')).toBe('Fixkost')
    expect(eventKindLabel('expected_income')).toBe('Einnahme')
    expect(eventKindLabel('loan_installment')).toBe('Kreditrate')
  })
  it('zeigt die Spanne, falls vorhanden', () => {
    expect(eventRangeText(['2800.00', '3000.00'])).toBe('2.800,00\u00a0€ bis 3.000,00\u00a0€')
    expect(eventRangeText(null)).toBeNull()
    expect(eventRangeText([])).toBeNull()
  })
  it('erkennt den niedrigsten Stand', () => {
    const lowest = { date: '2026-11-20', balance: '10.00' }
    expect(isLowestEvent({ date: '2026-11-20', balance_after: '10.00' }, lowest)).toBe(true)
    expect(isLowestEvent({ date: '2026-11-20', balance_after: '50.00' }, lowest)).toBe(false)
  })
})
