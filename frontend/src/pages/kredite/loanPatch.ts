import type { Loan } from '../../api/hooks'
import { toCents } from '../../lib/moneyInput'

/** Bearbeitbare Felder des Kredit-Formulars (Zielwerte, wie sie die API erwartet). */
export interface LoanFormValues {
  name: string
  lender_name: string
  annual_interest_rate: number | string | null
  payment_account_id: number | null
  lender_iban: string | null
  payment_reference: string | null
  fixed_rate_until: string | null
  extra_amount: string
  installment_amount: string | null
  fixed_principal: string | null
  term_months: number | null
}

function sameMoney(a: string | null | undefined, b: string | null | undefined): boolean {
  if (a == null || b == null) return (a ?? null) === (b ?? null)
  return toCents(a) === toCents(b)
}

function sameNumber(a: number | string | null | undefined, b: number | string | null | undefined): boolean {
  if (a == null || b == null) return (a ?? null) === (b ?? null)
  return Number(a) === Number(b)
}

/**
 * PATCH-Körper für „Konditionen ändern“: nur Felder, die sich gegenüber dem geladenen
 * Kredit tatsächlich unterscheiden. So kann eine reine Umbenennung weder Laufzeit noch
 * Rate überschreiben.
 */
export function loanPatch(loan: Loan, v: LoanFormValues): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  if (v.name !== loan.name) patch.name = v.name
  if (v.lender_name !== loan.lender_name) patch.lender_name = v.lender_name
  if (!sameNumber(v.annual_interest_rate, loan.annual_interest_rate)) patch.annual_interest_rate = v.annual_interest_rate
  if ((v.payment_account_id ?? null) !== (loan.payment_account_id ?? null)) patch.payment_account_id = v.payment_account_id
  if ((v.lender_iban ?? null) !== (loan.lender_iban ?? null)) patch.lender_iban = v.lender_iban
  if ((v.payment_reference ?? null) !== (loan.payment_reference ?? null)) patch.payment_reference = v.payment_reference
  if ((v.fixed_rate_until ?? null) !== (loan.fixed_rate_until ?? null)) patch.fixed_rate_until = v.fixed_rate_until
  if (!sameMoney(v.extra_amount, loan.extra_amount)) patch.extra_amount = v.extra_amount
  if (!sameMoney(v.installment_amount, loan.installment_amount)) patch.installment_amount = v.installment_amount
  if (!sameMoney(v.fixed_principal, loan.fixed_principal)) patch.fixed_principal = v.fixed_principal
  if ((v.term_months ?? null) !== (loan.term_months ?? null)) patch.term_months = v.term_months
  return patch
}
