import { describe, expect, it } from 'vitest'
import { loanPatch, type LoanFormValues } from './loanPatch'
import type { Loan } from '../../api/hooks'

const loan = {
  name: 'Auto', lender_name: 'Bank', annual_interest_rate: '4.9500', payment_account_id: 3,
  lender_iban: null, payment_reference: null, fixed_rate_until: null, extra_amount: '0.00',
  installment_amount: '234.86', fixed_principal: null, term_months: 48, loan_type: 'annuity',
} as unknown as Loan

const values = (o: Partial<LoanFormValues> = {}): LoanFormValues => ({
  name: 'Auto', lender_name: 'Bank', annual_interest_rate: 4.95, payment_account_id: 3,
  lender_iban: null, payment_reference: null, fixed_rate_until: null, extra_amount: '0.00',
  installment_amount: '234.86', fixed_principal: null, term_months: 48, ...o,
})

describe('loanPatch', () => {
  it('reine Namensänderung sendet nur den Namen (F15)', () => {
    expect(loanPatch(loan, values({ name: 'Neues Auto' }))).toEqual({ name: 'Neues Auto' })
  })
  it('geänderter Zins sendet nur den Zins', () => {
    expect(loanPatch(loan, values({ annual_interest_rate: 6 }))).toEqual({ annual_interest_rate: 6 })
  })
  it('bewusst geänderte Laufzeit wird gesendet', () => {
    expect(loanPatch(loan, values({ term_months: 60, installment_amount: null }))).toEqual({ term_months: 60, installment_amount: null })
  })
  it('keine Änderung ergibt leeren Patch', () => {
    expect(loanPatch(loan, values())).toEqual({})
  })
  it('Geldwerte werden numerisch verglichen', () => {
    expect(loanPatch(loan, values({ installment_amount: '234.860' }))).toEqual({})
  })
})
