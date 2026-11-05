/** Reine Hilfen für Vorschläge (Erkannte Fixkosten) – Payload und Belege kommen als lose Objekte vom Server. */

export const INTERVAL_OPTIONS = [
  { value: '1', label: 'monatlich' },
  { value: '3', label: 'vierteljährlich' },
  { value: '6', label: 'halbjährlich' },
  { value: '12', label: 'jährlich' },
]

export function intervalLabel(months: number): string {
  return INTERVAL_OPTIONS.find((o) => o.value === String(months))?.label ?? `alle ${months} Monate`
}

type Loose = Record<string, unknown>

export interface FixedCostPayload {
  name: string
  amount: string | null
  intervalMonths: number
  dueDay: number
  firstDueDate: string | null
  categoryId: number | null
  accountId: number | null
  matchText: string | null
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

export function parseFixedCostPayload(payload: Loose): FixedCostPayload {
  const amount = typeof payload.amount === 'number' ? String(payload.amount) : str(payload.amount)
  return {
    name: str(payload.name) ?? '',
    amount,
    intervalMonths: num(payload.interval_months) ?? 1,
    dueDay: num(payload.due_day) ?? 1,
    firstDueDate: str(payload.first_due_date),
    categoryId: num(payload.category_id),
    accountId: num(payload.account_id),
    matchText: str(payload.match_text),
  }
}

export interface EvidenceTx {
  id: number
  splitId: number | null
  date: string
  amount: string
}

export function parseEvidence(evidence: Loose): { transactions: EvidenceTx[]; identicalAmount: boolean } {
  const raw = Array.isArray(evidence.transactions) ? (evidence.transactions as Loose[]) : []
  const transactions = raw.flatMap((t) => {
    const id = num(t.id)
    const date = str(t.date)
    if (id === null || !date) return []
    const amount = typeof t.amount === 'number' ? String(t.amount) : str(t.amount) ?? '0'
    return [{ id, splitId: num(t.split_id), date, amount }]
  })
  return { transactions, identicalAmount: evidence.identical_amount === true }
}

const RANK: Record<string, number> = { open: 0, dry_run: 1 }

/** Offene zuerst, dann Probelauf, dann der Rest; innerhalb nach Priorität (hoch zuerst). */
export function sortSuggestions<T extends { status: string; priority: number }>(list: T[]): T[] {
  return [...list].sort((a, b) => (RANK[a.status] ?? 2) - (RANK[b.status] ?? 2) || b.priority - a.priority)
}

export function statusNote(status: string): string | null {
  if (status === 'dry_run') return 'wäre automatisch angelegt worden'
  if (status === 'auto_applied') return 'automatisch angelegt'
  return null
}
