import type { Loan } from '../api/hooks'
import { toCents } from './moneyInput'

/**
 * Getilgter Anteil 0–1 aus den tatsächlich gezahlten Tilgungsanteilen.
 * Gesamt ist die ursprüngliche Summe, sonst gezahlte Tilgung + Restschuld.
 */
export function loanProgress(loan: Pick<Loan, 'principal_original' | 'principal_repaid' | 'remaining_debt'>): number | null {
  const repaid = toCents(loan.principal_repaid)
  const total = loan.principal_original ? toCents(loan.principal_original) : repaid + toCents(loan.remaining_debt)
  if (total <= 0n) return null
  return Math.min(1, Math.max(0, Number(repaid) / Number(total)))
}
