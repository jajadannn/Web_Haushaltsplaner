import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import {
  MONEY_AREAS, useAccounts, useAiStatus, useApiMutation, useCategories, useReview, useRules, useTransactions,
  type Category, type Transaction,
} from '../../api/hooks'
import { fullDate, shortDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, Checkbox, SelectField, Segmented, TextField } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, Money, Notice, PageHeader } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import './pruefen.css'

/**
 * Prüfen (Entwurf C · Tabelle mit Sammelleiste): Buchungen ohne Kategorie oder mit
 * automatisch gesetzter Kategorie bestätigen – einzeln, gesammelt oder als Regel für
 * die Zukunft. Vom Import erkannte Kreditraten lassen sich direkt als Rate buchen.
 * Ist eine lokale KI eingerichtet, schlägt sie im Hintergrund Kategorien vor; ihre
 * Vorschläge stehen unter „Automatisch zugeordnet“ mit Begründung und warten aufs Bestätigen.
 */

type ReviewItem = Schemas['ReviewItem']
type Status = 'needs_review' | 'auto_categorized'
const TRANSFER = 'transfer'
const PAGE = 100

/** Häufigste Kategorien der letzten Buchungen – als Vorschlags-Chips je Vorzeichen. */
function useFrequentCategories(categories: Category[]) {
  const history = useTransactions({ kind: 'regular', limit: 200 })
  return useMemo(() => {
    const counts = new Map<number, number>()
    for (const t of history.data?.items ?? []) {
      for (const id of t.splits.length ? t.splits.map((s) => s.category_id) : [t.category_id]) {
        if (id) counts.set(id, (counts.get(id) ?? 0) + 1)
      }
    }
    const byType = (type: 'income' | 'expense') => categories
      .filter((c) => c.type === type && c.active && !c.system_key)
      .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0))
    return { expense: byType('expense'), income: byType('income') }
  }, [history.data, categories])
}

