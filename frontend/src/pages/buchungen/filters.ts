import type { Query } from '../../api/client'
import { monthEnd } from '../../lib/dates'

/**
 * Filter der Buchungsliste – stehen in der URL, damit Links (z. B. von der Startseite)
 * und Zurück im Browser funktionieren.
 *
 *   ?monat=2026-11-01   Monat (fehlt: aktueller Monat, "alle": ohne Zeitraum)
 *   &konto=3            ein Konto
 *   &kategorie=12       Kategorie (mit Unterkategorien) · "ohne" = unkategorisiert
 *   &q=rewe             Suche in Text und Empfänger
 *   &pruefen=1          nur unbestätigte (ohne Bestätigung oder nur Vorschlag)
 *   &ausgeschlossen=1   ausgeschlossene mit anzeigen
 */
export interface TxFilter {
  month: string | 'alle'
  account: number | null
  category: number | 'ohne' | null
  search: string
  onlyReview: boolean
  withExcluded: boolean
}

const MONTH = /^\d{4}-\d{2}-01$/

export function parseFilter(params: URLSearchParams, currentMonth: string): TxFilter {
  const month = params.get('monat')
  const account = Number(params.get('konto'))
  const category = params.get('kategorie')
  return {
    month: month === 'alle' ? 'alle' : month && MONTH.test(month) ? month : currentMonth,
    account: Number.isInteger(account) && account > 0 ? account : null,
    category: category === 'ohne' ? 'ohne' : Number(category) > 0 ? Number(category) : null,
    search: (params.get('q') ?? '').slice(0, 200),
    onlyReview: params.get('pruefen') === '1',
    withExcluded: params.get('ausgeschlossen') === '1',
  }
}

export function filterToParams(filter: TxFilter, currentMonth: string): Record<string, string> {
  const out: Record<string, string> = {}
  if (filter.month !== currentMonth) out.monat = filter.month
  if (filter.account) out.konto = String(filter.account)
  if (filter.category) out.kategorie = String(filter.category)
  if (filter.search.trim()) out.q = filter.search.trim()
  if (filter.onlyReview) out.pruefen = '1'
  if (filter.withExcluded) out.ausgeschlossen = '1'
  return out
}

/** Filter → Query für GET /transactions und den CSV-Export (ohne limit/offset). */
export function filterToQuery(filter: TxFilter): Query {
  return {
    date_from: filter.month === 'alle' ? undefined : filter.month,
    date_to: filter.month === 'alle' ? undefined : monthEnd(filter.month),
    account_ids: filter.account ? [filter.account] : undefined,
    category_id: typeof filter.category === 'number' ? filter.category : undefined,
    uncategorized: filter.category === 'ohne' ? true : undefined,
    search: filter.search.trim() || undefined,
    // needs_review UND auto_categorized: alles, was der Nutzer noch nicht bestätigt hat
    unconfirmed: filter.onlyReview ? true : undefined,
    include_excluded: filter.withExcluded || undefined,
  }
}
