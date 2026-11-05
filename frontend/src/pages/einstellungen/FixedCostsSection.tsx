import { useState } from 'react'
import { api } from '../../api/client'
import { useAccounts, useApiMutation, useCategories, useFixedCosts, type Account, type Category, type FixedCost } from '../../api/hooks'
import { fullDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { Checkbox, MoneyField, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { iconForName } from '../../lib/icons'
import { useFormErrors } from '../../ui/useFormErrors'
import { DetectedFixedCosts } from './DetectedFixedCosts'
import { FixedCostAmounts } from './FixedCostAmounts'
import { FixedCostPayments } from './FixedCostPayments'
import { INTERVAL_OPTIONS, intervalLabel } from './suggestions'
import { FormActions, MasterDetail, Switch } from './MasterDetail'

/**
 * Fixkosten – VORLAGE für alle Einstellungsbereiche:
 *   Liste mit Zeilen (Icon, Name, Unterzeile, Betrag/Wert, Status, Schalter)
 *   + Formular rechts mit useFormErrors, useApiMutation, Confirm vor dem Löschen.
 */

const AREAS = ['fixed-costs', 'budget', 'forecast'] as const

function subline(item: FixedCost, categories: Category[]): string {
  const parts = [categories.find((c) => c.id === item.category_id)?.name ?? 'ohne Kategorie']
  if (item.interval_months > 1) parts.push(intervalLabel(item.interval_months))
  if (item.match_text) parts.push(`erkennt: ${item.match_text}`)
  if (item.end_date) parts.push(`endet ${fullDate(item.end_date)}`)
  else if (item.start_date) parts.push(`ab ${fullDate(item.start_date)}`)
  return parts.join(' · ')
}

export function FixedCostsSection() {
  const list = useFixedCosts()
  const categories = useCategories({ type: 'expense' })
  const accounts = useAccounts()
  const toast = useToast()
  const toggle = useApiMutation(
    (item: FixedCost) => api.patch(`/fixed-costs/${item.id}`, { active: !item.active }),
    [...AREAS],
  )

  const active = (list.data ?? []).filter((f) => f.active)
  // Nur monatliche Fixkosten zählen im Spielraum; die übrigen erscheinen als Rücklage
  const monthly = active.filter((f) => f.interval_months === 1)
  const total = fromCents(monthly.reduce((sum, f) => sum + toCents(f.amount), 0n))

  return (
    <>
    <MasterDetail<FixedCost>
      title="Fixkosten"
      hint="Monatliche Fixkosten werden jeden Monat eingeplant, Kreditraten kommen automatisch dazu. Vierteljährliche, halbjährliche und jährliche Kosten erscheinen als Rücklage."
      createLabel="Fixkost anlegen"
      items={list.data}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'calendar', title: 'Noch keine Fixkosten', text: 'Miete, Strom, Handy, Versicherungen und Abos einmal eintragen – der Spielraum rechnet sie jeden Monat ein.' }}
      formTitle={(item) => item?.name ?? 'Neue Fixkost'}
      renderRow={(item) => (
        <>
          <span className="row-icon"><Icon name={iconForName(item.name, iconForName(categories.data?.find((c) => c.id === item.category_id)?.name))} size={26} /></span>
          <span className="row-main">
            <strong>{item.name}</strong>
            <span>{subline(item, categories.data ?? [])}</span>
          </span>
          <span className="settings-value money">{formatEuro(item.amount)}</span>
          <span className="settings-day">{item.interval_months > 1 && item.first_due_date ? fullDate(item.first_due_date) : `am ${item.due_day}.`}</span>
          <span className={`settings-state${item.active ? ' is-on' : ''}`}>{item.active ? 'aktiv' : 'pausiert'}</span>
          <Switch
            checked={item.active}
            label={`${item.name} ${item.active ? 'pausieren' : 'aktivieren'}`}
            disabled={toggle.isPending}
            onChange={() => toggle.mutate(item, { onError: toast.error })}
          />
        </>
      )}
      footer={monthly.length > 0 && (
        <div className="settings-total">
          <span>Summe pro Monat (monatliche)</span>
          <strong className="money">{formatEuro(total)}</strong>
        </div>
      )}
      renderForm={(item, done) => (
        <FixedCostForm key={item?.id ?? 'neu'} item={item} categories={categories.data ?? []} done={done}
          accounts={accounts.data ?? []} />
      )}
    />
    <DetectedFixedCosts />
    </>
  )
}

