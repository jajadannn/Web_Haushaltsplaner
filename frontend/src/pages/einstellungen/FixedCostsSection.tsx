import { useState } from 'react'
import { api } from '../../api/client'
import { useApiMutation, useCategories, useFixedCosts, useTransactions, type Category, type FixedCost } from '../../api/hooks'
import { fullDate, shiftMonth, todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { Button, Checkbox, MoneyField, SelectField, TextField } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { iconForName } from '../../lib/icons'
import { useFormErrors } from '../../ui/useFormErrors'
import { filterCandidates, fixedCostCandidates, type Candidate, type ExistingFixedCost } from './fixedCostCandidates'
import { FormActions, MasterDetail, Switch } from './MasterDetail'

const INTERVAL_LABEL = {
  quarterly: { badge: 'vierteljährlich', every: 'etwa alle drei Monate' },
  semiannual: { badge: 'halbjährlich', every: 'etwa alle sechs Monate' },
  yearly: { badge: 'jährlich', every: 'etwa einmal im Jahr' },
} as const

/**
 * Fixkosten – VORLAGE für alle Einstellungsbereiche:
 *   Liste mit Zeilen (Icon, Name, Unterzeile, Betrag/Wert, Status, Schalter)
 *   + Formular rechts mit useFormErrors, useApiMutation, Confirm vor dem Löschen.
 */

const AREAS = ['fixed-costs', 'budget'] as const

function subline(item: FixedCost, categories: Category[]): string {
  const parts = [categories.find((c) => c.id === item.category_id)?.name ?? 'ohne Kategorie']
  if (item.match_text) parts.push(`erkennt: ${item.match_text}`)
  if (item.end_date) parts.push(`endet ${fullDate(item.end_date)}`)
  else if (item.start_date) parts.push(`ab ${fullDate(item.start_date)}`)
  return parts.join(' · ')
}

export function FixedCostsSection() {
  const list = useFixedCosts()
  const categories = useCategories({ type: 'expense' })
  const toast = useToast()
  const toggle = useApiMutation(
    (item: FixedCost) => api.patch(`/fixed-costs/${item.id}`, { active: !item.active }),
    [...AREAS],
  )

  const active = (list.data ?? []).filter((f) => f.active)
  const total = fromCents(active.reduce((sum, f) => sum + toCents(f.amount), 0n))

  return (
    <MasterDetail<FixedCost>
      title="Fixkosten"
      hint="Fixkosten werden jeden Monat eingeplant. Kreditraten kommen automatisch dazu."
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
          <span className="settings-day">am {item.due_day}.</span>
          <span className={`settings-state${item.active ? ' is-on' : ''}`}>{item.active ? 'aktiv' : 'pausiert'}</span>
          <Switch
            checked={item.active}
            label={`${item.name} ${item.active ? 'pausieren' : 'aktivieren'}`}
            disabled={toggle.isPending}
            onChange={() => toggle.mutate(item, { onError: toast.error })}
          />
        </>
      )}
      footer={active.length > 0 && (
        <div className="settings-total">
          <span>Summe pro Monat</span>
          <strong className="money">{formatEuro(total)}</strong>
        </div>
      )}
      renderForm={(item, done) => (
        <FixedCostForm key={item?.id ?? 'neu'} item={item} categories={categories.data ?? []} done={done}
          existing={list.data ?? []} />
      )}
    />
  )
}

