import type { Account } from '../../api/hooks'

/** Beschriftungen, die mehrere Seiten teilen (Einstellungen, Kredite, Buchungen). */

export type AccountType = Account['type']

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  checking: 'Girokonto',
  savings: 'Tagesgeld / Sparkonto',
  cash: 'Bargeld',
  credit_card: 'Kreditkarte',
  loan: 'Kreditkonto',
}

/** Typen, die in den Einstellungen angelegt werden dürfen (Kreditkonten entstehen auf der Kredite-Seite). */
export const EDITABLE_ACCOUNT_TYPES: AccountType[] = ['checking', 'savings', 'cash', 'credit_card']

export const MATCH_TYPE_LABELS = { contains: 'enthält', regex: 'regulärer Ausdruck' } as const
export const MATCH_FIELD_LABELS = {
  any: 'Empfänger oder Text',
  description: 'Text',
  counterparty: 'Empfänger',
} as const
