import { useState } from 'react'
import { api } from '../../api/client'
import { SUGGESTION_AREAS, useApiMutation, useCategories, useSuggestions, type Category, type Suggestion } from '../../api/hooks'
import { monthLabel } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, SelectField, TextField } from '../../ui/controls'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import {
  consistencyText, parseChange, parseConsistency, parseQuestion, parseRule, ruleEvidenceText, sortSuggestions,
  type MatchField,
} from './review'

/**
 * Einklappbarer Bereich „Vorschläge“ über der Prüfliste: Regeln aus Korrekturen,
 * Preisänderungen bei Fixkosten, Konsistenzhinweise und Rückfragen. Übernehmen und
 * Ablehnen gehen über dieselben Endpunkte wie bei den erkannten Fixkosten.
 */

function useOpen(kind: string) {
  const list = useSuggestions({ kind })
  return sortSuggestions((list.data ?? []).filter((s) => s.status === 'open'))
}


export function SuggestionsPanel() {
  const toast = useToast()
  const categories = useCategories()
  const rules = useOpen('rule')
  const changes = useOpen('fixed_cost_change')
  const consistency = useOpen('consistency')
  const questions = useOpen('question')
  const [expanded, setExpanded] = useState(true)
  const total = rules.length + changes.length + consistency.length + questions.length

  const accept = useApiMutation(
    ({ id, body }: { id: number; body?: Record<string, unknown> }) => api.post(`/suggestions/${id}/accept`, body), SUGGESTION_AREAS)
  const reject = useApiMutation((id: number) => api.post(`/suggestions/${id}/reject`), SUGGESTION_AREAS)
  const busy = accept.isPending || reject.isPending

  const categoryName = (id: number) => categories.data?.find((c) => c.id === id)?.name ?? 'Kategorie'
  const take = (s: Suggestion, ok: string, body?: Record<string, unknown>) =>
    accept.mutate({ id: s.id, body }, { onSuccess: () => toast.ok(ok), onError: toast.error })
  const drop = (s: Suggestion, ok: string) => reject.mutate(s.id, { onSuccess: () => toast.ok(ok), onError: toast.error })

  if (total === 0) return null
  return (
    <section className="tile suggestions-panel" aria-labelledby="review-suggestions-title">
      <button type="button" className="suggestions-toggle" aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
        <Icon name={expanded ? 'chevronDown' : 'chevronRight'} />
        <h2 id="review-suggestions-title">Vorschläge <span className="muted">({total})</span></h2>
      </button>
      {expanded && (
        <ul className="suggestion-list">
          {rules.map((s) => (
            <li key={s.id}>
              <RuleCard suggestion={s} categories={categories.data ?? []} busy={busy}
                onAccept={(overrides) => take(s, 'Regel angelegt', overrides)} onReject={() => drop(s, 'Vorschlag abgelehnt')} />
            </li>
          ))}
          {changes.map((s) => {
            const c = parseChange(s.payload)
            return (
              <li key={s.id} className="suggestion-card">
                <p><Icon name="coins" size={18} /> <strong>{c.name}</strong>
                  {c.oldAmount && c.newAmount ? <>: {formatEuro(c.oldAmount)} → {formatEuro(c.newAmount)}</> : null}
                  {c.permanent && c.validFrom ? <> ab {monthLabel(c.validFrom)}</> : null}
                </p>
                <p className="muted">{c.permanent ? 'Der Betrag hat sich dauerhaft geändert.' : 'Diesmal weicht der Betrag ab – nur zur Information.'}</p>
                {s.reason && <p className="muted">{s.reason}</p>}
                <div className="suggestion-actions">
                  {c.permanent ? (
                    <>
                      <Button variant="primary" icon="check" disabled={busy} onClick={() => take(s, 'Neuer Betrag übernommen')}>Neuen Betrag übernehmen</Button>
                      <Button disabled={busy} onClick={() => drop(s, 'Vorschlag abgelehnt')}>Ablehnen</Button>
                    </>
                  ) : (
                    <Button disabled={busy} onClick={() => take(s, 'Hinweis erledigt')}>Verstanden</Button>
                  )}
                </div>
              </li>
            )
          })}
          {consistency.map((s) => (
            <li key={s.id} className="suggestion-card">
              <p><Icon name="info" size={18} /> {consistencyText(parseConsistency(s.payload), categoryName)}</p>
              {s.reason && <p className="muted">{s.reason}</p>}
              <div className="suggestion-actions">
                <Button icon="check" disabled={busy} onClick={() => take(s, 'Okay, so bleibt es')}>Ist so gewollt</Button>
                <Button variant="ghost" disabled={busy} onClick={() => drop(s, 'Hinweis ausgeblendet')}>Ausblenden</Button>
              </div>
            </li>
          ))}
          {questions.map((s) => {
            const q = parseQuestion(s.payload)
            return (
              <li key={s.id} className="suggestion-card">
                <p><Icon name="sparkle" size={18} /> <strong>{q.merchant ?? 'Rückfrage'}</strong></p>
                <p>{q.question || s.reason}</p>
                <div className="suggestion-actions">
                  {q.options.map((o) => (
                    <Button key={o.value} disabled={busy} onClick={() => take(s, 'Danke, ist vermerkt', { answer: o.value })}>{o.label}</Button>
                  ))}
                  <Button variant="ghost" disabled={busy} onClick={() => drop(s, 'Rückfrage ausgeblendet')}>Später</Button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function RuleCard({ suggestion: s, categories, busy, onAccept, onReject }: {
  suggestion: Suggestion
  categories: Category[]
  busy: boolean
  onAccept: (overrides: Record<string, unknown>) => void
  onReject: () => void
}) {
  const r = parseRule(s.payload, s.evidence)
  const [pattern, setPattern] = useState(r.pattern)
  const [field, setField] = useState<MatchField>(r.matchField)
  const target = categories.find((c) => c.id === r.targetCategoryId)?.name ?? 'Kategorie'
  const valid = pattern.trim().length >= 2
  return (
    <div className="suggestion-card suggestion-rule">
      <p><Icon name="list" size={18} /> Regel: <strong>{target}</strong></p>
      <div className="form-grid">
        <SelectField label="Suchen in" value={field} onChange={(v) => setField(v as MatchField)} options={[
          { value: 'counterparty', label: 'Empfänger' }, { value: 'description', label: 'Verwendungszweck' }, { value: 'any', label: 'Empfänger oder Zweck' },
        ]} />
        <TextField label="enthält" value={pattern} onChange={setPattern} maxLength={200}
          error={valid ? undefined : 'Mindestens 2 Zeichen'} />
      </div>
      <p className="muted">{ruleEvidenceText(r)}</p>
      {r.conflictCount > 0 && (
        <p className="suggestion-conflict" role="note">
          <Icon name="alert" size={18} /> {r.conflictCount === 1 ? '1 Konflikt' : `${r.conflictCount} Konflikte`}
          {r.conflicts.length > 0 && <>: {r.conflicts.slice(0, 3).join(', ')}{r.conflicts.length > 3 ? ' …' : ''}</>}
          {' – '}das Muster trifft auch Buchungen mit anderer Kategorie.
        </p>
      )}
      {s.reason && <p className="muted">{s.reason}</p>}
      <div className="suggestion-actions">
        <Button variant="primary" icon="check" disabled={busy || !valid}
          onClick={() => onAccept({ name: pattern.trim(), pattern: pattern.trim(), match_field: field })}>Regel anlegen</Button>
        <Button disabled={busy} onClick={onReject}>Ablehnen</Button>
      </div>
    </div>
  )
}

