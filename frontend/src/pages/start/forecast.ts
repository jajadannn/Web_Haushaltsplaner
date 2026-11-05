/** Reine Hilfen für die Kontovorschau auf der Startseite. */
import { addDays } from '../../lib/dates'
import { formatEuro } from '../../lib/money'

export const DEFAULT_HORIZON_DAYS = 45

export function forecastHorizon(settings: Record<string, unknown> | undefined): number {
  const n = Number(settings?.['forecast.horizon_days'])
  return Number.isFinite(n) && n > 0 ? Math.round(n) : DEFAULT_HORIZON_DAYS
}

export function forecastUntil(today: string, horizonDays: number): string {
  return addDays(today, horizonDays)
}

interface AccountLike { id: number; type: string; archived_at: string | null }

/** Zahlkonten der Vorschau: ohne Kredit- und archivierte Konten. */
export const forecastAccounts = <T extends AccountLike>(accounts: T[]): T[] =>
  accounts.filter((a) => !a.archived_at && a.type !== 'loan')

/** Hauptkonto = erstes Girokonto, sonst das erste Zahlkonto. */
export function pickForecastAccount(accounts: AccountLike[]): number | null {
  const usable = forecastAccounts(accounts)
  return (usable.find((a) => a.type === 'checking') ?? usable[0])?.id ?? null
}

const KIND: Record<string, string> = { fixed_cost: 'Fixkost', expected_income: 'Einnahme', loan_installment: 'Kreditrate' }
export const eventKindLabel = (kind: string): string => KIND[kind] ?? kind

export function eventRangeText(range: string[] | null | undefined): string | null {
  if (!range || range.length < 2) return null
  return `${formatEuro(range[0])} bis ${formatEuro(range[range.length - 1])}`
}

export function isLowestEvent(event: { date: string; balance_after: string }, lowest: { date: string; balance: string }): boolean {
  return event.date === lowest.date && event.balance_after === lowest.balance
}
