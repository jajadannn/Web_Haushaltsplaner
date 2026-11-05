import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { MONEY_AREAS, useApiMutation, useReview, useReviewGroups, type Category } from '../../api/hooks'
import { shortDate } from '../../lib/dates'
import { Button, Checkbox, SelectField } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, Money } from '../../ui/blocks'
import { useToast } from '../../ui/overlay'
import { confirmIds } from './review'

type Group = Schemas['ReviewGroup']

/**
 * Gruppierte Ansicht: Buchungen desselben Empfängers stehen zusammen. Je Gruppe eine Kategorie
 * wählen, einzelne Buchungen abwählen und den Rest gemeinsam bestätigen.
 */
export function GroupedView({ categories }: { categories: Category[] }) {
  const groups = useReviewGroups()
  // Details der Buchungen (Datum, Empfänger); die API liefert höchstens 200 je Abruf
  const detail = useReview({ status: 'needs_review', limit: 200 })
  const byId = new Map((detail.data?.items ?? []).map((i) => [i.transaction.id, i.transaction]))
  const [deselected, setDeselected] = useState<Set<number>>(new Set())
  const toggle = (id: number, on: boolean) => setDeselected((s) => { const n = new Set(s); if (on) n.delete(id); else n.add(id); return n })

  if (groups.isLoading) return <Loading />
  if (groups.isError) return <ErrorBox error={groups.error} onRetry={() => groups.refetch()} />
  if ((groups.data ?? []).length === 0) {
    return (
      <div className="tile">
        <EmptyState icon="check" title="Keine Gruppen">Es gibt keine Buchungen, die sich sinnvoll gemeinsam bestätigen lassen.</EmptyState>
      </div>
    )
  }
  return (
    <ul className="group-list">
      {(groups.data ?? []).map((g) => (
        <li key={g.key}>
          <GroupCard group={g} categories={categories} byId={byId} deselected={deselected} onToggle={toggle} />
        </li>
      ))}
    </ul>
  )
}

function GroupCard({ group: g, categories, byId, deselected, onToggle }: {
  group: Group
  categories: Category[]
  byId: Map<number, Schemas['TransactionRead']>
  deselected: ReadonlySet<number>
  onToggle: (id: number, on: boolean) => void
}) {
  const toast = useToast()
  const type = g.direction === 'in' ? 'income' : 'expense'
  const options = categories.filter((c) => c.type === type && c.active && !c.system_key)
    .map((c) => ({ value: String(c.id), label: c.name }))
  const [category, setCategory] = useState(g.category_ids.length === 1 ? String(g.category_ids[0]) : '')
  const ids = confirmIds(g.transaction_ids, deselected)
  const known = g.transaction_ids.filter((id) => byId.has(id))
  const hidden = g.transaction_ids.length - known.length

  const bulk = useApiMutation(() => api.post('/review/bulk-confirm', { transaction_ids: ids, category_id: Number(category) }), MONEY_AREAS)

  return (
    <section className="tile group-card" aria-label={g.label}>
      <header className="group-head">
        <div>
          <h3>{g.label}</h3>
          <p className="muted">{g.count === 1 ? '1 Buchung' : `${g.count} Buchungen`} · <Money value={g.total} signed /></p>
        </div>
        <SelectField label="Kategorie" value={category} onChange={setCategory} placeholder="Kategorie wählen" options={options} />
        <Button variant="primary" icon="check" busy={bulk.isPending} disabled={!category || ids.length === 0}
          onClick={() => bulk.mutate(undefined, {
            onSuccess: () => toast.ok(ids.length === 1 ? '1 Buchung bestätigt' : `${ids.length} Buchungen bestätigt`),
            onError: toast.error,
          })}>
          {ids.length === g.count ? 'Alle bestätigen' : `${ids.length} bestätigen`}
        </Button>
      </header>
      <details className="group-items">
        <summary>Buchungen ansehen und einzelne abwählen</summary>
        <ul>
          {known.map((id) => {
            const t = byId.get(id)!
            return (
              <li key={id}>
                <Checkbox label={`${shortDate(t.booking_date)} · ${t.counterparty || t.description}`}
                  checked={!deselected.has(id)} onChange={(on) => onToggle(id, on)} />
                <Money value={t.amount} signed />
              </li>
            )
          })}
        </ul>
        {hidden > 0 && <p className="muted">{hidden === 1 ? '1 weitere Buchung' : `${hidden} weitere Buchungen`} der Gruppe werden mitbestätigt.</p>}
      </details>
    </section>
  )
}
