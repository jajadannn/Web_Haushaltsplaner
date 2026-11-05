import { useState } from 'react'
import { api } from '../../api/client'
import {
  SUGGESTION_AREAS, useAccounts, useApiMutation, useCategories, useExpectedIncomes, useSuggestions,
  type Account, type Category, type ExpectedIncome,
} from '../../api/hooks'
import { fullDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Icon } from '../../ui/Icon'
import { Button, Checkbox, MoneyField, SelectField, TextField } from '../../ui/controls'
import { EmptyState, Loading } from '../../ui/blocks'
import { Confirm, useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail, Switch } from './MasterDetail'
import { INTERVAL_OPTIONS, intervalLabel, parseIncomeSeries, sortSuggestions } from './suggestions'

/** Erwartete Einnahmen (Gehalt, Rente, Miete …): fließen in die Kontovorschau ein. */

const AREAS = ['expected-incomes', 'forecast', 'suggestions'] as const

function rangeText(item: { amount_min: string | null; amount_max: string | null }): string | null {
  return item.amount_min && item.amount_max ? `${formatEuro(item.amount_min)} bis ${formatEuro(item.amount_max)}` : null
}

export function IncomesSection() {
  const list = useExpectedIncomes()
  const categories = useCategories({ type: 'income' })
  const accounts = useAccounts()
  const toast = useToast()
  const toggle = useApiMutation(
    (item: ExpectedIncome) => api.patch(`/expected-incomes/${item.id}`, { active: !item.active }), [...AREAS])

  return (
    <>
      <MasterDetail<ExpectedIncome>
        title="Erwartete Einnahmen"
        hint="Gehalt, Rente oder Miete, die regelmäßig kommen. Die Kontovorschau auf der Startseite rechnet sie mit ein."
        createLabel="Einnahme anlegen"
        items={list.data}
        isLoading={list.isLoading}
        error={list.error}
        onRetry={() => list.refetch()}
        empty={{ icon: 'coins', title: 'Noch keine erwarteten Einnahmen', text: 'Lege dein Gehalt an oder übernimm unten einen erkannten Vorschlag.' }}
        formTitle={(item) => item?.name ?? 'Neue erwartete Einnahme'}
        renderRow={(item) => (
          <>
            <span className="row-icon"><Icon name="coins" size={26} /></span>
            <span className="row-main">
              <strong>{item.name}</strong>
              <span>
                {[categories.data?.find((c) => c.id === item.category_id)?.name ?? 'ohne Kategorie', intervalLabel(item.interval_months),
                  rangeText(item), item.match_text ? `erkennt: ${item.match_text}` : null].filter(Boolean).join(' · ')}
              </span>
            </span>
            <span className="settings-value money">{formatEuro(item.amount)}</span>
            <span className="settings-day">{item.interval_months > 1 && item.first_due_date ? fullDate(item.first_due_date) : `am ${item.due_day}.`}</span>
            <span className={`settings-state${item.active ? ' is-on' : ''}`}>{item.active ? 'aktiv' : 'pausiert'}</span>
            <Switch checked={item.active} label={`${item.name} ${item.active ? 'pausieren' : 'aktivieren'}`}
              disabled={toggle.isPending} onChange={() => toggle.mutate(item, { onError: toast.error })} />
          </>
        )}
        renderForm={(item, done) => (
          <IncomeForm key={item?.id ?? 'neu'} item={item} categories={categories.data ?? []} accounts={accounts.data ?? []} done={done} />
        )}
      />
      <DetectedIncomes />
    </>
  )
}

