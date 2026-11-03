/**
 * Geldbeträge kommen als Dezimalstrings aus der API ("1749.21", "-15.00").
 * Sie werden nur als Text umgeformt, nie über float gerechnet.
 */

const DECIMAL = /^(-)?(\d+)(?:\.(\d{1,2}))?$/

const MINUS = '−' // typografisches Minus
const NBSP = ' '

export interface ParsedMoney {
  negative: boolean
  euros: string
  cents: string
}

export function parseMoney(value: string): ParsedMoney {
  const match = DECIMAL.exec(value.trim())
  if (!match) throw new Error(`Kein gültiger Betrag: ${value}`)
  const [, sign, euros, cents = ''] = match
  const normalizedEuros = euros.replace(/^0+(?=\d)/, '')
  const normalizedCents = cents.padEnd(2, '0')
  const isZero = /^0+$/.test(normalizedEuros) && /^0+$/.test(normalizedCents)
  return { negative: sign === '-' && !isZero, euros: normalizedEuros, cents: normalizedCents }
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/** "1749.21" → "1.749,21 €", "-15.00" → "−15,00 €" */
export function formatEuro(value: string): string {
  const { negative, euros, cents } = parseMoney(value)
  return `${negative ? MINUS : ''}${groupThousands(euros)},${cents}${NBSP}€`
}

export function isNegative(value: string): boolean {
  return parseMoney(value).negative
}
