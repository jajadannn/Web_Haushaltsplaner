import { fullDate } from '../../lib/dates'
import { toCents } from '../../lib/moneyInput'

/**
 * Status, nächste Rate und monatliche Belastung sind immer der AKTUELLE Stand, die
 * Restschuld gilt zum gewählten Stichtag. Liegt der Zeitraum in der Vergangenheit,
 * wird das ausdrücklich gekennzeichnet.
 */
export function currentStateNote(until: string, currentAsOf: string): string | null {
  return until < currentAsOf ? `aktueller Stand (${fullDate(currentAsOf)})` : null
}

export interface YearInterestLike {
  year: number
  interest: string
  paid: string
  charged: string
}

/** Zinskosten eines Jahres, aufgeteilt in gezahlt und der Schuld zugeschlagen (0 → null). */
export function interestBreakdown(y: YearInterestLike) {
  return {
    year: y.year,
    total: y.interest,
    paid: toCents(y.paid) !== 0n ? y.paid : null,
    charged: toCents(y.charged) !== 0n ? y.charged : null,
  }
}
