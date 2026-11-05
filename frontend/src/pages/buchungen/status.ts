import type { IconName } from '../../ui/Icon'

export type ReviewState = 'needs_review' | 'auto_categorized' | 'confirmed'

/** Symbolik der Prüfstatus: nur `confirmed` gilt als geprüft. */
export function reviewIndicator(state: ReviewState): { kind: 'confirmed' | 'suggested' | 'open'; title: string; icon: IconName } {
  if (state === 'confirmed') return { kind: 'confirmed', title: 'geprüft', icon: 'check' }
  if (state === 'auto_categorized') return { kind: 'suggested', title: 'Vorschlag – noch nicht bestätigt', icon: 'sparkle' }
  return { kind: 'open', title: 'ungeprüft', icon: 'tag' }
}

/**
 * Welche Entfernen-Aktion der Editor anbietet:
 * - delete: nur manuelle Buchung ohne Import- oder Kreditverknüpfung
 * - exclude: importiert oder mit Bankdaten abgeglichen
 * - loan-payment: Kreditzahlung, wird unter Kredite storniert
 */
export function editorMode(tx: { source: string; import_linked: boolean; loan_payment_id?: number | null }): 'delete' | 'exclude' | 'loan-payment' {
  if (tx.source === 'loan' || tx.loan_payment_id != null) return 'loan-payment'
  if (tx.source === 'import' || tx.import_linked) return 'exclude'
  return 'delete'
}
