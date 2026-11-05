import { useState } from 'react'
import { api } from '../../api/client'
import { SUGGESTION_AREAS, useApiMutation, useChanges, type Change } from '../../api/hooks'
import { Button, Checkbox } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { Confirm, useToast } from '../../ui/overlay'
import { changeSummary } from './automation'

const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** Verlauf: was der Finanzplaner (oder du über Vorschläge) geändert hat – mit Rücknahme. */
export function HistorySection() {
  const toast = useToast()
  const [onlyAuto, setOnlyAuto] = useState(false)
  const changes = useChanges(onlyAuto ? { actor: 'auto' } : {})
  const [reverting, setReverting] = useState<Change | null>(null)
  const revert = useApiMutation((c: Change) => api.post(`/changes/${c.id}/revert`), [...SUGGESTION_AREAS, 'transactions', 'loans'])

  return (
    <div className="settings-section">
      <header className="settings-head">
        <div>
          <h2>Verlauf</h2>
          <p className="muted">Änderungen, die über Vorschläge oder die Automatik entstanden sind.</p>
        </div>
      </header>
      <section className="tile">
        <Checkbox label="Nur automatische Änderungen" checked={onlyAuto} onChange={setOnlyAuto} />
        {changes.isLoading && <Loading />}
        {changes.isError && <ErrorBox error={changes.error} onRetry={() => changes.refetch()} />}
        {changes.isSuccess && changes.data.length === 0 && (
          <EmptyState icon="list" title="Noch nichts im Verlauf">Sobald ein Vorschlag übernommen wird, steht er hier.</EmptyState>
        )}
        {changes.data && changes.data.length > 0 && (
          <ul className="rows history-list">
            {changes.data.map((c) => (
              <li key={c.id} className="row-card">
                <span className="row-main">
                  <strong>{changeSummary(c)}</strong>
                  <span>{dateTime(c.created_at)} · {c.actor === 'auto' ? 'automatisch' : 'von dir'}
                    {c.reverted_at && ` · zurückgenommen ${dateTime(c.reverted_at)}`}</span>
                </span>
                {!c.reverted_at && (
                  <Button disabled={revert.isPending} onClick={() => setReverting(c)}>Rückgängig</Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <Confirm
        open={reverting !== null}
        title="Änderung zurücknehmen?"
        text={reverting ? `${changeSummary(reverting)} wird auf den früheren Stand zurückgesetzt.` : ''}
        confirmLabel="Zurücknehmen"
        busy={revert.isPending}
        onCancel={() => setReverting(null)}
        onConfirm={() => reverting && revert.mutate(reverting, {
          onSuccess: () => { toast.ok('Zurückgenommen'); setReverting(null) },
          onError: (e) => { setReverting(null); toast.error(e) },
        })}
      />
    </div>
  )
}