export function ReviewPage() {
  const toast = useToast()
  const [status, setStatus] = useState<Status>('needs_review')
  const ai = useAiStatus()
  const aiWorking = Boolean(ai.data?.enabled && ai.data.reachable && ai.data.pending > 0)
  // Solange die KI arbeitet, erscheinen ihre Vorschläge ohne Neuladen der Seite
  const review = useReview({ status, limit: PAGE }, { refetchInterval: aiWorking ? 15_000 : false })
  const categories = useCategories({ active: true })
  const accounts = useAccounts({ include_archived: true })
  const rules = useRules()
  const frequent = useFrequentCategories(categories.data ?? [])
  const items = review.data?.items ?? []
  const total = review.data?.total ?? 0

  // gewählte Kategorie je Buchung ('' = keine, 'transfer' = Umbuchung)
  const [choice, setChoice] = useState<Record<number, string>>({})
  const [marked, setMarked] = useState<Set<number>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [ruleFor, setRuleFor] = useState<Transaction | null>(null)

  const choiceOf = (t: Transaction) => choice[t.id] ?? (t.category_id ? String(t.category_id) : '')
  const accountName = (id: number) => accounts.data?.find((a) => a.id === id)?.name ?? ''
  const ruleName = (id: number | null) => rules.data?.find((r) => r.id === id)?.name || rules.data?.find((r) => r.id === id)?.pattern

  const confirm = useApiMutation((t: Transaction) => {
    const value = choiceOf(t)
    return api.post(`/review/${t.id}/confirm`, value === TRANSFER ? { as_transfer: true } : { category_id: value ? Number(value) : null })
  }, MONEY_AREAS)
  const bulk = useApiMutation(() => api.post('/review/bulk-confirm', {
    transaction_ids: [...marked],
    ...(bulkCategory === TRANSFER ? { as_transfer: true } : { category_id: bulkCategory ? Number(bulkCategory) : null }),
  }), MONEY_AREAS)
  const aiRetry = useApiMutation(() => api.post<Schemas['AiRetryResult']>('/review/ai/retry'), ['review'])
  const bookLoan = useApiMutation((item: ReviewItem) => api.post(`/loans/${item.suggested_loan!.loan_id}/payments`, {
    transaction_id: item.transaction.id, schedule_seq: item.suggested_loan!.seq,
  }), [...MONEY_AREAS, 'fixed-costs'])

  const confirmOne = (t: Transaction) => {
    const value = choiceOf(t)
    if (!value && status === 'needs_review') {
      toast.error(new Error('Bitte zuerst eine Kategorie wählen'))
      return
    }
    confirm.mutate(t, {
      onSuccess: () => {
        toast.ok(`„${t.counterparty || t.description}“ bestätigt`)
        setMarked((m) => { const n = new Set(m); n.delete(t.id); return n })
      },
      onError: toast.error,
    })
  }

  const allMarked = items.length > 0 && items.every((i) => marked.has(i.transaction.id))
  const optionsFor = (t: Transaction) => {
    const incoming = !t.amount.startsWith('-')
    const main = (incoming ? frequent.income : frequent.expense).map((c) => ({ value: String(c.id), label: c.name }))
    const other = (incoming ? frequent.expense : frequent.income).map((c) => ({ value: String(c.id), label: `${c.name} (${incoming ? 'Erstattung' : 'Rückzahlung'})` }))
    return [{ value: TRANSFER, label: 'Umbuchung (eigenes Konto)' }, ...main, ...other]
  }

  return (
    <div className="page review-page">
      <PageHeader title="Prüfen">
        {marked.size > 0 && (
          <Button variant="primary" busy={bulk.isPending} onClick={() => bulk.mutate(undefined, {
            onSuccess: () => { toast.ok(`${marked.size} Buchungen bestätigt`); setMarked(new Set()) },
            onError: toast.error,
          })} disabled={status === 'needs_review' && !bulkCategory}>
            Alle markierten bestätigen
          </Button>
        )}
      </PageHeader>
      <p className="review-sub">
        {status === 'needs_review'
          ? total === 1 ? '1 Buchung braucht eine Kategorie' : `${total} Buchungen brauchen eine Kategorie`
          : `${total} automatisch zugeordnete Buchungen zum Bestätigen`}
      </p>
      <AiNotice status={ai.data} canRetry={status === 'needs_review' && items.some((i) => i.transaction.ai_note)}
        retrying={aiRetry.isPending}
        onRetry={() => aiRetry.mutate(undefined, {
          onSuccess: (r) => toast.ok(r.queued === 1 ? '1 Buchung wird erneut geprüft' : `${r.queued} Buchungen werden erneut geprüft`),
          onError: toast.error,
        })} />
      <Segmented<Status> label="Ansicht" value={status} onChange={(s) => { setStatus(s); setMarked(new Set()) }} options={[
        { value: 'needs_review', label: 'Ohne Kategorie' },
        { value: 'auto_categorized', label: 'Automatisch zugeordnet' },
      ]} />

      {review.isLoading && <Loading />}
      {review.isError && <ErrorBox error={review.error} onRetry={() => review.refetch()} />}
      {review.isSuccess && items.length === 0 && (
        <div className="tile">
          <EmptyState icon="check" title="Alles geprüft">
            {status === 'needs_review' ? 'Keine Buchung wartet auf eine Kategorie.' : 'Keine automatisch zugeordnete Buchung wartet auf Bestätigung.'}
          </EmptyState>
        </div>
      )}

      {items.length > 0 && (
        <div className="review-layout">
          <div className="tile review-table-tile">
            <table className="review-table">
              <thead>
                <tr>
                  <th scope="col" className="col-check">
                    <input type="checkbox" aria-label="Alle markieren" checked={allMarked}
                      onChange={(e) => setMarked(e.target.checked ? new Set(items.map((i) => i.transaction.id)) : new Set())} />
                  </th>
                  <th scope="col">Datum</th>
                  <th scope="col">Empfänger / Zweck</th>
                  <th scope="col" className="num">Betrag</th>
                  <th scope="col">Kategorie</th>
                  <th scope="col">Aktion</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const t = item.transaction
                  const value = choiceOf(t)
                  const chips = (t.amount.startsWith('-') ? frequent.expense : frequent.income).slice(0, 2)
                  return (
                    <tr key={t.id} className={marked.has(t.id) ? 'is-marked' : ''}>
                      <td className="col-check">
                        <input type="checkbox" aria-label={`${t.counterparty || t.description} markieren`} checked={marked.has(t.id)}
                          onChange={(e) => setMarked((m) => { const n = new Set(m); if (e.target.checked) n.add(t.id); else n.delete(t.id); return n })} />
                      </td>
                      <td className="col-date">{shortDate(t.booking_date)}</td>
                      <td className="col-what">
                        <strong>{t.counterparty || t.description}</strong>
                        <span>{t.counterparty && t.description !== t.counterparty ? `${t.description} · ` : ''}{accountName(t.account_id)}</span>
                      </td>
                      <td className="num col-amount"><Money value={t.amount} signed /></td>
                      <td className="col-category">
                        {item.suggested_loan ? (
                          <p className="loan-suggestion">
                            <Icon name="coins" size={18} />
                            passt zu {item.suggested_loan.loan_name}, Rate {item.suggested_loan.seq} vom {fullDate(item.suggested_loan.due_date)} ({formatEuro(item.suggested_loan.planned_installment)})
                          </p>
                        ) : null}
                        <div className="select">
                          <select className="input" aria-label="Kategorie" value={value}
                            onChange={(e) => setChoice((c) => ({ ...c, [t.id]: e.target.value }))}>
                            <option value="">Kategorie wählen</option>
                            {optionsFor(t).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                          </select>
                          <Icon name="chevronDown" size={18} className="select-chevron" />
                        </div>
                        {t.ai_note && !(t.category_source === 'ai' && value === String(t.category_id)) && (
                          <p className="ai-hint is-muted"><Icon name="sparkle" size={16} /> KI: {t.ai_note}</p>
                        )}
                        <div className="review-chips">
                          {t.category_source === 'ai' && t.category_id && value === String(t.category_id) ? (
                            <span className="ai-hint"><Icon name="sparkle" size={16} /> KI: {t.ai_note}</span>
                          ) : t.applied_rule_id && t.category_id && value === String(t.category_id) ? (
                            <span className="rule-hint"><Icon name="list" size={16} /> Regel „{ruleName(t.applied_rule_id)}“</span>
                          ) : (
                            <>
                              {chips.map((c) => (
                                <button key={c.id} type="button" className={`chip small${value === String(c.id) ? ' is-active' : ''}`}
                                  onClick={() => setChoice((x) => ({ ...x, [t.id]: String(c.id) }))}>
                                  {c.name}
                                </button>
                              ))}
                              {!t.amount.startsWith('-') && (
                                <button type="button" className={`chip small${value === TRANSFER ? ' is-active' : ''}`}
                                  onClick={() => setChoice((x) => ({ ...x, [t.id]: TRANSFER }))}>
                                  Umbuchung
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                      <td className="col-actions">
                        {item.suggested_loan ? (
                          <Button variant="primary" busy={bookLoan.isPending} onClick={() => bookLoan.mutate(item, {
                            onSuccess: () => toast.ok('Als Kreditrate gebucht und aufgeteilt'), onError: toast.error,
                          })}>
                            Als Rate buchen
                          </Button>
                        ) : (
                          <Button variant="primary" busy={confirm.isPending && confirm.variables?.id === t.id} onClick={() => confirmOne(t)}>
                            Bestätigen
                          </Button>
                        )}
                        <Button variant="secondary" className={ruleFor?.id === t.id ? 'is-pressed' : ''} onClick={() => setRuleFor(ruleFor?.id === t.id ? null : t)}>
                          Regel vorschlagen
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {total > items.length && <p className="muted review-more">Die ersten {items.length} von {total}. Nach dem Bestätigen rücken die nächsten nach.</p>}
          </div>

          {ruleFor && (
            <RuleSuggestionPanel key={ruleFor.id} tx={ruleFor} categories={categories.data ?? []} onClose={() => setRuleFor(null)} />
          )}
        </div>
      )}

      {marked.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Sammelaktion">
          <strong>{marked.size} markiert</strong>
          <span aria-hidden="true">·</span>
          <div className="select">
            <select className="input" aria-label="Kategorie für alle markierten" value={bulkCategory} onChange={(e) => setBulkCategory(e.target.value)}>
              <option value="">{status === 'auto_categorized' ? 'Kategorie: wie vorgeschlagen' : 'Kategorie wählen'}</option>
              <option value={TRANSFER}>Umbuchung (eigenes Konto)</option>
              {[...frequent.expense, ...frequent.income].map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <Icon name="chevronDown" size={18} className="select-chevron" />
          </div>
          <Button variant="primary" busy={bulk.isPending} disabled={status === 'needs_review' && !bulkCategory}
            onClick={() => bulk.mutate(undefined, {
              onSuccess: () => { toast.ok(`${marked.size} Buchungen bestätigt`); setMarked(new Set()); setBulkCategory('') },
              onError: toast.error,
            })}>
            Bestätigen
          </Button>
          <button type="button" className="icon-btn" aria-label="Markierung aufheben" onClick={() => setMarked(new Set())}>
            <Icon name="close" />
          </button>
        </div>
      )}
    </div>
  )
}

/** Zeile über der Liste: Was die lokale KI gerade tut (nichts, wenn keine eingerichtet ist). */
function AiNotice({ status, canRetry, retrying, onRetry }: {
  status: Schemas['AiStatus'] | undefined
  canRetry: boolean
  retrying: boolean
  onRetry: () => void
}) {
  if (!status?.enabled) return null
  const retry = canRetry ? <Button variant="secondary" busy={retrying} onClick={onRetry}>Erneut prüfen</Button> : null
  if (status.reachable === false) {
    return (
      <Notice tone="due" icon="alert" action={retry}>
        KI ({status.model}) nicht erreichbar – Vorschläge kommen, sobald sie wieder läuft.
      </Notice>
    )
  }
  if (status.pending > 0) {
    return (
      <Notice tone="info" icon="sparkle">
        KI ({status.model}) prüft im Hintergrund – noch {status.pending === 1 ? '1 Buchung' : `${status.pending} Buchungen`}.
        Vorschläge erscheinen unter „Automatisch zugeordnet“.
      </Notice>
    )
  }
  return retry ? (
    <Notice tone="info" icon="sparkle" action={retry}>
      Für einige Buchungen hat die KI keine passende Kategorie gefunden.
    </Notice>
  ) : null
}

/** „Regel vorschlagen“: Vorschlag des Backends, bearbeitbar, dann als Regel speichern. */
function RuleSuggestionPanel({ tx, categories, onClose }: { tx: Transaction; categories: Category[]; onClose: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [loaded, setLoaded] = useState(false)
  const [pattern, setPattern] = useState('')
  const [field, setField] = useState<'any' | 'description' | 'counterparty'>('counterparty')
  const [categoryId, setCategoryId] = useState('')
  const [hits, setHits] = useState<number | null>(null)
  const [applyNow, setApplyNow] = useState(true)

  // Vorschlag einmal beim Öffnen holen (das Panel wird je Buchung neu eingehängt)
  useEffect(() => {
    let cancelled = false
    api.post<Schemas['RuleSuggestion']>(`/review/${tx.id}/suggest-rule`)
      .then((s) => {
        if (cancelled) return
        setPattern(s.pattern)
        setField(s.match_field)
        setCategoryId(s.target_category_id ? String(s.target_category_id) : '')
        setHits(s.matching_transactions)
      })
      .catch((e) => { if (!cancelled) form.fail(e) })
      .finally(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tx.id])

  const save = useApiMutation(async () => {
    const rule = await api.post('/mapping-rules', {
      name: pattern.trim(), pattern: pattern.trim(), match_type: 'contains', match_field: field,
      target_category_id: Number(categoryId),
    })
    if (applyNow) await api.post('/mapping-rules/apply', undefined, { dry_run: false })
    return rule
  }, [...MONEY_AREAS, 'rules'])

  return (
    <aside className="tile rule-panel" aria-label="Regel vorschlagen">
      <header>
        <h2>Regel vorschlagen</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Schließen"><Icon name="close" /></button>
      </header>
      {!loaded ? <Loading /> : (
        <form className="rule-form" onSubmit={(e) => {
          e.preventDefault()
          if (!form.check({ pattern: pattern.trim().length < 2 && 'Mindestens 2 Zeichen', target_category_id: !categoryId && 'Bitte eine Kategorie wählen' })) return
          save.mutate(undefined, { onSuccess: () => { toast.ok('Regel gespeichert'); onClose() }, onError: form.fail })
        }}>
          <SelectField label="Suchen in" value={field} onChange={(v) => setField(v as typeof field)} options={[
            { value: 'counterparty', label: 'Empfänger' }, { value: 'description', label: 'Verwendungszweck' }, { value: 'any', label: 'Empfänger oder Zweck' },
          ]} />
          <TextField label="enthält" value={pattern} onChange={setPattern} error={form.errors.pattern} maxLength={200} />
          <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="Kategorie wählen" error={form.errors.target_category_id}
            options={categories.filter((c) => !c.system_key).map((c) => ({ value: String(c.id), label: c.name }))} />
          {hits !== null && <p className="muted">trifft {hits} {hits === 1 ? 'Buchung' : 'Buchungen'}</p>}
          <Checkbox label="Gleich auf ungeprüfte Buchungen anwenden" checked={applyNow} onChange={setApplyNow} />
          {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
          <Button variant="primary" type="submit" busy={save.isPending}>Regel speichern</Button>
          <Link to="/einstellungen/regeln" className="link">Alle Regeln</Link>
        </form>
      )}
    </aside>
  )
}