function FixedCostForm({ item, categories, accounts, done }: {
  item: FixedCost | null
  categories: Category[]
  accounts: Account[]
  done: () => void
}) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [amount, setAmount] = useState<string | null>(item?.amount ?? null)
  const [dueDay, setDueDay] = useState(String(item?.due_day ?? 1))
  const [categoryId, setCategoryId] = useState(item?.category_id ? String(item.category_id) : '')
  const [matchText, setMatchText] = useState(item?.match_text ?? '')
  const [start, setStart] = useState(item?.start_date ?? '')
  const [end, setEnd] = useState(item?.end_date ?? '')
  const [active, setActive] = useState(item?.active ?? true)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [interval, setIntervalValue] = useState(String(item?.interval_months ?? 1))
  const [firstDue, setFirstDue] = useState(item?.first_due_date ?? '')
  const [accountId, setAccountId] = useState(item?.account_id ? String(item.account_id) : '')

  const body = () => ({
    name: name.trim(),
    amount,
    due_day: Number(dueDay),
    category_id: categoryId ? Number(categoryId) : null,
    match_text: matchText.trim() || null,
    start_date: start || null,
    end_date: end || null,
    active,
    interval_months: Number(interval),
    first_due_date: interval === '1' ? null : firstDue || null,
    account_id: accountId ? Number(accountId) : null,
  })
  const save = useApiMutation(
    () => (item ? api.patch(`/fixed-costs/${item.id}`, body()) : api.post('/fixed-costs', body())),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/fixed-costs/${item!.id}`), [...AREAS])

  function submit() {
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      amount: !amount && 'Bitte einen Betrag eingeben',
      first_due_date: interval !== '1' && !firstDue && 'Bitte die erste Fälligkeit angeben',
      match_text: matchText.trim().length === 1 && 'Mindestens 2 Zeichen',
      end_date: start && end && end < start && 'Ende liegt vor dem Beginn',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => {
        toast.ok(item ? 'Fixkost gespeichert' : 'Fixkost angelegt')
        done()
      },
      onError: form.fail,
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} />
      <div className="form-grid">
        <MoneyField label={interval === '1' ? 'Betrag' : 'Betrag pro Zahlung'} value={amount} onChange={setAmount} error={form.errors.amount} />
        <SelectField label="Fälligkeitstag" value={dueDay} onChange={setDueDay} error={form.errors.due_day}
          options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: `am ${i + 1}.` }))}
          hint={Number(dueDay) > 28 ? 'In kürzeren Monaten am letzten Tag' : undefined} />
      </div>
      <div className="form-grid">
        <SelectField label="Rhythmus" value={interval} onChange={setIntervalValue} options={INTERVAL_OPTIONS} error={form.errors.interval_months} />
        {interval !== '1' && (
          <TextField label="Erste Fälligkeit" type="date" value={firstDue} onChange={setFirstDue} error={form.errors.first_due_date}
            hint="Danach alle paar Monate am selben Tag." />
        )}
      </div>
      <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="ohne Kategorie"
        options={categories.filter((c) => c.active || String(c.id) === categoryId).map((c) => ({ value: String(c.id), label: c.name }))}
        error={form.errors.category_id}
        hint="Zahlungen in dieser Kategorie gelten als bezahlt." />
      <SelectField label="Zahlkonto (optional)" value={accountId} onChange={setAccountId} placeholder="egal"
        options={accounts.filter((a) => a.type !== 'loan' || String(a.id) === accountId).map((a) => ({ value: String(a.id), label: a.name }))}
        error={form.errors.account_id} hint="Nur Zahlungen von diesem Konto gelten als bezahlt." />
      <TextField label="Erkennen an (Text in der Buchung)" value={matchText} onChange={setMatchText}
        placeholder="z. B. Stadtwerke" maxLength={100} error={form.errors.match_text}
        hint="Steht dieser Text im Empfänger oder Verwendungszweck, ist die Fixkost bezahlt." />
      <div className="form-grid">
        <TextField label="Beginn (optional)" type="date" value={start} onChange={setStart} error={form.errors.start_date} />
        <TextField label="Ende (optional)" type="date" value={end} onChange={setEnd} error={form.errors.end_date} />
      </div>
      <Checkbox label="aktiv" checked={active} onChange={setActive} hint="Pausierte Fixkosten zählen nicht im Spielraum." />
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined} saveLabel={item ? 'Speichern' : 'Anlegen'} />
      {item && <FixedCostAmounts fixedCostId={item.id} />}
      {item && <FixedCostPayments fixedCostId={item.id} />}
      {item && (
        <Confirm
          open={confirmDelete}
          title="Fixkost löschen?"
          text={`„${item.name}“ wird nicht mehr eingeplant. Bereits gebuchte Zahlungen bleiben erhalten.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Fixkost gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </form>
  )
}