function IncomeForm({ item, categories, accounts, done }: {
  item: ExpectedIncome | null
  categories: Category[]
  accounts: Account[]
  done: () => void
}) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [amount, setAmount] = useState<string | null>(item?.amount ?? null)
  const [min, setMin] = useState<string | null>(item?.amount_min ?? null)
  const [max, setMax] = useState<string | null>(item?.amount_max ?? null)
  const [interval, setIntervalValue] = useState(String(item?.interval_months ?? 1))
  const [dueDay, setDueDay] = useState(String(item?.due_day ?? 1))
  const [first, setFirst] = useState(item?.first_due_date ?? '')
  const [accountId, setAccountId] = useState(item?.account_id ? String(item.account_id) : '')
  const [categoryId, setCategoryId] = useState(item?.category_id ? String(item.category_id) : '')
  const [matchText, setMatchText] = useState(item?.match_text ?? '')
  const [active, setActive] = useState(item?.active ?? true)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const body = () => ({
    name: name.trim(),
    amount,
    amount_min: min,
    amount_max: max,
    interval_months: Number(interval),
    due_day: Number(dueDay),
    first_due_date: interval === '1' ? null : first || null,
    account_id: accountId ? Number(accountId) : null,
    category_id: categoryId ? Number(categoryId) : null,
    match_text: matchText.trim() || null,
    active,
  })
  const save = useApiMutation(
    () => (item ? api.patch(`/expected-incomes/${item.id}`, body()) : api.post('/expected-incomes', body())), [...AREAS])
  const remove = useApiMutation(() => api.delete(`/expected-incomes/${item!.id}`), [...AREAS])

  function submit() {
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      amount: !amount && 'Bitte einen Betrag eingeben',
      amount_min: (!!min !== !!max) && 'Spanne bitte mit „von“ und „bis“ angeben',
      first_due_date: interval !== '1' && !first && 'Bitte die erste Fälligkeit angeben',
      match_text: matchText.trim().length === 1 && 'Mindestens 2 Zeichen',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Einnahme gespeichert' : 'Einnahme angelegt'); done() },
      onError: form.fail,
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} placeholder="z. B. Gehalt" />
      <div className="form-grid">
        <MoneyField label="Betrag" value={amount} onChange={setAmount} error={form.errors.amount} />
        <SelectField label="Kommt am" value={dueDay} onChange={setDueDay} error={form.errors.due_day}
          options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: `am ${i + 1}.` }))} />
      </div>
      <div className="form-grid">
        <MoneyField label="Spanne von (optional)" value={min} onChange={setMin} error={form.errors.amount_min} />
        <MoneyField label="Spanne bis (optional)" value={max} onChange={setMax} error={form.errors.amount_max} />
      </div>
      <div className="form-grid">
        <SelectField label="Rhythmus" value={interval} onChange={setIntervalValue} options={INTERVAL_OPTIONS} error={form.errors.interval_months} />
        {interval !== '1' && (
          <TextField label="Erste Fälligkeit" type="date" value={first} onChange={setFirst} error={form.errors.first_due_date} />
        )}
      </div>
      <SelectField label="Einnahmenkategorie" value={categoryId} onChange={setCategoryId} placeholder="ohne Kategorie"
        options={categories.filter((c) => c.active || String(c.id) === categoryId).map((c) => ({ value: String(c.id), label: c.name }))}
        error={form.errors.category_id} />
      <SelectField label="Zahlkonto (optional)" value={accountId} onChange={setAccountId} placeholder="egal"
        options={accounts.filter((a) => !a.archived_at && a.type !== 'loan').map((a) => ({ value: String(a.id), label: a.name }))}
        error={form.errors.account_id} />
      <TextField label="Erkennen an (Text in der Buchung)" value={matchText} onChange={setMatchText}
        placeholder="z. B. Arbeitgeber GmbH" maxLength={100} error={form.errors.match_text} />
      <Checkbox label="aktiv" checked={active} onChange={setActive} hint="Pausierte Einnahmen fehlen in der Vorschau." />
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined} saveLabel={item ? 'Speichern' : 'Anlegen'} />
      {item && (
        <Confirm open={confirmDelete} title="Einnahme löschen?" text={`„${item.name}“ wird in der Vorschau nicht mehr erwartet.`}
          confirmLabel="Löschen" busy={remove.isPending} onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Einnahme gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })} />
      )}
    </form>
  )
}

/** Erkannte Einnahmenserien: übernehmen legt eine erwartete Einnahme an. */
function DetectedIncomes() {
  const toast = useToast()
  const list = useSuggestions({ kind: 'income_series' })
  const accept = useApiMutation((id: number) => api.post(`/suggestions/${id}/accept`), SUGGESTION_AREAS)
  const reject = useApiMutation((id: number) => api.post(`/suggestions/${id}/reject`), SUGGESTION_AREAS)
  const shown = sortSuggestions((list.data ?? []).filter((s) => s.status === 'open'))
  const busy = accept.isPending || reject.isPending
  return (
    <section className="settings-section detected" aria-labelledby="detected-incomes-title">
      <header className="settings-head">
        <div>
          <h2 id="detected-incomes-title">Erkannte Einnahmen</h2>
          <p className="muted">Regelmäßige Eingänge, die der Finanzplaner in deinen Buchungen gefunden hat.</p>
        </div>
      </header>
      <div className="tile">
        {list.isLoading && <Loading />}
        {list.isSuccess && shown.length === 0 && (
          <EmptyState icon="search" title="Keine Vorschläge">Es gibt gerade keine erkannten Einnahmen.</EmptyState>
        )}
        <ul className="rows">
          {shown.map((s) => {
            const p = parseIncomeSeries(s.payload)
            const range = p.amountMin && p.amountMax ? `${formatEuro(p.amountMin)} bis ${formatEuro(p.amountMax)}` : null
            return (
              <li key={s.id} className="row-card detected-row">
                <div className="detected-card">
                  <div className="detected-top">
                    <strong>{p.name || 'Einnahme'}</strong>
                    <span className="money">{p.amount ? formatEuro(p.amount) : '–'}</span>
                  </div>
                  <p className="muted">
                    {intervalLabel(p.intervalMonths)} · am {p.dueDay}.{range && ` · Spanne ${range}`}
                    {p.firstDueDate && ` · erste Fälligkeit ${fullDate(p.firstDueDate)}`}
                  </p>
                  {s.reason && <p className="detected-reason">{s.reason}</p>}
                  <div className="detected-actions">
                    <Button variant="primary" icon="check" disabled={busy}
                      onClick={() => accept.mutate(s.id, { onSuccess: () => toast.ok('Erwartete Einnahme angelegt'), onError: toast.error })}>Übernehmen</Button>
                    <Button variant="danger" disabled={busy}
                      onClick={() => reject.mutate(s.id, { onSuccess: () => toast.ok('Vorschlag abgelehnt'), onError: toast.error })}>Ablehnen</Button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}
