import { useState } from 'react'
import { api } from '../../api/client'
import { openDocumentFile, useDeleteDocument, useDocumentFileUrl, useDocuments, useLinkDocument, useRetryDocument } from '../../api/documents'
import { SUGGESTION_AREAS, useApiMutation, useSuggestions, useTransactions, type Suggestion } from '../../api/hooks'
import { fullDate, shortDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { EmptyState, ErrorBox, Loading, Money, PageHeader, Tile } from '../../ui/blocks'
import { Button, Checkbox, Segmented, SelectField, TextField } from '../../ui/controls'
import { Icon } from '../../ui/Icon'
import { Confirm, useToast } from '../../ui/overlay'
import { UploadButton } from './AttachDocument'
import {
  formatSize, intervalText, isImage, isPdf, KIND_LABEL, linkLabel, parseContractDraft, parseExtracted, parseReceiptMatch, sourceFor,
  STATUS_LABEL, suggestionDocumentId, type DocumentItem, type DocumentKind,
} from './documents'
import './belege.css'

/**
 * Belege & Verträge: Dateien hochladen, die lokale KI liest sie aus (Status wird neu geladen,
 * solange etwas wartet). Das Detail zeigt die Datei neben den erkannten Werten samt Fundstellen;
 * Vorschläge (Beleg ↔ Buchung, Vertragsentwurf) werden hier übernommen oder abgelehnt.
 */

const STATUS_ICON = { pending: 'clock', extracted: 'check', failed: 'alert' } as const

export function DocumentsPage() {
  const docs = useDocuments()
  const [kind, setKind] = useState<DocumentKind>('receipt')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const list = docs.data ?? []
  const selected = list.find((d) => d.id === selectedId) ?? null

  return (
    <div className="page">
      <PageHeader title="Belege & Verträge">
        <Segmented<DocumentKind> label="Art" value={kind} onChange={setKind}
          options={[{ value: 'receipt', label: 'Beleg' }, { value: 'invoice', label: 'Rechnung' }, { value: 'contract', label: 'Vertrag' }]} />
        <UploadButton kind={kind} label={`${KIND_LABEL[kind]} hochladen`} variant="primary" onUploaded={(d) => setSelectedId(d.id)} />
      </PageHeader>
      <p className="muted">Erlaubt sind PDF, JPEG, PNG und WebP. Die Datei wird lokal ausgelesen; Scans ohne Text lassen sich nicht auslesen.</p>

      {docs.isLoading && <Loading />}
      {docs.isError && <ErrorBox error={docs.error} onRetry={() => docs.refetch()} />}
      {docs.data && list.length === 0 && (
        <EmptyState icon="file" title="Noch keine Belege oder Verträge">Lade eine Quittung, Rechnung oder einen Vertrag hoch.</EmptyState>
      )}
      {list.length > 0 && (
        <div className="docs-layout">
          <ul className="rows docs-list">
            {list.map((d) => (
              <li key={d.id}>
                <button type="button" className={`row-card docs-row${d.id === selectedId ? ' is-selected' : ''}`}
                  aria-pressed={d.id === selectedId} onClick={() => setSelectedId(d.id)}>
                  <span className="row-icon"><Icon name={STATUS_ICON[d.status]} /></span>
                  <span className="row-main">
                    <strong>{d.original_filename}</strong>
                    <span>{KIND_LABEL[d.kind]} · {STATUS_LABEL[d.status]} · {shortDate(d.created_at.slice(0, 10))}</span>
                  </span>
                  {d.links.length > 0 && <span className="muted">{d.links.length}× verknüpft</span>}
                </button>
              </li>
            ))}
          </ul>
          {selected ? <DocumentDetail key={selected.id} doc={selected} onDeleted={() => setSelectedId(null)} />
            : <Tile className="docs-detail"><p className="muted">Eine Datei wählen, um Details zu sehen.</p></Tile>}
        </div>
      )}
    </div>
  )
}

function Preview({ doc }: { doc: DocumentItem }) {
  const file = useDocumentFileUrl(doc.id)
  if (file.error) return <p className="muted">Die Datei lässt sich nicht anzeigen.</p>
  if (!file.url) return <Loading />
  if (isImage(doc.mime)) return <img className="docs-preview" src={file.url} alt={`Vorschau von ${doc.original_filename}`} />
  if (isPdf(doc.mime)) return <iframe className="docs-preview docs-pdf" src={file.url} title={`Vorschau von ${doc.original_filename}`} />
  return <p className="muted">Keine Vorschau für diesen Dateityp.</p>
}

function Value({ label, value, source }: { label: string; value: string | null; source?: { page: number | null; quote: string } }) {
  return (
    <div className="docs-value">
      <dt>{label}</dt>
      <dd>{value ?? <span className="muted">nicht erkannt</span>}</dd>
      {source && <dd className="docs-source">„{source.quote}“{source.page != null ? ` (Seite ${source.page})` : ''}</dd>}
    </div>
  )
}

function DocumentDetail({ doc, onDeleted }: { doc: DocumentItem; onDeleted: () => void }) {
  const toast = useToast()
  const [confirm, setConfirm] = useState(false)
  const remove = useDeleteDocument(() => { toast.ok('Datei gelöscht'); setConfirm(false); onDeleted() })
  const retry = useRetryDocument(() => toast.ok('Wird erneut ausgelesen'))
  const e = parseExtracted(doc.extracted)
  const contract = e.contract
  const pick = (field: string) => sourceFor(e.sources, field)

  return (
    <Tile className="docs-detail" title={doc.original_filename}
      action={<Button variant="ghost" icon="download" onClick={() => openDocumentFile(doc.id).catch(toast.error)}>Original öffnen</Button>}>
      <p className="muted">{KIND_LABEL[doc.kind]} · {formatSize(doc.size)} · hochgeladen am {fullDate(doc.created_at.slice(0, 10))}</p>
      <div className="docs-compare">
        <div className="docs-original"><Preview doc={doc} /></div>
        <div className="docs-extracted">
          {doc.status === 'pending' && <p role="status"><Icon name="clock" size={18} /> Wird ausgelesen …</p>}
          {doc.status === 'failed' && (
            <>
              <p className="field-error" role="alert"><Icon name="alert" size={18} /> {doc.error || 'Das Auslesen ist fehlgeschlagen.'}</p>
              <Button icon="refresh" disabled={retry.isPending}
                onClick={() => retry.mutate(doc.id, { onError: toast.error })}>Erneut auslesen</Button>
            </>
          )}
          {doc.status === 'extracted' && (
            <>
              <h3>Erkannte Werte</h3>
              <dl className="docs-values">
                <Value label="Händler" value={e.merchant} source={pick('haendler')} />
                <Value label="Datum" value={e.date ? fullDate(e.date) : null} source={pick('datum')} />
                <Value label="Betrag" value={e.amount ? formatEuro(e.amount) : null} source={pick('betrag')} />
                {contract && (
                  <>
                    <Value label="Anbieter" value={contract.provider} source={pick('anbieter')} />
                    <Value label="Beitrag" value={contract.amount ? formatEuro(contract.amount) : null} source={pick('beitrag')} />
                    <Value label="Rhythmus" value={intervalText(contract.intervalMonths)} source={pick('rhythmus_monate')} />
                    <Value label="Nächste Fälligkeit" value={contract.nextDue ? fullDate(contract.nextDue) : null} source={pick('naechste_faelligkeit')} />
                    <Value label="Kündigungsfrist" value={contract.notice} source={pick('kuendigungsfrist')} />
                    <Value label="Laufzeit bis" value={contract.end ? fullDate(contract.end) : null} source={pick('laufzeit_ende')} />
                  </>
                )}
              </dl>
              {e.positions.length > 0 && (
                <>
                  <h3>Positionen</h3>
                  <ul className="docs-positions">
                    {e.positions.map((p, i) => <li key={i}><span>{p.text}</span><Money value={p.amount} /></li>)}
                  </ul>
                </>
              )}
              {e.sources.length > 0 && (
                <>
                  <h3>Fundstellen</h3>
                  <ul className="docs-sources">
                    {e.sources.map((s, i) => (
                      <li key={i}><strong>{s.field}</strong>{s.page != null ? `, Seite ${s.page}` : ''}: „{s.quote}“</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </div>

      <DocumentSuggestions doc={doc} />

      <h3>Verknüpfungen</h3>
      {doc.links.length === 0 ? <p className="muted">Noch mit nichts verknüpft.</p> : (
        <ul className="docs-links">{doc.links.map((l) => <li key={l.id}>{linkLabel(l)}</li>)}</ul>
      )}
      <LinkToTransaction doc={doc} />

      <div className="suggestion-actions">
        <Button variant="danger" icon="trash" onClick={() => setConfirm(true)}>Löschen</Button>
      </div>
      <Confirm open={confirm} title="Datei löschen?" text={`„${doc.original_filename}“ und die Verknüpfungen werden endgültig gelöscht.`}
        confirmLabel="Löschen" busy={remove.isPending} onCancel={() => setConfirm(false)}
        onConfirm={() => remove.mutate(doc.id, { onError: (err) => { setConfirm(false); toast.error(err) } })} />
    </Tile>
  )
}

function useDocumentSuggestions(kind: string, docId: number): Suggestion[] {
  const list = useSuggestions({ kind })
  return (list.data ?? []).filter((s) => s.status === 'open' && suggestionDocumentId(s.payload) === docId)
}

function DocumentSuggestions({ doc }: { doc: DocumentItem }) {
  const toast = useToast()
  const receipts = useDocumentSuggestions('receipt_match', doc.id)
  const drafts = useDocumentSuggestions('contract_draft', doc.id)
  const [createFixed, setCreateFixed] = useState(true)
  const accept = useApiMutation(
    ({ id, body }: { id: number; body?: Record<string, unknown> }) => api.post(`/suggestions/${id}/accept`, body), SUGGESTION_AREAS)
  const reject = useApiMutation((id: number) => api.post(`/suggestions/${id}/reject`), SUGGESTION_AREAS)
  const busy = accept.isPending || reject.isPending
  const take = (s: Suggestion, ok: string, body?: Record<string, unknown>) =>
    accept.mutate({ id: s.id, body }, { onSuccess: () => toast.ok(ok), onError: toast.error })
  const drop = (s: Suggestion) => reject.mutate(s.id, { onSuccess: () => toast.ok('Vorschlag abgelehnt'), onError: toast.error })

  if (receipts.length + drafts.length === 0) return null
  return (
    <section aria-label="Vorschläge zu dieser Datei">
      <h3>Vorschläge</h3>
      <ul className="suggestion-list">
        {receipts.map((s) => {
          const m = parseReceiptMatch(s.payload)
          return (
            <li key={s.id} className="suggestion-card">
              <p><Icon name="file" size={18} /> Passt zur Buchung{m.merchant ? <> <strong>{m.merchant}</strong></> : null}
                {m.amount ? <> über {formatEuro(m.amount)}</> : null}{m.date ? <> vom {shortDate(m.date)}</> : null}.</p>
              {s.reason && <p className="muted">{s.reason}</p>}
              <div className="suggestion-actions">
                <Button variant="primary" icon="check" disabled={busy} onClick={() => take(s, 'Beleg verknüpft')}>Verknüpfen</Button>
                <Button disabled={busy} onClick={() => drop(s)}>Ablehnen</Button>
              </div>
            </li>
          )
        })}
        {drafts.map((s) => {
          const c = parseContractDraft(s.payload).contract
          return (
            <li key={s.id} className="suggestion-card">
              <p><Icon name="sparkle" size={18} /> Vertrag erkannt: <strong>{c.provider ?? 'Anbieter unbekannt'}</strong>
                {c.amount ? <>, {formatEuro(c.amount)}{c.intervalMonths ? ` ${intervalText(c.intervalMonths)}` : ''}</> : null}</p>
              <Checkbox label="Dazu eine Fixkost anlegen" checked={createFixed} onChange={setCreateFixed} />
              {s.reason && <p className="muted">{s.reason}</p>}
              <div className="suggestion-actions">
                <Button variant="primary" icon="check" disabled={busy}
                  onClick={() => take(s, 'Vertrag angelegt', { create_fixed_cost: createFixed })}>Vertrag anlegen</Button>
                <Button disabled={busy} onClick={() => drop(s)}>Ablehnen</Button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function LinkToTransaction({ doc }: { doc: DocumentItem }) {
  const toast = useToast()
  const [search, setSearch] = useState('')
  const [txId, setTxId] = useState('')
  const found = useTransactions({ search: search.trim() || undefined, limit: 20 })
  const link = useLinkDocument(() => { toast.ok('Mit Buchung verknüpft'); setTxId('') })
  const linked = new Set(doc.links.map((l) => l.transaction_id))
  const options = (found.data?.items ?? []).filter((t) => !linked.has(t.id)).map((t) => ({
    value: String(t.id),
    label: `${shortDate(t.booking_date)} · ${t.counterparty || t.description} · ${formatEuro(t.amount)}`,
  }))
  return (
    <div className="docs-link-form">
      <TextField label="Buchung suchen" value={search} onChange={setSearch} placeholder="Empfänger oder Text" />
      <SelectField label="Buchung" value={txId} onChange={setTxId} placeholder="Buchung wählen" options={options} />
      <Button icon="check" disabled={!txId} busy={link.isPending}
        onClick={() => link.mutate({ id: doc.id, target: { transaction_id: Number(txId) } }, { onError: toast.error })}>
        Mit Buchung verknüpfen
      </Button>
    </div>
  )
}
