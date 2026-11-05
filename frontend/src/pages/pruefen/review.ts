/** Reine Hilfen für die Prüfliste: Vorschlags-Payloads lesen, Gruppenauswahl. */

type Loose = Record<string, unknown>

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const money = (v: unknown): string | null => (typeof v === 'number' ? String(v) : str(v))

export type MatchField = 'any' | 'description' | 'counterparty'

export interface RuleSuggestion {
  name: string
  pattern: string
  matchField: MatchField
  matchType: string
  targetCategoryId: number | null
  confirmed: number
  wouldMatchOpen: number
  conflictCount: number
  /** lesbare Kurzbeschreibungen der Konfliktbuchungen (soweit der Server sie mitschickt) */
  conflicts: string[]
}

function conflictLabel(c: unknown): string {
  if (typeof c === 'string') return c
  if (c && typeof c === 'object') {
    const o = c as Loose
    const who = str(o.counterparty) ?? str(o.description) ?? str(o.name)
    const cat = str(o.category_name) ?? str(o.category)
    if (who && cat) return `${who} (${cat})`
    return who ?? cat ?? ''
  }
  return ''
}

export function parseRule(payload: Loose, evidence: Loose): RuleSuggestion {
  const field = payload.match_field
  const raw = evidence.conflicts
  const list = Array.isArray(raw) ? raw : []
  return {
    name: str(payload.name) ?? '',
    pattern: str(payload.pattern) ?? '',
    matchField: field === 'any' || field === 'description' ? field : 'counterparty',
    matchType: str(payload.match_type) ?? 'contains',
    targetCategoryId: num(payload.target_category_id),
    confirmed: num(evidence.confirmed) ?? 0,
    wouldMatchOpen: num(evidence.would_match_open) ?? 0,
    conflictCount: Array.isArray(raw) ? raw.length : num(raw) ?? 0,
    conflicts: list.map(conflictLabel).filter(Boolean),
  }
}

export function ruleEvidenceText(r: Pick<RuleSuggestion, 'confirmed' | 'wouldMatchOpen'>): string {
  const open = r.wouldMatchOpen === 1 ? '1 offene Buchung' : `${r.wouldMatchOpen} offene Buchungen`
  return `${r.confirmed}× bestätigt, würde ${open} zuordnen`
}

export interface AmountChange {
  fixedCostId: number | null
  name: string
  permanent: boolean
  oldAmount: string | null
  newAmount: string | null
  validFrom: string | null
}

export function parseChange(payload: Loose): AmountChange {
  return {
    fixedCostId: num(payload.fixed_cost_id),
    name: str(payload.name) ?? 'Fixkost',
    permanent: payload.change === 'dauerhaft',
    oldAmount: money(payload.old_amount),
    newAmount: money(payload.new_amount),
    validFrom: str(payload.valid_from),
  }
}

export interface Consistency {
  type: 'mixed_categories' | 'similar_categories'
  counterparty: string | null
  categoryIds: number[]
  counts: Record<string, number>
  names: string[]
}

export function parseConsistency(payload: Loose): Consistency {
  const counts: Record<string, number> = {}
  if (payload.counts && typeof payload.counts === 'object') {
    for (const [k, v] of Object.entries(payload.counts as Loose)) {
      const n = num(v)
      if (n !== null) counts[k] = n
    }
  }
  return {
    type: payload.type === 'similar_categories' ? 'similar_categories' : 'mixed_categories',
    counterparty: str(payload.counterparty),
    categoryIds: Array.isArray(payload.category_ids) ? payload.category_ids.filter((v): v is number => typeof v === 'number') : [],
    counts,
    names: Array.isArray(payload.names) ? payload.names.filter((v): v is string => typeof v === 'string') : [],
  }
}

export function consistencyText(c: Consistency, categoryName: (id: number) => string): string {
  if (c.type === 'similar_categories') {
    const names = c.names.length ? c.names : c.categoryIds.map(categoryName)
    return `Diese Kategorien wirken ähnlich: ${names.join(', ')}.`
  }
  const parts = c.categoryIds.map((id) => {
    const n = c.counts[String(id)]
    return n ? `${categoryName(id)} (${n}×)` : categoryName(id)
  })
  return `„${c.counterparty ?? 'Dieser Empfänger'}“ ist in mehreren Kategorien gebucht: ${parts.join(', ')}.`
}

export interface Question {
  type: string
  merchant: string | null
  question: string
  options: { value: string; label: string }[]
}

export function parseQuestion(payload: Loose): Question {
  const raw = Array.isArray(payload.options) ? (payload.options as Loose[]) : []
  return {
    type: str(payload.type) ?? '',
    merchant: str(payload.merchant),
    question: str(payload.question) ?? '',
    options: raw.flatMap((o) => {
      const value = o && typeof o === 'object' ? str(o.value) : null
      const label = o && typeof o === 'object' ? str(o.label) : null
      return value && label ? [{ value, label }] : []
    }),
  }
}

/** Buchungen einer Gruppe, die bestätigt werden – abgewählte bleiben offen. */
export function confirmIds(ids: number[], deselected: ReadonlySet<number>): number[] {
  return ids.filter((id) => !deselected.has(id))
}

/** Höchste Priorität zuerst, bei Gleichstand die neueren (höhere id). */
export function sortSuggestions<T extends { id: number; priority: number }>(list: T[]): T[] {
  return [...list].sort((a, b) => b.priority - a.priority || b.id - a.id)
}
