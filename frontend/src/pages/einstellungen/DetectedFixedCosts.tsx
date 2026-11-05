import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import {
  SUGGESTION_AREAS, useAccounts, useApiMutation, useCategories, useSuggestions,
  type Account, type Category, type Suggestion,
} from '../../api/hooks'
import { fullDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, MoneyField, SelectField, TextField } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import { parseAiHint } from './merchants'
import {
  INTERVAL_OPTIONS, intervalLabel, parseEvidence, parseFixedCostPayload, sortSuggestions, statusNote,
  type FixedCostPayload,
} from './suggestions'

const SHOWN = ['open', 'dry_run', 'auto_applied']

/** „Erkannte Fixkosten“: Vorschläge des Servers übernehmen, anpassen oder ablehnen. */
export function DetectedFixedCosts() {
  const toast = useToast()
  const list = useSuggestions({ kind: 'fixed_cost_new' })
  const categories = useCategories({ type: 'expense' })
  const accounts = useAccounts()
  const [editing, setEditing] = useState<number | null>(null)

  const refresh = useApiMutation(() => api.post<{ new: number }>('/suggestions/refresh'), SUGGESTION_AREAS)
  const accept = useApiMutation(
    ({ id, overrides }: { id: number; overrides?: Record<string, unknown> }) =>
      api.post(`/suggestions/${id}/accept`, overrides), SUGGESTION_AREAS)
  const reject = useApiMutation((id: number) => api.post(`/suggestions/${id}/reject`), SUGGESTION_AREAS)
  const revert = useApiMutation((id: number) => api.post(`/suggestions/${id}/revert`), SUGGESTION_AREAS)

  const shown = sortSuggestions((list.data ?? []).filter((s) => SHOWN.includes(s.status)))

  return (
    <section className="settings-section detected" aria-labelledby="detected-title">
      <header className="settings-head">
        <div>
          <h2 id="detected-title">Erkannte Fixkosten</h2>
          <p className="muted">Wiederkehrende Zahlungen, die der Finanzplaner in deinen Buchungen gefunden hat.</p>
        </div>
        <Button icon="refresh" busy={refresh.isPending} onClick={() => refresh.mutate(undefined, {
          onSuccess: (r) => {
            const n = (r as { new: number }).new
            toast.ok(n === 0 ? 'Nichts Neues gefunden' : n === 1 ? '1 neuer Vorschlag' : `${n} neue Vorschläge`)
          },
          onError: toast.error,
        })}>Jetzt prüfen</Button>
      </header>
      <div className="tile">
        {list.isLoading && <Loading />}
        {list.isError && <ErrorBox error={list.error} onRetry={() => list.refetch()} />}
        {list.isSuccess && shown.length === 0 && (
          <EmptyState icon="search" title="Keine Vorschläge">
            Es gibt gerade nichts zu übernehmen. „Jetzt prüfen“ sucht noch einmal in den Buchungen.
          </EmptyState>
        )}
        <ul className="rows">
          {shown.map((s) => (
            <li key={s.id} className="row-card detected-row">
              {editing === s.id ? (
                <SuggestionEditForm
                  suggestion={s} categories={categories.data ?? []} accounts={accounts.data ?? []}
                  busy={accept.isPending}
                  onCancel={() => setEditing(null)}
                  onSave={(overrides, fail) => accept.mutate({ id: s.id, overrides }, {
                    onSuccess: () => { toast.ok('Fixkost angelegt'); setEditing(null) },
                    onError: fail,
                  })}
                />
              ) : (
                <SuggestionCard
                  suggestion={s} busy={accept.isPending || reject.isPending || revert.isPending}
                  onAccept={() => accept.mutate({ id: s.id }, { onSuccess: () => toast.ok('Fixkost angelegt'), onError: toast.error })}
                  onEdit={() => setEditing(s.id)}
                  onReject={() => reject.mutate(s.id, { onSuccess: () => toast.ok('Vorschlag abgelehnt'), onError: toast.error })}
                  onRevert={() => revert.mutate(s.id, { onSuccess: () => toast.ok('Zurückgenommen'), onError: toast.error })}
                />
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function SuggestionCard({ suggestion: s, busy, onAccept, onEdit, onReject, onRevert }: {
  suggestion: Suggestion
  busy: boolean
  onAccept: () => void
  onEdit: () => void
  onReject: () => void
  onRevert: () => void
}) {
  const p = parseFixedCostPayload(s.payload)
  const evidence = parseEvidence(s.evidence)
  const note = statusNote(s.status)
  const ai = parseAiHint(s.payload)
  return (
    <div className="detected-card">
      <div className="detected-top">
        <strong>{p.name || 'Fixkost'}</strong>
        <span className="money">{p.amount ? formatEuro(p.amount) : '–'}</span>
      </div>
      <p className="muted">
        {intervalLabel(p.intervalMonths)} · am {p.dueDay}.
        {p.firstDueDate && ` · erste Fälligkeit ${fullDate(p.firstDueDate)}`}
      </p>
      {ai && (
        <p className="muted" role="note">
          Vorschlag mit KI benannt{ai.provider && <> · Anbieter: {ai.provider}</>}
          {ai.obligation === false && <> · KI: eher regelmäßiger Konsum</>}
        </p>
      )}
      {note && <p className={`detected-note is-${s.status}`} role="note">{note}</p>}
      {s.reason && <p className="detected-reason">{s.reason}</p>}
      {evidence.transactions.length > 0 && (
        <details className="detected-evidence">
          <summary>{evidence.transactions.length === 1 ? '1 Belegbuchung' : `${evidence.transactions.length} Belegbuchungen`}</summary>
          <ul>
            {evidence.transactions.map((t) => (
              <li key={`${t.id}-${t.splitId ?? 0}`}>
                <Link to={`/buchungen?id=${t.id}`}>{fullDate(t.date)}</Link>
                <span className="money">{formatEuro(t.amount)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="detected-actions">
        {s.status === 'auto_applied' ? (
          <Button disabled={busy} onClick={onRevert}>Rückgängig</Button>
        ) : (
          <>
            <Button variant="primary" icon="check" disabled={busy} onClick={onAccept}>Übernehmen</Button>
            <Button icon="edit" disabled={busy} onClick={onEdit}>Bearbeiten</Button>
            <Button variant="danger" disabled={busy} onClick={onReject}>Ablehnen</Button>
          </>
        )}
      </div>
    </div>
  )
}

function SuggestionEditForm({ suggestion, categories, accounts, busy, onSave, onCancel }: {
  suggestion: Suggestion
  categories: Category[]
  accounts: Account[]
  busy: boolean
  onSave: (overrides: Record<string, unknown>, fail: (e: unknown) => void) => void
  onCancel: () => void
}) {
  const p: FixedCostPayload = parseFixedCostPayload(suggestion.payload)
  const form = useFormErrors()
  const [name, setName] = useState(p.name)
  const [amount, setAmount] = useState<string | null>(p.amount)
  const [interval, setIntervalValue] = useState(String(p.intervalMonths))
  const [dueDay, setDueDay] = useState(String(p.dueDay))
  const [first, setFirst] = useState(p.firstDueDate ?? '')
  const [categoryId, setCategoryId] = useState(p.categoryId ? String(p.categoryId) : '')
  const [accountId, setAccountId] = useState(p.accountId ? String(p.accountId) : '')
  const [matchText, setMatchText] = useState(p.matchText ?? '')

  function submit() {
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      amount: !amount && 'Bitte einen Betrag eingeben',
      first_due_date: interval !== '1' && !first && 'Bitte die erste Fälligkeit angeben',
      match_text: matchText.trim().length === 1 && 'Mindestens 2 Zeichen',
    })
    if (!ok) return
    onSave({
      name: name.trim(),
      amount,
      interval_months: Number(interval),
      due_day: Number(dueDay),
      first_due_date: interval === '1' ? null : first,
      category_id: categoryId ? Number(categoryId) : null,
      account_id: accountId ? Number(accountId) : null,
      match_text: matchText.trim() || null,
    }, form.fail)
  }

  return (
    <form className="settings-form-body detected-form" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus />
      <div className="form-grid">
        <MoneyField label="Betrag pro Zahlung" value={amount} onChange={setAmount} error={form.errors.amount} />
        <SelectField label="Rhythmus" value={interval} onChange={setIntervalValue} options={INTERVAL_OPTIONS} error={form.errors.interval_months} />
      </div>
      <div className="form-grid">
        <SelectField label="Fälligkeitstag" value={dueDay} onChange={setDueDay}
          options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: `am ${i + 1}.` }))} />
        {interval !== '1' && (
          <TextField label="Erste Fälligkeit" type="date" value={first} onChange={setFirst} error={form.errors.first_due_date} />
        )}
      </div>
      <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="ohne Kategorie"
        options={categories.filter((c) => c.active || String(c.id) === categoryId).map((c) => ({ value: String(c.id), label: c.name }))} />
      <SelectField label="Zahlkonto (optional)" value={accountId} onChange={setAccountId} placeholder="egal"
        options={accounts.filter((a) => a.type !== 'loan').map((a) => ({ value: String(a.id), label: a.name }))} />
      <TextField label="Erkennen an (Text in der Buchung)" value={matchText} onChange={setMatchText}
        maxLength={100} error={form.errors.match_text} />
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <div className="form-actions">
        <Button onClick={onCancel}>Abbrechen</Button>
        <span className="spacer" />
        <Button variant="primary" type="submit" busy={busy}>Übernehmen</Button>
      </div>
    </form>
  )
}
