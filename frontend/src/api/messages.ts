/**
 * Fehlercodes der API in verständliche Sätze übersetzen.
 *
 * Fachliche Fehler bringen schon einen deutschen Satz vom Backend mit – der wird gezeigt.
 * Nur allgemeine Codes bekommen hier einen eigenen Text, dazu die Feldnamen bei
 * Validierungsfehlern.
 */

const GENERIC: Record<string, string> = {
  network: 'Keine Verbindung zum Finanzplaner. Läuft der Server, und ist das Gerät im Heimnetz?',
  local_network_only: 'Der Finanzplaner ist nur im Heimnetz erreichbar.',
  profile_required: 'Bitte zuerst ein Profil wählen.',
  profile_not_found: 'Dieses Profil gibt es nicht mehr. Bitte ein anderes wählen.',
  not_found: 'Das gibt es nicht (mehr) – vielleicht wurde es gerade gelöscht.',
  conflict: 'Das gibt es schon.',
  internal_error: 'Im Finanzplaner ist ein Fehler aufgetreten. Bitte noch einmal versuchen.',
  payment_followed_by_skip: 'Zuerst die spätere Ratenpause zurücknehmen.',
  charge_has_later_payments: 'Nach dieser Belastung wurden Zahlungen gebucht – zuerst diese stornieren.',
  suggestion_not_open: 'Dieser Vorschlag wurde schon bearbeitet.',
  suggestion_stale: 'Dieser Vorschlag passt nicht mehr zu den aktuellen Buchungen. Bitte „Jetzt prüfen“ ausführen.',
  changed_since: 'Das wurde inzwischen weiter geändert und lässt sich nicht mehr zurücknehmen.',
  payment_already_linked: 'Diese Buchung ist schon einer Fixkost zugeordnet.',
  due_month_already_paid: 'Für diesen Monat ist die Fixkost schon als bezahlt verknüpft.',
  payment_not_linkable: 'Diese Buchung lässt sich dieser Fixkost nicht zuordnen.',
  setting_unknown: 'Diese Einstellung gibt es nicht.',
  setting_invalid: 'Dieser Wert ist für die Einstellung nicht erlaubt.',
  file_too_large: 'Die Datei ist zu groß.',
  http_500: 'Im Finanzplaner ist ein Fehler aufgetreten. Bitte noch einmal versuchen.',
  http_502: 'Der Finanzplaner antwortet gerade nicht.',
  http_503: 'Der Finanzplaner ist gerade nicht bereit.',
}

/** Feldnamen der API → Beschriftung im Formular */
export const FIELD_LABELS: Record<string, string> = {
  amount: 'Betrag', booking_date: 'Datum', value_date: 'Wertstellung', account_id: 'Konto',
  category_id: 'Kategorie', description: 'Text', counterparty: 'Empfänger', name: 'Name',
  opening_balance: 'Anfangssaldo', opening_balance_date: 'Stichtag', iban: 'IBAN', due_day: 'Fälligkeitstag',
  match_text: 'Suchtext', start_date: 'Beginn', end_date: 'Ende', pattern: 'Muster', priority: 'Priorität',
  annual_interest_rate: 'Zinssatz', current_balance: 'Restschuld', balance_date: 'Stichtag',
  first_due_date: 'Erste Fälligkeit', term_months: 'Laufzeit', installment_amount: 'Rate', splits: 'Aufteilung',
  interval_months: 'Rhythmus',
  from_account_id: 'Von Konto', to_account_id: 'Auf Konto', target_category_id: 'Kategorie',
}

interface ValidationDetail {
  loc?: (string | number)[]
  msg?: string
}

function validationText(details: unknown): string | null {
  if (!Array.isArray(details) || details.length === 0) return null
  const fields = (details as ValidationDetail[])
    .map((d) => d.loc?.filter((part) => typeof part === 'string' && part !== 'body').at(-1))
    .filter((f): f is string => typeof f === 'string')
    .map((f) => FIELD_LABELS[f] ?? f)
  const unique = [...new Set(fields)]
  if (unique.length === 0) return null
  return unique.length === 1
    ? `Bitte „${unique[0]}“ prüfen.`
    : `Bitte diese Felder prüfen: ${unique.map((f) => `„${f}“`).join(', ')}.`
}

export function messageFor(code: string, serverMessage?: string, details?: unknown): string {
  if (code === 'validation_error') {
    return validationText(details) ?? serverMessage ?? 'Die Eingabe ist ungültig.'
  }
  if (GENERIC[code] && (!serverMessage || code.startsWith('http_') || code === 'network' || code === 'internal_error')) {
    return GENERIC[code]
  }
  return serverMessage || GENERIC[code] || 'Das hat nicht geklappt.'
}

/** Feld → Fehlertext, damit Formulare den Fehler am richtigen Feld zeigen können. */
export function fieldErrors(details: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  if (!Array.isArray(details)) return out
  for (const d of details as ValidationDetail[]) {
    const field = d.loc?.filter((part) => typeof part === 'string' && part !== 'body').at(-1)
    if (typeof field === 'string' && !out[field]) out[field] = 'Bitte prüfen'
  }
  return out
}
