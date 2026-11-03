import type { Loan } from '../../api/hooks'

export const LOAN_TYPE_LABEL: Record<Loan['loan_type'], string> = {
  annuity: 'Annuitätendarlehen',
  installment: 'Tilgungsdarlehen',
  private: 'Privatkredit',
}

/** Zinssatz "5.0000" → "5,00 %" */
export function rateLabel(rate: string | number): string {
  const value = String(rate)
  const [whole, frac = ''] = value.split('.')
  const digits = frac.replace(/0+$/, '').padEnd(2, '0')
  return `${whole},${digits} %`
}

/** Zinssatz "5,25" → "5.25" (bis 4 Nachkommastellen, unter 100 %). */
export function parseRate(raw: string): string | null {
  const text = raw.trim().replace('%', '').trim().replace(',', '.')
  if (!/^\d{1,2}(\.\d{1,4})?$/.test(text)) return null
  return text
}
