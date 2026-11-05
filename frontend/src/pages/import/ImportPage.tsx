import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  MONEY_AREAS, useAccounts, useApiMutation, useImportProfiles, useProfileQuery,
  type ImportBatch, type ImportRow,
} from '../../api/hooks'
import { fullDate, shortDate, standLabel } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, SelectField } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, PageHeader } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { mergeBatches, pickSelected } from './batches'
import './import.css'

/**
 * Import (Entwurf A): Upload-Kachel oben, darunter die Importe als Zeilen; der gewählte
 * Import klappt mit Reitern auf. Offen sind nur „unklar“ und „vor Stichtag“ – erst wenn
 * alle geklärt sind, lässt sich der Import abschließen. Neue Zeilen übernimmt das
 * Abschließen, Dubletten bleiben draußen.
 */

const IMPORT_AREAS = [...MONEY_AREAS, 'imports'] as const
const PAGE = 30
const MAX_LIMIT = 200
const BUSY: ImportBatch['status'][] = ['queued', 'processing']

const STATUS: Record<ImportBatch['status'], { label: string; tone: string; icon: 'clock' | 'check' | 'alert' | 'refresh' }> = {
  queued: { label: 'wartet', tone: 'muted', icon: 'clock' },
  processing: { label: 'wird verarbeitet', tone: 'muted', icon: 'refresh' },
  awaiting_review: { label: 'Klärung nötig', tone: 'due', icon: 'clock' },
  done: { label: 'erledigt', tone: 'paid', icon: 'check' },
  failed: { label: 'fehlgeschlagen', tone: 'overdue', icon: 'alert' },
}

function counts(b: ImportBatch): string {
  if (b.status === 'done') return `${b.rows_new} übernommen${b.rows_duplicate ? ` · ${b.rows_duplicate} Dubletten` : ''}`
  if (BUSY.includes(b.status)) return ''
  if (b.status === 'failed') return `${b.errors.length} ${b.errors.length === 1 ? 'Fehler' : 'Fehler'}`
  // Neu/Dubletten zählt das Backend erst beim Abschließen – vorher Zeilen gesamt und offene
  const parts = [`${b.rows_total} ${b.rows_total === 1 ? 'Zeile' : 'Zeilen'}`]
  if (b.rows_review) parts.push(`${b.rows_review} unklar`)
  return parts.join(' · ')
}

function errorText(error: unknown): string {
  if (typeof error === 'string') return error
  if (error && typeof error === 'object') {
    const e = error as Record<string, unknown>
    const where = e.row ?? e.row_no ?? e.line
    const text = String(e.message ?? e.msg ?? e.error ?? e.code ?? JSON.stringify(e))
    return where !== undefined ? `Zeile ${where}: ${text}` : text
  }
  return String(error)
}

