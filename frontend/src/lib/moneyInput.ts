/**
 * Betragseingabe im deutschen Format → Dezimalstring für die API.
 *
 * Erlaubt: "12", "12,5", "12,50", "1.234,56", "1234.56" (Punkt als Dezimaltrenner nur ohne
 * Komma und mit höchstens zwei Nachkommastellen), führendes "-" oder "−". Mehr als zwei
 * Nachkommastellen, Buchstaben oder falsch gesetzte Tausenderpunkte werden abgelehnt.
 */
export function parseMoneyInput(raw: string): string | null {
  let text = raw.trim().replace(/\s|€/g, '').replace('−', '-')
  if (!text) return null
  let negative = false
  if (text.startsWith('-')) {
    negative = true
    text = text.slice(1)
  } else if (text.startsWith('+')) {
    text = text.slice(1)
  }
  let euros: string
  let cents = ''
  if (text.includes(',')) {
    const parts = text.split(',')
    if (parts.length !== 2) return null
    ;[euros, cents] = parts
    if (euros.includes('.')) {
      if (!/^\d{1,3}(\.\d{3})+$/.test(euros)) return null
      euros = euros.replace(/\./g, '')
    }
  } else if (/^\d+\.\d{1,2}$/.test(text)) {
    ;[euros, cents] = text.split('.')
  } else if (/^\d{1,3}(\.\d{3})+$/.test(text)) {
    euros = text.replace(/\./g, '')
  } else {
    euros = text
  }
  if (euros === '') euros = '0'
  if (!/^\d+$/.test(euros) || !/^\d{0,2}$/.test(cents)) return null
  const normalized = `${euros.replace(/^0+(?=\d)/, '')}.${cents.padEnd(2, '0')}`
  if (normalized.length > 13) return null // NUMERIC(12,2)
  return negative && normalized !== '0.00' ? `-${normalized}` : normalized
}

/** Dezimalstring → Eingabetext ("1234.5" → "1234,50"), ohne Tausenderpunkte. */
export function moneyToInput(value: string | null | undefined): string {
  if (!value) return ''
  const [euros, cents = ''] = value.replace('-', '').split('.')
  return `${value.startsWith('-') ? '-' : ''}${euros},${cents.padEnd(2, '0')}`
}

/** Betrag als absolute Zahl in Cent (für Summen ohne float). */
export function toCents(value: string): bigint {
  const negative = value.startsWith('-')
  const [euros, cents = ''] = value.replace('-', '').split('.')
  const total = BigInt(euros) * 100n + BigInt(cents.padEnd(2, '0').slice(0, 2) || '0')
  return negative ? -total : total
}

export function fromCents(cents: bigint): string {
  const negative = cents < 0n
  const abs = negative ? -cents : cents
  const text = `${abs / 100n}.${String(abs % 100n).padStart(2, '0')}`
  return negative ? `-${text}` : text
}

export function negate(value: string): string {
  if (value.startsWith('-')) return value.slice(1)
  return value === '0.00' ? value : `-${value}`
}
