import { describe, expect, it } from 'vitest'
import { editorMode, reviewIndicator } from './status'

describe('reviewIndicator', () => {
  it('unterscheidet die drei Zustände', () => {
    expect(reviewIndicator('confirmed').title).toBe('geprüft')
    expect(reviewIndicator('auto_categorized').title).toBe('Vorschlag – noch nicht bestätigt')
    expect(reviewIndicator('needs_review').title).toBe('ungeprüft')
    expect(reviewIndicator('auto_categorized').kind).not.toBe(reviewIndicator('confirmed').kind)
  })
})

const base = { source: 'manual', import_linked: false, loan_payment_id: null } as const
describe('editorMode', () => {
  it('manuell ohne Verknüpfung: löschen', () => expect(editorMode(base)).toBe('delete'))
  it('importverknüpfte manuelle Buchung: ausschließen', () =>
    expect(editorMode({ ...base, import_linked: true })).toBe('exclude'))
  it('Import: ausschließen', () => expect(editorMode({ ...base, source: 'import' })).toBe('exclude'))
  it('Kreditzahlung: weder löschen noch ausschließen', () =>
    expect(editorMode({ ...base, loan_payment_id: 4 })).toBe('loan-payment'))
  it('Kreditbuchung (source=loan)', () => expect(editorMode({ ...base, source: 'loan' })).toBe('loan-payment'))
})