function FixedCostForm({ item, categories, done, existing }: {
  item: FixedCost | null
  categories: Category[]
  done: () => void
  existing: ExistingFixedCost[]
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
  const [picking, setPicking] = useState(false)
  const [pickedFrom, setPickedFrom] = useState<Candidate | null>(null)

  function pick(c: Candidate) {
    setName(c.name)
    // Fixkosten sind monatlich: bei Quartals-/Jahreszahlungen den Monatsanteil eintragen
    setAmount(c.monthlyAmount)
    setDueDay(String(c.dueDay))
    setCategoryId(c.latest.category_id && categories.some((k) => k.id === c.latest.category_id) ? String(c.latest.category_id) : '')
    setMatchText(c.matchText)
    setPickedFrom(c)
    setPicking(false)
  }

  const body = () => ({
    name: name.trim(),
    amount,
    due_day: Number(dueDay),
    category_id: categoryId ? Number(categoryId) : null,
    match_text: matchText.trim() || null,
    start_date: start || null,
    end_date: end || null,
    active,
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
      {!item && (
        picking ? (
          <TransactionPicker existing={existing} categories={categories} onPick={pick} onClose={() => setPicking(false)} />
        ) : (
          <div className="pick-from">
            <Button icon="list" onClick={() => setPicking(true)}>Aus Buchung übernehmen</Button>
            {pickedFrom && <span className="muted">übernommen aus der Buchung vom {fullDate(pickedFrom.latest.booking_date)}</span>}
            {pickedFrom && pickedFrom.interval !== 'monthly' && pickedFrom.interval !== 'irregular' && (
              <span className="muted" role="note">
                Die Zahlung ({formatEuro(pickedFrom.amount)}) kommt {INTERVAL_LABEL[pickedFrom.interval].every}.
                Eingetragen ist der Monatsanteil {formatEuro(pickedFrom.monthlyAmount)} – bitte prüfen.
              </span>
            )}
            {pickedFrom && pickedFrom.interval === 'irregular' && (
              <span className="muted" role="note">
                Der Rhythmus dieser Zahlung ist unklar. Bitte den Betrag als Monatsbetrag prüfen.
              </span>
            )}
          </div>
        )
      )}
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item && !picking} />
      <div className="form-grid">
        <MoneyField label="Betrag" value={amount} onChange={setAmount} error={form.errors.amount} />
        <SelectField label="Fälligkeitstag" value={dueDay} onChange={setDueDay} error={form.errors.due_day}
          options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: `am ${i + 1}.` }))}
          hint={Number(dueDay) > 28 ? 'In kürzeren Monaten am letzten Tag' : undefined} />
      </div>
      <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="ohne Kategorie"
        options={categories.filter((c) => c.active || String(c.id) === categoryId).map((c) => ({ value: String(c.id), label: c.name }))}
        error={form.errors.category_id}
        hint="Zahlungen in dieser Kategorie gelten als bezahlt." />
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

/** Auswahl aus den Ausgaben der letzten Monate – wiederkehrende Empfänger zuerst. */
function TransactionPicker({ existing, categories, onPick, onClose }: {
  existing: ExistingFixedCost[]
  categories: Category[]
  onPick: (c: Candidate) => void
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const txs = useTransactions({ kind: 'regular', amount_max: '-0.01', date_from: shiftMonth(todayISO(), -4), limit: 200 })
  const all = fixedCostCandidates(txs.data?.items ?? [], existing)
  const shown = filterCandidates(all, search).slice(0, 40)
  const categoryName = (id: number | null) => categories.find((c) => c.id === id)?.name

  return (
    <div className="tx-picker" role="group" aria-label="Fixkost aus Buchung übernehmen">
      <div className="tx-picker-head">
        <TextField label="Buchung suchen" value={search} onChange={setSearch} placeholder="z. B. Stadtwerke, Netflix" autoFocus />
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Auswahl schließen"><Icon name="close" /></button>
      </div>
      {txs.isLoading && <Loading />}
      {txs.isError && <ErrorBox error={txs.error} onRetry={() => txs.refetch()} />}
      {txs.isSuccess && shown.length === 0 && (
        <EmptyState icon="search" title="Keine passende Buchung">
          {search ? 'Anderen Suchbegriff versuchen.' : 'In den letzten vier Monaten gibt es keine Ausgaben, die nicht schon als Fixkost erfasst sind.'}
        </EmptyState>
      )}
      {shown.length > 0 && (
        <ul className="tx-picker-list">
          {shown.map((c) => (
            <li key={c.key}>
              <button type="button" className="tx-picker-row" onClick={() => onPick(c)}>
                <span className="tx-picker-top">
                  <strong>{c.name}</strong>
                  <span className="money">{formatEuro(c.amount)}</span>
                </span>
                <span className="tx-picker-sub">
                  {c.monthly && <span className="tx-picker-monthly">monatlich</span>}
                  {c.interval !== 'monthly' && c.interval !== 'irregular' && (
                    <span className="tx-picker-monthly">{INTERVAL_LABEL[c.interval].badge} · {formatEuro(c.monthlyAmount)} / Monat</span>
                  )}
                  am {c.dueDay}. · {categoryName(c.latest.category_id) ?? 'ohne Kategorie'}
                  {c.months >= 2 ? ` · in ${c.months} Monaten` : ` · zuletzt ${fullDate(c.latest.booking_date)}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
