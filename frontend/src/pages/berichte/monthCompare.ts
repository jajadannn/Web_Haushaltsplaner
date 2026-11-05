/** Reine Hilfen für Monatsvergleich und „Frage zu deinen Buchungen“. */
import { fullDate } from '../../lib/dates'
import { formatEuro, isNegative } from '../../lib/money'
import type { ComparisonCategory } from '../../api/ai'

export function deltaText(delta: string): string {
  if (/^-?0+(\.0+)?$/.test(delta)) return 'unverändert'
  return isNegative(delta) ? `${formatEuro(delta)} weniger` : `+${formatEuro(delta)} mehr`
}

/** Bei Ausgaben ist ein Plus ungünstig. */
export function deltaTone(delta: string): 'worse' | 'better' | 'same' {
  if (/^-?0+(\.0+)?$/.test(delta)) return 'same'
  return isNegative(delta) ? 'better' : 'worse'
}

/** Kategorien mit den größten Abweichungen; reine Nullzeilen entfallen. */
export function mainCategories(categories: ComparisonCategory[], limit = 5): ComparisonCategory[] {
  const size = (c: ComparisonCategory) => Math.abs(Number(c.delta))
  return categories
    .filter((c) => Number(c.current) !== 0 || Number(c.previous) !== 0)
    .sort((a, b) => size(b) - size(a))
    .slice(0, limit)
}

export function askPeriodText(period: { from: string; to: string } | null | undefined): string | null {
  return period ? `${fullDate(period.from)} – ${fullDate(period.to)}` : null
}

const TOOLS: Record<string, string> = {
  sum_by_category: 'Summe nach Kategorie',
  sum_by_merchant: 'Summe nach Anbieter',
  sum_by_period: 'Summe im Zeitraum',
  compare_periods: 'Zeiträume vergleichen',
  list_transactions: 'Buchungen suchen',
  largest_transactions: 'Größte Buchungen',
  top_categories: 'Größte Kategorien',
}

export function toolLabel(tool: string): string {
  return TOOLS[tool] ?? tool.replace(/_/g, ' ')
}

export const transactionLink = (id: number): string => `/buchungen?id=${id}`
