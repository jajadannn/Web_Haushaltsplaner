import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import type { AskAnswer, ComparisonTransaction, MonthExplanation } from '../../api/ai'
import { useMonthComparison } from '../../api/hooks'
import { fullDate, monthLabel } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, TextField } from '../../ui/controls'
import { ErrorBox, Loading, Money, Notice, Tile } from '../../ui/blocks'
import { askPeriodText, deltaText, deltaTone, mainCategories, toolLabel, transactionLink } from './monthCompare'

/** Gemeinsame Fehleranzeige: fehlende KI freundlich, alles andere als normale Fehlermeldung. */
function AiError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === 'ai_unavailable') {
    return <Notice tone="info" icon="info">Keine lokale KI eingerichtet.</Notice>
  }
  return <ErrorBox error={error} />
}

function References({ ids }: { ids: number[] }) {
  if (ids.length === 0) return null
  return (
    <p className="ai-refs">
      <span className="muted">Belege:</span>{' '}
      {ids.map((id) => <Link key={id} to={transactionLink(id)} className="chip small">Buchung {id}</Link>)}
    </p>
  )
}

/** „Frage zu deinen Buchungen“ – die Antwort kommt aus festen Auswertungen, die KI wählt nur das Werkzeug. */
export function AskCard() {
  const [question, setQuestion] = useState('')
  const ask = useMutation({ mutationFn: (q: string) => api.post<AskAnswer>('/ask', { question: q }) })
  const a = ask.data
  const period = askPeriodText(a?.period)

  return (
    <Tile className="ai-card" title="Frage zu deinen Buchungen">
      <form className="ai-ask" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask.mutate(question.trim()) }}>
        <TextField label="Frage" value={question} onChange={setQuestion} maxLength={500}
          placeholder="z. B. Was habe ich im Oktober für Lebensmittel ausgegeben?" />
        <Button variant="primary" icon="sparkle" type="submit" busy={ask.isPending} disabled={!question.trim()}>Fragen</Button>
      </form>
      {ask.isError && <AiError error={ask.error} />}
      {a && (
        <div className="ai-answer" aria-live="polite">
          <p className="ai-answer-text">{a.answer}</p>
          <p className="muted">
            {period && <>Zeitraum: {period} · </>}
            {a.data_as_of && <>Datenstand: {fullDate(a.data_as_of)} · </>}
            Werkzeug: {toolLabel(a.tool)}
          </p>
          <References ids={a.references} />
        </div>
      )}
    </Tile>
  )
}

function TxList({ title, items }: { title: string; items: ComparisonTransaction[] }) {
  if (items.length === 0) return null
  return (
    <div className="cmp-block">
      <h3>{title}</h3>
      <ul className="cmp-list">
        {items.map((t) => (
          <li key={t.transaction_id}>
            <span className="muted">{fullDate(t.date)}</span>
            <Link to={transactionLink(t.transaction_id)}>{t.counterparty || t.description || 'Buchung'}</Link>
            <Money value={t.amount} />
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Monatsvergleich mit Zahlen; „Erklären lassen“ ergänzt einen Text der lokalen KI. */
export function MonthCompareCard({ month }: { month: string }) {
  const cmp = useMonthComparison(month)
  const explain = useMutation({
    mutationFn: () => api.post<MonthExplanation>('/reports/month-comparison/explain', undefined, { month }),
  })
  const c = cmp.data
  const cats = c ? mainCategories(c.categories) : []

  return (
    <Tile className="ai-card" title={`Monatsvergleich ${monthLabel(month)}`}
      action={c && (
        <Button icon="sparkle" busy={explain.isPending} onClick={() => explain.mutate()}>Erklären lassen</Button>
      )}>
      {cmp.isLoading && <Loading />}
      {cmp.isError && <ErrorBox error={cmp.error} onRetry={() => cmp.refetch()} />}
      {c && (
        <>
          {c.incomplete && (
            <Notice tone="info" icon="info">
              Der Monat ist noch nicht zu Ende – verglichen wird bis {fullDate(c.until)}.
            </Notice>
          )}
          <div className="cmp-numbers">
            <div><p className="kpi-label">Ausgaben</p><p className="kpi-value">{formatEuro(c.expenses)}</p></div>
            <div><p className="kpi-label">Vormonat</p><p className="kpi-value">{formatEuro(c.previous_expenses)}</p></div>
            <div>
              <p className="kpi-label">Unterschied</p>
              <p className={`kpi-value cmp-${deltaTone(c.delta)}`}>{deltaText(c.delta)}</p>
            </div>
          </div>
          {cats.length > 0 && (
            <div className="cmp-block">
              <h3>Hauptkategorien</h3>
              <ul className="cmp-list">
                {cats.map((k) => (
                  <li key={`${k.category_id}-${k.name}`}>
                    <strong>{k.name}</strong>
                    <span className="muted">{formatEuro(k.current)} (Vormonat {formatEuro(k.previous)}, Schnitt 3 Monate {formatEuro(k.average_3)})</span>
                    <span className={`cmp-${deltaTone(k.delta)}`}>{deltaText(k.delta)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <TxList title="Einmaleffekte" items={c.one_offs} />
          {explain.isError && <AiError error={explain.error} />}
          {explain.data && (
            <div className="ai-answer" aria-live="polite">
              <p className="ai-answer-text">{explain.data.text}</p>
              <References ids={explain.data.references} />
            </div>
          )}
        </>
      )}
    </Tile>
  )
}
