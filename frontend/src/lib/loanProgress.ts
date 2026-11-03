import type { Loan, ScheduleEntry } from '../api/hooks'
import { toCents } from './moneyInput'

/** Getilgter Anteil 0–1: aus der ursprünglichen Summe, sonst aus dem Plan (bezahlte Tilgung + Restschuld). */
export function loanProgress(loan: Loan, schedule?: ScheduleEntry[]): number | null {
  const remaining = toCents(loan.remaining_debt)
  if (loan.principal_original) {
    const original = toCents(loan.principal_original)
    return original > 0n ? Math.min(1, Math.max(0, Number(original - remaining) / Number(original))) : null
  }
  if (!schedule) return null
  const paid = schedule.filter((e) => e.status === 'paid').reduce((s, e) => s + toCents(e.planned_principal), 0n)
  const total = paid + remaining
  return total > 0n && paid > 0n ? Number(paid) / Number(total) : null
}
