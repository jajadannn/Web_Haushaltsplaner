/** Reine Hilfen für Anbieter und die KI-Anreicherung von Vorschlägen. */

export const ALIAS_TYPE_LABELS: Record<string, string> = { iban: 'IBAN', reference: 'Referenz', name: 'Name' }

export interface AliasDraft {
  match_type: 'iban' | 'name'
  value: string
}

/** Merkmale, die beim „Als Anbieter merken“ aus einer Buchung entstehen: IBAN (falls vorhanden) und Name. */
export function aliasesFromCounterparty(counterparty: string | null | undefined, iban: string | null | undefined): AliasDraft[] {
  const out: AliasDraft[] = []
  const cleanIban = (iban ?? '').replace(/\s+/g, '')
  if (cleanIban) out.push({ match_type: 'iban', value: cleanIban })
  const name = (counterparty ?? '').trim()
  if (name) out.push({ match_type: 'name', value: name })
  return out
}

export interface AiHint {
  provider: string | null
  /** false = eher regelmäßiger Konsum; null = unbekannt */
  obligation: boolean | null
}

export function parseAiHint(payload: Record<string, unknown>): AiHint | null {
  const ai = payload.ai
  if (typeof ai !== 'object' || ai === null || Array.isArray(ai)) return null
  const o = ai as Record<string, unknown>
  return {
    provider: typeof o.anbieter === 'string' && o.anbieter ? o.anbieter : null,
    obligation: typeof o.ist_verpflichtung === 'boolean' ? o.ist_verpflichtung : null,
  }
}
