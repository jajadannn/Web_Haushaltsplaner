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

const money = (v: unknown): string | null => (typeof v === 'number' ? String(v) : str(v))

export interface IncomeSeriesPayload {
  name: string
  amount: string | null
  amountMin: string | null
  amountMax: string | null
  intervalMonths: number
  dueDay: number
  firstDueDate: string | null
  accountId: number | null
  categoryId: number | null
  matchText: string | null
}

/** Vorschlag „erwartete Einnahme“ (Gehalt, Rente, Miete …). */
export function parseIncomeSeries(payload: Loose): IncomeSeriesPayload {
  return {
    name: str(payload.name) ?? '',
    amount: money(payload.amount),
    amountMin: money(payload.amount_min),
    amountMax: money(payload.amount_max),
    intervalMonths: num(payload.interval_months) ?? 1,
    dueDay: num(payload.due_day) ?? 1,
    firstDueDate: str(payload.first_due_date),
    accountId: num(payload.account_id),
    categoryId: num(payload.category_id),
    matchText: str(payload.match_text),
  }
}

export interface AnnualCostPayload extends FixedCostPayload {
  expectedDate: string | null
}

/** Vorschlag „Jahresposten prüfen“ – wird wie eine Fixkost angelegt. */
export function parseAnnualCost(payload: Loose): AnnualCostPayload {
  return { ...parseFixedCostPayload(payload), intervalMonths: 12, expectedDate: str(payload.expected_date) }
}

export interface UnusualPayload {
  type: 'duplicate' | 'high'
  name: string
  month: string | null
  amount: string | null
  paidAmount: string | null
}

export function parseUnusual(payload: Loose): UnusualPayload {
  return {
    type: payload.type === 'duplicate' ? 'duplicate' : 'high',
    name: str(payload.name) ?? 'Zahlung',
    month: str(payload.month),
    amount: money(payload.amount),
    paidAmount: money(payload.paid_amount),
  }
}

export interface MissingPaymentPayload {
  fixedCostId: number | null
  name: string
  amount: string | null
  dueDate: string | null
  month: string | null
}

export function parseMissingPayment(payload: Loose): MissingPaymentPayload {
  return {
    fixedCostId: num(payload.fixed_cost_id),
    name: str(payload.name) ?? 'Fixkost',
    amount: money(payload.amount),
    dueDate: str(payload.due_date),
    month: str(payload.month),
  }
}
