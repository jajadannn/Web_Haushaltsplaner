import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { MONEY_AREAS, useApiMutation, useFixedCostPayments, type FixedCostPayment } from '../../api/hooks'
import { monthLabel } from '../../lib/dates'
import { Button } from '../../ui/controls'
import { ErrorBox, Loading } from '../../ui/blocks'
import { Confirm, useToast } from '../../ui/overlay'

const SOURCE: Record<string, string> = { manual: 'von Hand', suggestion: 'aus Vorschlag', auto: 'automatisch' }

/** Mit einer Fixkost verknüpfte Zahlungen (Bezahlt-Erkennung); Verknüpfungen lassen sich lösen. */
export function FixedCostPayments({ fixedCostId }: { fixedCostId: number }) {
  const toast = useToast()
  const payments = useFixedCostPayments(fixedCostId)
  const [removing, setRemoving] = useState<FixedCostPayment | null>(null)
  const unlink = useApiMutation(
    (link: FixedCostPayment) => api.delete(`/fixed-costs/${fixedCostId}/payments/${link.id}`),
    [...MONEY_AREAS, 'fixed-costs', 'suggestions'],
  )
  const items = [...(payments.data ?? [])].sort((a, b) => b.due_month.localeCompare(a.due_month))

  return (
    <section className="fc-payments" aria-label="Verknüpfte Zahlungen">
      <h4>Verknüpfte Zahlungen</h4>
      {payments.isLoading && <Loading />}
      {payments.isError && <ErrorBox error={payments.error} onRetry={() => payments.refetch()} />}
      {payments.isSuccess && items.length === 0 && (
        <p className="muted">Noch keine Zahlung fest verknüpft. Bezahlt wird dann über Kategorie oder Suchtext erkannt.</p>
      )}
      {items.length > 0 && (
        <ul className="fc-payments-list">
          {items.map((l) => (
            <li key={l.id}>
              <span>
                <strong>{monthLabel(l.due_month)}</strong>
                {' · '}
                <Link to={`/buchungen?id=${l.transaction_id}`}>Buchung ansehen</Link>
                <span className="muted"> · {SOURCE[l.source] ?? l.source}</span>
              </span>
              <Button disabled={unlink.isPending} onClick={() => setRemoving(l)}>Lösen</Button>
            </li>
          ))}
        </ul>
      )}
      <Confirm
        open={removing !== null}
        title="Verknüpfung lösen?"
        text={removing ? `Die Zahlung für ${monthLabel(removing.due_month)} gilt danach nicht mehr als fest zugeordnet. Die Buchung selbst bleibt erhalten.` : ''}
        confirmLabel="Lösen"
        busy={unlink.isPending}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && unlink.mutate(removing, {
          onSuccess: () => { toast.ok('Verknüpfung gelöst'); setRemoving(null) },
          onError: (e) => { setRemoving(null); toast.error(e) },
        })}
      />
    </section>
  )
}
