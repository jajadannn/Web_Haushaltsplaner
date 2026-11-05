/** Ergebnis von POST /entries/parse → Werte für den Entwurf im Plus-Dialog (reine Umrechnung). */
import type { ParsedEntry } from '../api/ai'

export type MissingField = 'amount' | 'date' | 'account'

export interface EntryDraft {
  /** null = Betrag unbekannt, Modus bleibt wie er ist */
  mode: 'expense' | 'income' | null
  /** immer positiv */
  amount: string | null
  date: string | null
  accountId: string | null
  categoryId: number | null
  text: string | null
  missing: MissingField[]
  duplicate: ParsedEntry['possible_duplicate']
}

const FIELDS: MissingField[] = ['amount', 'date', 'account']

export function draftFromParsed(p: ParsedEntry): EntryDraft {
  const raw = p.amount === null || p.amount === undefined ? null : String(p.amount)
  const negative = raw?.startsWith('-') ?? false
  return {
    mode: raw === null ? null : negative ? 'expense' : 'income',
    amount: raw === null ? null : negative ? raw.slice(1) : raw,
    date: p.booking_date,
    accountId: p.account_id === null ? null : String(p.account_id),
    categoryId: p.category_id,
    text: p.description,
    missing: FIELDS.filter((f) => p.questions.includes(f)),
    duplicate: p.possible_duplicate,
  }
}
