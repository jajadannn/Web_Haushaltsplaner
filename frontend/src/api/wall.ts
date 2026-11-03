/** Antwort von GET /wall (siehe app/schemas/budget.py). Beträge sind Dezimalstrings. */

export type ItemStatus = 'paid' | 'open' | 'overdue'

export interface MonthItem {
  kind: 'fixed' | 'loan'
  ref_id: number
  name: string
  amount: string
  due_date: string
  status: ItemStatus
  paid_amount: string | null
  paid_on: string | null
}

export interface WallProfile {
  profile_id: number
  name: string
  available: string
  income: string
  fixed_total: string
  variable_spent: string
  available_per_day: string | null
  timeline: MonthItem[]
  upcoming: MonthItem[]
  open_items: number
}

export interface WallLoan {
  loan_id: number
  profile_id: number
  profile_name: string
  name: string
  status: string
  remaining_debt: string | null
  payoff_date: string | null
  remaining_installments: number
  next_due_date: string | null
  next_installment: string | null
}

export interface WallView {
  generated_at: string
  month: string
  as_of: string
  days_left: number
  profiles: WallProfile[]
  loans: WallLoan[]
}

export class WallError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** Fehlercodes der API in Sätze fürs Display übersetzen. */
function describe(code: string, status: number): string {
  if (code === 'wall_local_only') return 'Das Wanddisplay ist nur im Heimnetz erreichbar.'
  if (status >= 500) return 'Der Finanzplaner antwortet gerade nicht.'
  return 'Die Übersicht konnte nicht geladen werden.'
}

export async function fetchWall(signal?: AbortSignal): Promise<WallView> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/wall`, { signal, headers: { Accept: 'application/json' } })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new WallError('network', 'Keine Verbindung zum Finanzplaner.')
  }
  if (!response.ok) {
    let code = `http_${response.status}`
    try {
      const body = await response.json()
      code = body?.error?.code ?? code
    } catch {
      // kein JSON – Code aus dem Status
    }
    throw new WallError(code, describe(code, response.status))
  }
  return response.json() as Promise<WallView>
}
