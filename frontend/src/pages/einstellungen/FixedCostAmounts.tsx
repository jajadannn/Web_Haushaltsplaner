import { useState } from 'react'
import { api } from '../../api/client'
import { SUGGESTION_AREAS, useApiMutation, useFixedCostAmounts } from '../../api/hooks'
import { monthLabel } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, MoneyField, TextField } from '../../ui/controls'
import { ErrorBox, Loading } from '../../ui/blocks'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'

/** Betragsverlauf einer Fixkost und „Betrag ab Monat ändern“ (frühere Monate behalten ihren Betrag). */
export function FixedCostAmounts({ fixedCostId }: { fixedCostId: number }) {
  const toast = useToast()
  const form = useFormErrors()
  const amounts = useFixedCostAmounts(fixedCostId)
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState('')
  const [amount, setAmount] = useState<string | null>(null)
  const items = [...(amounts.data ?? [])].sort((a, b) => b.valid_from.localeCompare(a.valid_from))

  const add = useApiMutation(
    () => api.post(`/fixed-costs/${fixedCostId}/amounts`, { valid_from: `${month}-01`, amount }), SUGGESTION_AREAS)

  // Ein <form> darf nicht im Formular der Fixkost stecken – deshalb ein Knopf mit eigenem Handler
  function submit() {
    if (!form.check({
      valid_from: !/^\d{4}-\d{2}$/.test(month) && 'Bitte einen Monat wählen',
      amount: !amount && 'Bitte einen Betrag eingeben',
    })) return
    add.mutate(undefined, {
      onSuccess: () => { toast.ok('Neuer Betrag gespeichert'); setOpen(false); setMonth(''); setAmount(null) },
      onError: form.fail,
    })
  }

  return (
    <section className="fc-payments" aria-label="Betragsverlauf">
      <h4>Betragsverlauf</h4>
      {amounts.isLoading && <Loading />}
      {amounts.isError && <ErrorBox error={amounts.error} onRetry={() => amounts.refetch()} />}
      {amounts.isSuccess && items.length === 0 && <p className="muted">Der Betrag hat sich bisher nicht geändert.</p>}
      {items.length > 0 && (
        <ul className="fc-payments-list">
          {items.map((a) => (
            <li key={a.id}>
              <span><strong>ab {monthLabel(a.valid_from)}</strong></span>
              <span className="money">{formatEuro(a.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {open ? (
        <div className="settings-form-body">
          <div className="form-grid">
            <TextField label="Ab Monat" type="month" value={month} onChange={setMonth} error={form.errors.valid_from} />
            <MoneyField label="Neuer Betrag" value={amount} onChange={setAmount} error={form.errors.amount} />
          </div>
          {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
          <div className="form-actions">
            <Button onClick={() => setOpen(false)}>Abbrechen</Button>
            <span className="spacer" />
            <Button variant="primary" busy={add.isPending} onClick={submit}>Betrag speichern</Button>
          </div>
        </div>
      ) : (
        <Button icon="edit" onClick={() => setOpen(true)}>Betrag ab Monat ändern</Button>
      )}
    </section>
  )
}
