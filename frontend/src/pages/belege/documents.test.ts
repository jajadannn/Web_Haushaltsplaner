import { describe, expect, it } from 'vitest'
import {
  documentsForTransaction, formatSize, hasPending, intervalText, parseContractDraft, parseExtracted, parseReceiptMatch, sourceFor,
  type DocumentItem,
} from './documents'

const doc = (id: number, status: DocumentItem['status'], tx: number | null = null): DocumentItem => ({
  id, kind: 'receipt', original_filename: 'a.pdf', mime: 'application/pdf', size: 1, status, extracted: null, error: null,
  created_at: '', links: tx ? [{ id: 1, transaction_id: tx, fixed_cost_id: null, contract_id: null }] : [],
})

describe('Dokumente', () => {
  it('erkennt wartende Dokumente', () => {
    expect(hasPending([doc(1, 'extracted'), doc(2, 'pending')])).toBe(true)
    expect(hasPending([doc(1, 'failed')])).toBe(false)
    expect(hasPending(undefined)).toBe(false)
  })
  it('filtert Belege je Buchung', () => {
    expect(documentsForTransaction([doc(1, 'extracted', 5), doc(2, 'extracted', 6), doc(3, 'extracted')], 5).map((d) => d.id)).toEqual([1])
  })
  it('liest erkannte Werte und Fundstellen', () => {
    const e = parseExtracted({
      haendler: 'REWE', datum: '2026-01-02', betrag: '12.50', positionen: [{ text: 'Milch', betrag: '1.20' }, { text: 'x' }],
      vertrag: { anbieter: 'Telekom', beitrag: '29.99', rhythmus_monate: 1, kuendigungsfrist: null },
      fundstellen: [{ feld: 'beitrag', seite: 2, zitat: '29,99 € monatlich' }],
    })
    expect(e.merchant).toBe('REWE')
    expect(e.positions).toHaveLength(1)
    expect(e.contract?.provider).toBe('Telekom')
    expect(e.contract?.notice).toBeNull()
    expect(sourceFor(e.sources, 'beitrag')?.page).toBe(2)
    expect(sourceFor(e.sources, 'anbieter')).toBeUndefined()
    expect(parseExtracted(null).contract).toBeNull()
  })
  it('liest Vorschläge', () => {
    expect(parseReceiptMatch({ document_id: 1, transaction_id: 2, amount: '5.00', positions: [] }).transactionId).toBe(2)
    expect(parseContractDraft({ document_id: 1, contract: { anbieter: 'X' }, sources: [] }).contract.provider).toBe('X')
    expect(parseContractDraft({}).contract.amount).toBeNull()
  })
  it('Text für Rhythmus und Größe', () => {
    expect(intervalText(12)).toBe('jährlich')
    expect(intervalText(2)).toBe('alle 2 Monate')
    expect(intervalText(null)).toBeNull()
    expect(formatSize(2048)).toBe('2 KB')
    expect(formatSize(1572864)).toBe('1,5 MB')
  })
})
