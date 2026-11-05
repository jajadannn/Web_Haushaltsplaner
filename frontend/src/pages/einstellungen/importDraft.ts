/** Reine Hilfen für den Importassistenten: Spaltenrollen ↔ column_map des Importprofils. */

export type ColumnSpec = string | string[] | Record<string, unknown>
export type ColumnMap = Record<string, ColumnSpec>
/** Spaltenname aus der Kopfzeile → Rolle ('' = nicht verwendet) */
export type Assignment = Record<string, string>

export const ROLE_LABELS: Record<string, string> = {
  booking_date: 'Buchungsdatum',
  value_date: 'Wertstellung',
  amount: 'Betrag',
  debit: 'Soll (Ausgaben)',
  credit: 'Haben (Einnahmen)',
  indicator: 'Soll/Haben-Kennzeichen',
  description: 'Verwendungszweck',
  counterparty: 'Empfänger / Auftraggeber',
  counterparty_iban: 'IBAN der Gegenseite',
  external_id: 'Bank-Referenz',
  own_account: 'eigene IBAN',
  currency: 'Währung',
  status: 'Status',
}

/** Auswahl für eine Spalte: erste Option = nicht verwendet. */
export const ROLE_OPTIONS = [
  { value: '', label: 'nicht verwenden' },
  ...Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label })),
]

/** Rollen, die mehrere Spalten bündeln dürfen (Texte werden hintereinander gesetzt). */
const MULTI = new Set(['description'])

export function assignmentFromColumnMap(map: ColumnMap, header: string[]): Assignment {
  const out: Assignment = {}
  for (const [role, spec] of Object.entries(map)) {
    const columns = typeof spec === 'string' ? [spec] : Array.isArray(spec) ? spec : []
    for (const column of columns) {
      if (header.includes(column)) out[column] = role
    }
  }
  return out
}

export function columnMapFromAssignment(assignment: Assignment, header: string[], previous: ColumnMap): ColumnMap {
  const byRole = new Map<string, string[]>()
  for (const column of header) {
    const role = assignment[column]
    if (!role) continue
    byRole.set(role, [...(byRole.get(role) ?? []), column])
  }
  const out: ColumnMap = {}
  // Sonderformen (z. B. Empfänger je nach Richtung) bleiben, solange die Rolle nicht neu vergeben wird
  for (const [role, spec] of Object.entries(previous)) {
    if (spec && typeof spec === 'object' && !Array.isArray(spec) && !byRole.has(role)) out[role] = spec
  }
  // Reihenfolge wie in der Datei
  const roles = [...byRole.keys()].sort((a, b) => header.indexOf(byRole.get(a)![0]) - header.indexOf(byRole.get(b)![0]))
  for (const role of roles) {
    const columns = byRole.get(role)!
    out[role] = MULTI.has(role) && columns.length > 1 ? columns : columns[0]
  }
  return out
}

/** Ist die Rolle dieser Spalte laut Server unsicher? (`uncertain` nennt Rollen, dazu `date_format`.) */
export function isUncertainColumn(column: string, map: ColumnMap, uncertain: string[]): boolean {
  return Object.entries(map).some(([role, spec]) => {
    const flagged = uncertain.includes(role) || (role === 'booking_date' && uncertain.includes('date_format'))
    if (!flagged) return false
    return typeof spec === 'string' ? spec === column : Array.isArray(spec) && spec.includes(column)
  })
}

export const SIGN_MODE_LABELS: Record<string, string> = {
  signed: 'Eine Betragsspalte mit Vorzeichen',
  debit_credit_columns: 'Getrennte Spalten für Soll und Haben',
  indicator_column: 'Betrag mit Kennzeichen (z. B. S/H)',
}

export interface DraftOptions {
  column_map: ColumnMap
  delimiter: string
  encoding: string
  skip_rows: number
  date_format: string
  decimal_sep: string
  thousands_sep: string
  sign_mode: string
  debit_indicators: string[]
  pending_values: string[]
}

export interface DraftResult {
  options: DraftOptions
  header: string[]
  roles: ColumnMap
  uncertain: string[]
  unassigned: string[]
  rows_parsed: number
  errors: { row_no: number; message: string }[]
  preview: { row_no: number; booking_date: string | null; amount: string | null; counterparty: string | null; description: string | null }[]
  statement_account: string | null
  safe: boolean
  ai_used: boolean
}