export function ImportPage() {
  const [params, setParams] = useSearchParams()
  const selectedId = Number(params.get('id')) || null
  // Verlauf: neueste Importe, per „Ältere laden“ erweiterbar (die API erlaubt höchstens 200)
  const [limit, setLimit] = useState(PAGE)
  // Nur neu laden, solange ein Import wartet oder verarbeitet wird
  const refetchInterval = (data: ImportBatch[] | ImportBatch | undefined) =>
    ([] as (ImportBatch | undefined)[]).concat(data).some((b) => b && BUSY.includes(b.status)) ? 2500 : false
  const batches = useProfileQuery<ImportBatch[]>('imports', '/imports', { limit }, { refetchInterval })
  // Offene Importe hängen nicht an der Historienbegrenzung
  const openBatches = useProfileQuery<ImportBatch[]>('imports', '/imports', { status: 'awaiting_review', limit: MAX_LIMIT })
  // Der gewählte Import wird einzeln geladen – er muss nicht unter den neuesten stehen
  const chosen = useProfileQuery<ImportBatch>('imports', `/imports/${selectedId}`, undefined, {
    enabled: selectedId !== null, refetchInterval,
  })
  const list = mergeBatches(batches.data, openBatches.data, chosen.data ? [chosen.data] : undefined)
  const anyBusy = list.some((b) => BUSY.includes(b.status))
  const selected = pickSelected(list, selectedId, chosen.data)
  const canLoadMore = (batches.data?.length ?? 0) >= limit && limit < MAX_LIMIT

  return (
    <div className="page import-page">
      <PageHeader title="Import" />
      <UploadTile onUploaded={(b) => setParams({ id: String(b.id) })} />

      {batches.isLoading && <Loading />}
      {batches.isError && <ErrorBox error={batches.error} onRetry={() => batches.refetch()} />}
      {batches.isSuccess && list.length === 0 && (
        <div className="tile">
          <EmptyState icon="import" title="Noch nichts importiert">
            Lade einen Kontoauszug deiner Bank hoch (CSV, OFX oder MT940). Doppelte Buchungen werden erkannt,
            unklare Fälle legst du hier selbst fest.
          </EmptyState>
        </div>
      )}

      {list.length > 0 && (
        <ul className="rows import-list">
          {list.map((b) => {
            const s = STATUS[b.status]
            const open = b.id === selected?.id
            return (
              <li key={b.id}>
                <button type="button" className={`row-card import-row${open ? ' is-open' : ''}`} aria-expanded={open}
                  onClick={() => setParams(open ? {} : { id: String(b.id) })}>
                  <Icon name={open ? 'chevronDown' : 'chevronRight'} />
                  <span className="row-main">
                    <strong>{b.original_filename}</strong>
                    <span>{b.source === 'watcher' ? 'Watch-Ordner' : 'Upload'} · {standLabel(b.created_at).replace(' · ', ' ')}</span>
                  </span>
                  <span className="import-counts">{counts(b)}</span>
                  <span className={`import-status is-${s.tone}`}>
                    <Icon name={s.icon} size={20} className={b.status === 'processing' ? 'spin' : ''} />
                    {s.label}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {canLoadMore && (
        <div className="import-more">
          <Button variant="secondary" icon="refresh" busy={batches.isFetching} onClick={() => setLimit((l) => Math.min(l + PAGE, MAX_LIMIT))}>
            Ältere laden
          </Button>
        </div>
      )}
      {anyBusy && <ProcessHint />}
      {selectedId !== null && chosen.isError && !selected && <ErrorBox error={chosen.error} onRetry={() => chosen.refetch()} />}

      {selected && <BatchDetail key={selected.id} batch={selected} />}
    </div>
  )
}

/** Datei wählen oder hineinziehen, Profil und Konto, hochladen. */
function UploadTile({ onUploaded }: { onUploaded: (b: ImportBatch) => void }) {
  const toast = useToast()
  const profiles = useImportProfiles()
  const accounts = useAccounts()
  const [chosenProfile, setProfileId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const list = profiles.data ?? []

  // Ohne eigene Wahl das erste Profil
  const profileId = chosenProfile || (list[0] ? String(list[0].id) : '')

  const profile = list.find((p) => String(p.id) === profileId)
  const bankAccounts = (accounts.data ?? []).filter((a) => a.type !== 'loan' && !a.archived_at
    && (!profile || a.institution_id === profile.institution_id))

  const upload = useApiMutation((file: File) => {
    const form = new FormData()
    form.append('file', file)
    form.append('import_profile_id', profileId)
    if (accountId) form.append('account_id', accountId)
    return api.upload<ImportBatch>('/imports', form)
  }, ['imports'])

  const send = (file: File | undefined) => {
    if (!file) return
    if (!profileId) {
      toast.error(new Error('Bitte zuerst ein Importprofil anlegen (Einstellungen › Importprofile).'))
      return
    }
    upload.mutate(file, {
      onSuccess: (b) => {
        toast.ok(b.already_imported ? 'Diese Datei wurde schon importiert – der vorhandene Import ist geöffnet.' : `„${file.name}“ hochgeladen`)
        onUploaded(b)
      },
      onError: toast.error,
    })
    if (input.current) input.current.value = ''
  }

  if (profiles.isSuccess && list.length === 0) {
    return (
      <div className="tile">
        <EmptyState icon="upload" title="Zuerst ein Importprofil anlegen"
          action={<Link className="btn btn-primary" to="/einstellungen/importprofile">Importprofil anlegen</Link>}>
          Ein Importprofil beschreibt das Dateiformat deiner Bank (z. B. Spalten einer CSV). Es wird einmal je Bank angelegt.
        </EmptyState>
      </div>
    )
  }

  return (
    <div
      className={`upload-tile${dragging ? ' is-dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        send(e.dataTransfer.files[0])
      }}
    >
      <button type="button" className="upload-drop" onClick={() => input.current?.click()} disabled={upload.isPending}>
        <Icon name="upload" size={40} />
        <span>
          <strong>{upload.isPending ? 'Wird hochgeladen …' : 'Kontoauszug hierher ziehen oder Datei wählen'}</strong>
          <small>CSV, OFX oder MT940 · bis 10 MB</small>
        </span>
      </button>
      <input ref={input} type="file" accept=".csv,.txt,.ofx,.qfx,.sta,.mt940" hidden onChange={(e) => send(e.target.files?.[0])} />
      <div className="upload-options">
        <SelectField label="Importprofil" value={profileId} onChange={setProfileId}
          options={list.map((p) => ({ value: String(p.id), label: `${p.name} (${p.format.toUpperCase()})` }))} />
        <SelectField label="Konto" value={accountId} onChange={setAccountId} placeholder="automatisch (per IBAN)"
          options={bankAccounts.map((a) => ({ value: String(a.id), label: a.name }))} />
      </div>
    </div>
  )
}

/** Wartet etwas länger als ein paar Sekunden: Worker läuft vermutlich nicht – selbst anstoßen. */
function ProcessHint() {
  const toast = useToast()
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setShow(true), 8000)
    return () => window.clearTimeout(t)
  }, [])
  const run = useApiMutation(() => api.post<{ processed: number }>('/imports/process'), [...IMPORT_AREAS])
  if (!show) return null
  return (
    <p className="process-hint">
      <Icon name="info" size={20} />
      Der Import wartet noch. Läuft der Import-Dienst nicht, kannst du ihn hier anstoßen.
      <Button variant="secondary" icon="refresh" busy={run.isPending}
        onClick={() => run.mutate(undefined, { onSuccess: (r) => toast.ok(`${r.processed} verarbeitet`), onError: toast.error })}>
        Jetzt verarbeiten
      </Button>
    </p>
  )
}

type Tab = 'open' | 'new' | 'duplicate' | 'skipped'

function BatchDetail({ batch }: { batch: ImportBatch }) {
  const toast = useToast()
  const accounts = useAccounts()
  const rows = useProfileQuery<ImportRow[]>('imports', `/imports/${batch.id}/rows`, undefined, {
    enabled: batch.status === 'awaiting_review' || batch.status === 'done',
  })
  const all = rows.data ?? []
  const isOpen = (r: ImportRow) => (r.decision === 'ambiguous' || r.decision === 'before_opening') && !r.resolution
  const groups: Record<Tab, ImportRow[]> = {
    open: all.filter(isOpen),
    new: all.filter((r) => r.decision === 'new' || r.resolution === 'import'),
    duplicate: all.filter((r) => (r.decision === 'duplicate' && !r.resolution) || r.resolution === 'duplicate'),
    skipped: all.filter((r) => r.decision === 'skipped' || r.resolution === 'skip'),
  }
  // Ohne eigene Wahl: „Unklar“, solange es offene Zeilen gibt, sonst „Neu“
  const [chosenTab, setTab] = useState<Tab | null>(null)
  const hadOpen = all.some((r) => r.decision === 'ambiguous' || r.decision === 'before_opening')
  const tab: Tab = chosenTab ?? (hadOpen && batch.status !== 'done' ? 'open' : 'new')

  const resolve = useApiMutation((body: Record<string, unknown>) => api.post(`/imports/${batch.id}/rows/resolve`, body), ['imports'])
  const commit = useApiMutation(() => api.post<ImportBatch>(`/imports/${batch.id}/commit`), [...IMPORT_AREAS])
  const retry = useApiMutation((accountId: string) => api.post(`/imports/${batch.id}/retry`, accountId ? { account_id: Number(accountId) } : {}), [...IMPORT_AREAS])
  const [retryAccount, setRetryAccount] = useState('')

  const act = (body: Record<string, unknown>, ok: string) =>
    resolve.mutate(body, { onSuccess: () => toast.ok(ok), onError: toast.error })

  if (batch.status === 'failed') {
    return (
      <section className="tile batch-detail">
        <h2 className="batch-title">Import fehlgeschlagen</h2>
        <ul className="batch-errors">
          {batch.errors.slice(0, 20).map((e, i) => <li key={i}>{errorText(e)}</li>)}
          {batch.errors.length > 20 && <li>… und {batch.errors.length - 20} weitere</li>}
        </ul>
        <p className="muted">Profil in den Einstellungen anpassen oder ein Konto festlegen, dann erneut versuchen.</p>
        <div className="batch-actions">
          <SelectField label="Konto (optional)" value={retryAccount} onChange={setRetryAccount} placeholder="wie bisher"
            options={(accounts.data ?? []).filter((a) => a.type !== 'loan' && !a.archived_at).map((a) => ({ value: String(a.id), label: a.name }))} />
          <Button variant="primary" icon="refresh" busy={retry.isPending}
            onClick={() => retry.mutate(retryAccount, { onSuccess: () => toast.ok('Import wird erneut verarbeitet'), onError: toast.error })}>
            Erneut versuchen
          </Button>
        </div>
      </section>
    )
  }
  if (BUSY.includes(batch.status)) {
    return <section className="tile batch-detail"><Loading label="Der Kontoauszug wird gelesen und mit vorhandenen Buchungen verglichen …" /></section>
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'open', label: `Unklar (${groups.open.length})` },
    { id: 'new', label: `Neu (${groups.new.length})` },
    { id: 'duplicate', label: `Dubletten (${groups.duplicate.length})` },
    { id: 'skipped', label: `Übersprungen (${groups.skipped.length})` },
  ]
  const shown = groups[tab]
  const openAmbiguous = groups.open.filter((r) => r.decision === 'ambiguous').length
  const done = batch.status === 'done'

  return (
    <section className="tile batch-detail" aria-label={`Import ${batch.original_filename}`}>
      <div className="batch-tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
            className={tab === t.id ? 'is-active' : ''} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {rows.isLoading && <Loading />}
      {rows.isError && <ErrorBox error={rows.error} onRetry={() => rows.refetch()} />}
      {rows.isSuccess && shown.length === 0 && (
        <EmptyState icon={tab === 'open' ? 'check' : 'list'}
          title={tab === 'open' ? (done ? 'Alles übernommen' : 'Alles geklärt') : 'Keine Zeilen'}>
          {tab === 'open' && !done && 'Jetzt kannst du den Import abschließen. Neue Zeilen werden dabei als Buchungen übernommen.'}
        </EmptyState>
      )}

      <ul className="rows">
        {shown.slice(0, 200).map((r) => (
          <ImportRowCard key={r.id} row={r} open={tab === 'open' && !done} busy={resolve.isPending}
            onAction={(action, label) => act({ action, row_ids: [r.id] }, label)} />
        ))}
      </ul>
      {shown.length > 200 && <p className="muted">Die ersten 200 von {shown.length} Zeilen.</p>}

      {!done && (
        <footer className="batch-footer">
          {groups.open.length > 1 && openAmbiguous > 0 && (
            <>
              <Button variant="secondary" busy={resolve.isPending}
                onClick={() => act({ action: 'duplicate', decision: 'ambiguous' }, 'Alle unklaren als Dublette markiert')}>
                Alle unklaren sind Dubletten
              </Button>
              <Button variant="secondary" busy={resolve.isPending}
                onClick={() => act({ action: 'import', decision: 'ambiguous' }, 'Alle unklaren werden übernommen')}>
                Alle unklaren übernehmen
              </Button>
            </>
          )}
          <span className="spacer" />
          <Button variant="primary" className="btn-large" icon="check" busy={commit.isPending} disabled={groups.open.length > 0}
            title={groups.open.length ? 'Erst alle unklaren Zeilen klären' : undefined}
            onClick={() => commit.mutate(undefined, {
              onSuccess: (b) => toast.ok(`Import abgeschlossen: ${b.rows_new} Buchungen übernommen`),
              onError: (e) => toast.error(e instanceof ApiError && e.code === 'import_new_conflicts'
                ? new Error('Seit der Prüfung sind neue Konflikte aufgetaucht – bitte die markierten Zeilen erneut klären.') : e),
            })}>
            Import abschließen
          </Button>
        </footer>
      )}
    </section>
  )
}

function ImportRowCard({ row, open, busy, onAction }: {
  row: ImportRow
  open: boolean
  busy: boolean
  onAction: (action: 'import' | 'duplicate' | 'skip', label: string) => void
}) {
  const match = useProfileQuery<{ booking_date: string; amount: string; description: string }>(
    'transactions', `/transactions/${row.matched_transaction_id}`, undefined, { enabled: open && !!row.matched_transaction_id },
  )
  const hint = row.decision === 'before_opening'
    ? 'liegt vor dem Stichtag des Kontos – zählt nicht, außer du verlegst den Stichtag'
    : row.matched_transaction_id && match.data
      ? `ähnlich: Buchung vom ${shortDate(match.data.booking_date)} über ${formatEuro(match.data.amount)}`
      : row.note ?? (row.decision === 'ambiguous' ? 'möglicherweise schon vorhanden' : null)
  const loanHint = row.suggested_loan_entry_id ? 'passt zu einer Kreditrate – nach dem Abschließen unter „Prüfen“ als Rate buchen' : null

  return (
    <li className="row-card import-line">
      <span className="import-date">{row.booking_date ? shortDate(row.booking_date) : '–'}</span>
      <span className="row-main">
        <strong>{row.counterparty || row.description || 'ohne Text'}</strong>
        {(hint || loanHint) && <span>{loanHint ?? hint}</span>}
        {!hint && !loanHint && row.description && row.counterparty && <span>{row.description}</span>}
      </span>
      <span className="import-amount money">{row.amount ? formatEuro(row.amount) : '–'}</span>
      {open ? (
        <span className="import-actions">
          {row.decision === 'ambiguous' && (
            <Button variant="secondary" disabled={busy} onClick={() => onAction('duplicate', 'Als Dublette markiert')}>Ist Dublette</Button>
          )}
          <Button variant="secondary" disabled={busy} onClick={() => onAction('import', 'Wird übernommen')}>Übernehmen</Button>
          <Button variant="ghost" disabled={busy} onClick={() => onAction('skip', 'Übersprungen')}>Überspringen</Button>
        </span>
      ) : (
        <span className="muted import-resolution">
          {row.resolution === 'import' ? 'wird übernommen' : row.resolution === 'duplicate' ? 'Dublette' : row.resolution === 'skip' ? 'übersprungen' : row.value_date ? `Wert ${fullDate(row.value_date)}` : ''}
        </span>
      )}
    </li>
  )
}
