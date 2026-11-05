/** Reine Hilfen für „Belege & Verträge“: Dokumente, erkannte Werte, Vorschlags-Payloads. */

type Loose = Record<string, unknown>

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const money = (v: unknown): string | null => (typeof v === 'number' ? String(v) : str(v))

export type DocumentKind = 'receipt' | 'invoice' | 'contract'
export type DocumentStatus = 'pending' | 'extracted' | 'failed'

export const KIND_LABEL: Record<DocumentKind, string> = { receipt: 'Beleg', invoice: 'Rechnung', contract: 'Vertrag' }
export const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: 'Wird ausgelesen …', extracted: 'Ausgelesen', failed: 'Auslesen fehlgeschlagen',
}

export interface DocumentLink {
  id: number
  transaction_id: number | null
  fixed_cost_id: number | null
  contract_id: number | null
}

export interface DocumentItem {
  id: number
  kind: DocumentKind
  original_filename: string
  mime: string
  size: number
  status: DocumentStatus
  extracted: Loose | null
  error: string | null
  created_at: string
  links: DocumentLink[]
}

export const hasPending = (docs: DocumentItem[] | undefined): boolean => !!docs?.some((d) => d.status === 'pending')

/** Belege einer Buchung (über die Verknüpfungen). */
export const documentsForTransaction = (docs: DocumentItem[], transactionId: number): DocumentItem[] =>
  docs.filter((d) => d.links.some((l) => l.transaction_id === transactionId))

export function linkLabel(l: DocumentLink): string {
  if (l.transaction_id != null) return `Buchung #${l.transaction_id}`
  if (l.fixed_cost_id != null) return `Fixkost #${l.fixed_cost_id}`
  if (l.contract_id != null) return `Vertrag #${l.contract_id}`
  return 'Verknüpfung'
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}

export const isImage = (mime: string): boolean => mime.startsWith('image/')
export const isPdf = (mime: string): boolean => mime === 'application/pdf'

export interface Position { text: string; amount: string }
export interface Source { field: string; page: number | null; quote: string }
export interface ContractValues {
  provider: string | null
  amount: string | null
  intervalMonths: number | null
  nextDue: string | null
  notice: string | null
  end: string | null
}

export interface Extracted {
  merchant: string | null
  date: string | null
  amount: string | null
  currency: string | null
  positions: Position[]
  contract: ContractValues | null
  sources: Source[]
}

export function parseContract(raw: unknown): ContractValues | null {
  if (!raw || typeof raw !== 'object') return null
  const c = raw as Loose
  return {
    provider: str(c.anbieter), amount: money(c.beitrag), intervalMonths: num(c.rhythmus_monate),
    nextDue: str(c.naechste_faelligkeit), notice: str(c.kuendigungsfrist), end: str(c.laufzeit_ende),
  }
}

export function parsePositions(raw: unknown): Position[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((p) => {
    if (!p || typeof p !== 'object') return []
    const o = p as Loose
    const amount = money(o.betrag)
    return amount === null ? [] : [{ text: str(o.text) ?? '', amount }]
  })
}

export function parseSources(raw: unknown): Source[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((s) => {
    if (!s || typeof s !== 'object') return []
    const o = s as Loose
    const quote = str(o.zitat)
    return quote ? [{ field: str(o.feld) ?? '', page: num(o.seite), quote }] : []
  })
}

export function parseExtracted(raw: Loose | null | undefined): Extracted {
  const e = raw ?? {}
  return {
    merchant: str(e.haendler), date: str(e.datum), amount: money(e.betrag), currency: str(e.waehrung),
    positions: parsePositions(e.positionen), contract: parseContract(e.vertrag), sources: parseSources(e.fundstellen),
  }
}

/** Fundstelle eines Feldes (Feldname wie im Vertrag: anbieter, beitrag …). */
export const sourceFor = (sources: Source[], field: string): Source | undefined => sources.find((s) => s.field === field)

export const intervalText = (months: number | null): string | null => {
  if (months === null) return null
  if (months === 1) return 'monatlich'
  if (months === 3) return 'vierteljährlich'
  if (months === 6) return 'halbjährlich'
  if (months === 12) return 'jährlich'
  return `alle ${months} Monate`
}

export interface ReceiptMatch {
  documentId: number | null
  transactionId: number | null
  amount: string | null
  date: string | null
  merchant: string | null
  positions: Position[]
}

export function parseReceiptMatch(payload: Loose): ReceiptMatch {
  return {
    documentId: num(payload.document_id), transactionId: num(payload.transaction_id), amount: money(payload.amount),
    date: str(payload.date), merchant: str(payload.merchant), positions: parsePositions(payload.positions),
  }
}

export interface ContractDraft {
  documentId: number | null
  contract: ContractValues
  sources: Source[]
}

export function parseContractDraft(payload: Loose): ContractDraft {
  return {
    documentId: num(payload.document_id),
    contract: parseContract(payload.contract) ?? parseContract({}) as ContractValues,
    sources: parseSources(payload.sources),
  }
}

/** Gehört der Vorschlag zu diesem Dokument? */
export const suggestionDocumentId = (payload: Loose): number | null => num(payload.document_id)

/** Dateiname ohne Pfadanteile für die Anzeige. */
export const ACCEPTED_TYPES = 'application/pdf,image/jpeg,image/png,image/webp'
