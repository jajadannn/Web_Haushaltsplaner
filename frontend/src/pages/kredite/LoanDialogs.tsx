import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import {
  MONEY_AREAS, useAccounts, useApiMutation, useInstitutions, useTransactions,
  type Loan, type ScheduleEntry, type Transaction,
} from '../../api/hooks'
import { addDays, fullDate, todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { Button, Checkbox, MoneyField, Segmented, SelectField, TextField } from '../../ui/controls'
import { Confirm, Dialog, useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import { LOAN_TYPE_LABEL, parseRate, rateLabel } from './labels'

const LOAN_AREAS = [...MONEY_AREAS, 'fixed-costs'] as const

function rateToInput(rate: string | number | undefined): string {
  if (rate === undefined || rate === null) return ''
  return rateLabel(rate).replace(' %', '')
}

// --- Rate buchen -------------------------------------------------------------------

type PayMode = 'new' | 'link'

export function PaymentDialog({ loan, next, onClose }: { loan: Loan; next?: ScheduleEntry; onClose: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const accounts = useAccounts()
  const [mode, setMode] = useState<PayMode>('new')
  const [date, setDate] = useState(next && next.due_date <= todayISO() ? next.due_date : todayISO())
  const [amount, setAmount] = useState<string | null>(next?.planned_installment ?? loan.installment_amount ?? null)
  const [accountId, setAccountId] = useState(String(loan.payment_account_id ?? ''))
  const [own, setOwn] = useState(false)
  const [interest, setInterest] = useState<string | null>(next?.planned_interest ?? null)
  const [principal, setPrincipal] = useState<string | null>(next?.planned_principal ?? null)
  const [extra, setExtra] = useState<string | null>(next?.planned_extra ?? '0.00')
  const [linked, setLinked] = useState<number | null>(null)

  // Kandidaten zum Verknüpfen: Abbuchungen vom Zahlkonto rund um die Fälligkeit
  const around = next?.due_date ?? todayISO()
  const candidates = useTransactions({
    account_ids: loan.payment_account_id ? [loan.payment_account_id] : undefined,
    date_from: addDays(around, -20),
    date_to: addDays(around, 20),
    amount_max: '-0.01',
    limit: 50,
  })
  const linkable = (candidates.data?.items ?? []).filter((t) => t.source !== 'loan' && !t.splits.length && t.kind === 'regular')

  const splitSum = interest && principal && extra ? fromCents(toCents(interest) + toCents(principal) + toCents(extra)) : null
  const payAmount = mode === 'link' ? linkable.find((t) => t.id === linked)?.amount.replace('-', '') ?? null : amount

  const save = useApiMutation(() => {
    const body: Record<string, unknown> = next ? { schedule_seq: next.seq } : {}
    if (mode === 'link') body.transaction_id = linked
    else Object.assign(body, { booking_date: date, amount, account_id: accountId ? Number(accountId) : undefined })
    if (own) Object.assign(body, { interest, principal, extra })
    return api.post(`/loans/${loan.id}/payments`, body)
  }, [...LOAN_AREAS])

  function submit() {
    const ok = form.check({
      amount: mode === 'new' && !amount && 'Bitte den Betrag eingeben',
      transaction_id: mode === 'link' && !linked && 'Bitte eine Buchung wählen',
      split: own && (!splitSum || splitSum !== payAmount) && 'Zinsen + Tilgung + Gebühren müssen den Zahlbetrag ergeben',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => {
        toast.ok(`Rate ${next ? next.seq : ''} gebucht`.replace('  ', ' '))
        onClose()
      },
      onError: form.fail,
    })
  }

  return (
    <Dialog open onClose={onClose} title={`Rate buchen · ${loan.name}`} wide
      footer={<>
        <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
        <Button variant="primary" icon="check" busy={save.isPending} onClick={submit}>Rate buchen</Button>
      </>}>
      {next && (
        <p className="dialog-text">
          Rate {next.seq}, fällig am {fullDate(next.due_date)}: {formatEuro(next.planned_installment)}
          {' '}({formatEuro(next.planned_interest)} Zinsen, {formatEuro(next.planned_principal)} Tilgung
          {toCents(next.planned_extra) > 0n ? `, ${formatEuro(next.planned_extra)} Gebühren` : ''}).
        </p>
      )}
      <Segmented<PayMode> label="Zahlung" value={mode} onChange={setMode} options={[
        { value: 'new', label: 'Neue Zahlung erfassen' },
        { value: 'link', label: 'Vorhandene Buchung verknüpfen' },
      ]} />

      {mode === 'new' ? (
        <div className="form-grid">
          <MoneyField label="Betrag" value={amount} onChange={setAmount} error={form.errors.amount} />
          <TextField label="Datum" type="date" value={date} onChange={setDate} error={form.errors.booking_date} />
          <SelectField className="span-2" label="Vom Konto" value={accountId} onChange={setAccountId} placeholder="Konto wählen"
            options={(accounts.data ?? []).filter((a) => a.type !== 'loan' && !a.archived_at).map((a) => ({ value: String(a.id), label: a.name }))}
            error={form.errors.account_id} />
        </div>
      ) : (
        <div className="field">
          <span className="field-label">Abbuchung vom Zahlkonto (±20 Tage um die Fälligkeit)</span>
          {linkable.length === 0 ? (
            <p className="muted">Keine passende Abbuchung gefunden. Importiere zuerst den Kontoauszug oder erfasse die Zahlung neu.</p>
          ) : (
            <ul className="rows link-list" role="radiogroup" aria-label="Buchung wählen">
              {linkable.map((t: Transaction) => (
                <li key={t.id}>
                  <button type="button" role="radio" aria-checked={linked === t.id}
                    className={`row-card link-row${linked === t.id ? ' is-selected' : ''}`} onClick={() => setLinked(t.id)}>
                    <span className="row-main"><strong>{t.counterparty || t.description}</strong><span>{fullDate(t.booking_date)} · {t.description}</span></span>
                    <span className="row-end money">{formatEuro(t.amount)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {form.errors.transaction_id && <p className="field-error">{form.errors.transaction_id}</p>}
        </div>
      )}

      <Checkbox label="Aufteilung selbst angeben" checked={own} onChange={setOwn}
        hint="Sonst schlägt der Finanzplaner sie vor: zuerst Gebühren, dann Zinsen, der Rest ist Tilgung. Weicht die Bank ab, hier ihre Zahlen eintragen." />
      {own && (
        <div className="form-grid three">
          <MoneyField label="Zinsen" value={interest} onChange={setInterest} />
          <MoneyField label="Tilgung" value={principal} onChange={setPrincipal} />
          <MoneyField label="Gebühren" value={extra} onChange={setExtra} />
          <p className={`span-3 split-rest${splitSum && splitSum === payAmount ? ' is-ok' : ''}`}>
            Summe {splitSum ? formatEuro(splitSum) : '–'}{payAmount ? ` von ${formatEuro(payAmount)}` : ''}
          </p>
        </div>
      )}
      {form.errors.split && <p className="field-error">{form.errors.split}</p>}
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
    </Dialog>
  )
}

// --- Zinsen / Gebühren nachbuchen ---------------------------------------------------

export function ChargeDialog({ loan, onClose }: { loan: Loan; onClose: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [type, setType] = useState<'interest' | 'fee'>('interest')
  const [amount, setAmount] = useState<string | null>(null)
  const [date, setDate] = useState(todayISO())
  const [text, setText] = useState('')
  const save = useApiMutation(() => api.post(`/loans/${loan.id}/charges`, {
    charge_type: type, amount, booking_date: date, description: text.trim() || null,
  }), [...LOAN_AREAS])

  function submit() {
    if (!form.check({ amount: !amount && 'Bitte den Betrag eingeben' })) return
    save.mutate(undefined, { onSuccess: () => { toast.ok('Belastung gebucht'); onClose() }, onError: form.fail })
  }

  return (
    <Dialog open onClose={onClose} title="Zinsen oder Gebühr nachbuchen"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
        <Button variant="primary" busy={save.isPending} onClick={submit}>Buchen</Button>
      </>}>
      <p className="dialog-text">
        Für Beträge, die die Bank direkt dem Kreditkonto belastet (z. B. Zinsen in einer Ratenpause). Sie erhöhen die Restschuld.
      </p>
      <Segmented label="Art" value={type} onChange={setType} options={[
        { value: 'interest', label: 'Zinsen' },
        { value: 'fee', label: 'Gebühr' },
      ]} />
      <div className="form-grid">
        <MoneyField label="Betrag" value={amount} onChange={setAmount} error={form.errors.amount} />
        <TextField label="Datum" type="date" value={date} onChange={setDate} error={form.errors.booking_date} />
        <TextField className="span-2" label="Text (optional)" value={text} onChange={setText} maxLength={1000} />
      </div>
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
    </Dialog>
  )
}

// --- Kredit anlegen / Konditionen ändern ---------------------------------------------

type Basis = 'rate' | 'term'

export function LoanFormDialog({ loan, onClose, onSaved, onDeleted }: {
  loan: Loan | null
  onClose: () => void
  onSaved: (loan: Loan) => void
  onDeleted?: () => void
}) {
  const toast = useToast()
  const form = useFormErrors()
  const accounts = useAccounts()
  const institutions = useInstitutions()
  const editing = loan !== null
  const [type, setType] = useState<Loan['loan_type']>(loan?.loan_type ?? 'annuity')
  const [name, setName] = useState(loan?.name ?? '')
  const [lender, setLender] = useState(loan?.lender_name ?? '')
  const [institution, setInstitution] = useState(loan?.institution_id ? String(loan.institution_id) : '')
  const [rate, setRate] = useState(rateToInput(loan?.annual_interest_rate))
  const [balance, setBalance] = useState<string | null>(null)
  const [balanceDate, setBalanceDate] = useState(todayISO())
  const [firstDue, setFirstDue] = useState('')
  const [basis, setBasis] = useState<Basis>(loan?.term_months && !loan.installment_amount ? 'term' : 'rate')
  const [installment, setInstallment] = useState<string | null>(loan?.installment_amount ?? null)
  const [fixedPrincipal, setFixedPrincipal] = useState<string | null>(loan?.fixed_principal ?? null)
  const [term, setTerm] = useState(loan?.term_months ? String(loan.term_months) : '')
  const [extra, setExtra] = useState<string | null>(loan?.extra_amount ?? '0.00')
  const [payAccount, setPayAccount] = useState(loan?.payment_account_id ? String(loan.payment_account_id) : '')
  const [lenderIban, setLenderIban] = useState(loan?.lender_iban ?? '')
  const [reference, setReference] = useState(loan?.payment_reference ?? '')
  const [fixedUntil, setFixedUntil] = useState(loan?.fixed_rate_until ?? '')
  const [original, setOriginal] = useState<string | null>(loan?.principal_original ?? null)
  const [disburse, setDisburse] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const ownAccounts = (accounts.data ?? []).filter((a) => a.type !== 'loan' && !a.archived_at)
  const parsedRate = parseRate(rate)

  const body = () => {
    const plan: Record<string, unknown> = {}
    if (type === 'annuity') {
      plan.installment_amount = basis === 'rate' ? installment : null
      plan.term_months = basis === 'term' && term ? Number(term) : null
    } else if (type === 'installment') {
      plan.fixed_principal = basis === 'rate' ? fixedPrincipal : null
      plan.term_months = basis === 'term' && term ? Number(term) : null
    } else {
      plan.installment_amount = installment
    }
    const common = {
      name: name.trim(), lender_name: lender.trim(), annual_interest_rate: parsedRate,
      payment_account_id: payAccount ? Number(payAccount) : null,
      lender_iban: lenderIban.trim() || null, payment_reference: reference.trim() || null,
      fixed_rate_until: fixedUntil || null, extra_amount: extra ?? '0.00', ...plan,
    }
    if (editing) return common
    return {
      ...common, loan_type: type, current_balance: balance, balance_date: balanceDate,
      first_due_date: firstDue || null, institution_id: institution ? Number(institution) : null,
      principal_original: original, disbursement_account_id: disburse && payAccount ? Number(payAccount) : null,
    }
  }

  const save = useApiMutation(
    () => (editing ? api.patch<Loan>(`/loans/${loan.id}`, body()) : api.post<Loan>('/loans', body())),
    [...LOAN_AREAS],
  )
  // Erst die Detailansicht verlassen, dann neu laden – sonst fragt sie Plan und Zahlungen
  // des gelöschten Kredits noch einmal ab (404)
  const queryClient = useQueryClient()
  const remove = useMutation({ mutationFn: () => api.delete(`/loans/${loan!.id}`) })
  const refreshAfterDelete = (id: number) => {
    const own = (key: readonly unknown[]) => String(key[3] ?? '').startsWith(`/loans/${id}/`)
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] === 'p' && own(q.queryKey) })
    queryClient.invalidateQueries({
      predicate: (q) => q.queryKey[0] === 'p' && (LOAN_AREAS as readonly unknown[]).includes(q.queryKey[2]) && !own(q.queryKey),
    })
  }

  function submit() {
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      lender_name: !lender.trim() && 'Bitte den Kreditgeber eingeben',
      annual_interest_rate: !parsedRate && 'Zinssatz wie 4,95 eingeben',
      current_balance: !editing && !balance && 'Bitte die Restschuld eingeben',
      installment_amount: type !== 'installment' && basis === 'rate' && type === 'annuity' && !installment && 'Rate oder Laufzeit angeben',
      fixed_principal: type === 'installment' && basis === 'rate' && !fixedPrincipal && 'Tilgung oder Laufzeit angeben',
      term_months: basis === 'term' && type !== 'private' && !(Number(term) >= 1) && 'Laufzeit in Monaten angeben',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: (saved) => { toast.ok(editing ? 'Konditionen gespeichert – Plan neu berechnet' : 'Kredit angelegt'); onSaved(saved) },
      onError: form.fail,
    })
  }

  return (
    <Dialog open onClose={onClose} wide title={editing ? `Konditionen · ${loan.name}` : 'Kredit anlegen'}
      footer={<>
        {editing && <Button variant="danger" onClick={() => setConfirmDelete(true)}>Kredit löschen</Button>}
        <span className="spacer" />
        <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
        <Button variant="primary" busy={save.isPending} onClick={submit}>{editing ? 'Speichern' : 'Anlegen'}</Button>
      </>}>
      {!editing && (
        <Segmented<Loan['loan_type']> label="Kreditart" value={type} onChange={setType} options={[
          { value: 'annuity', label: LOAN_TYPE_LABEL.annuity },
          { value: 'installment', label: LOAN_TYPE_LABEL.installment },
          { value: 'private', label: LOAN_TYPE_LABEL.private },
        ]} />
      )}
      <p className="dialog-text">
        {type === 'annuity' && 'Gleichbleibende Rate; der Zinsanteil sinkt, die Tilgung steigt.'}
        {type === 'installment' && 'Gleichbleibende Tilgung; die Rate sinkt mit der Restschuld. Auch für 0-%-Finanzierungen.'}
        {type === 'private' && 'Ohne festen Plan, z. B. von Familie oder Freunden – oft 0 %. Zahlungen sind frei.'}
        {editing && ' Änderungen wirken auf alle offenen Raten; bezahlte bleiben unverändert.'}
      </p>

      <div className="form-grid">
        <TextField label="Name" value={name} onChange={setName} placeholder="z. B. Autokredit" maxLength={100} error={form.errors.name} />
        <TextField label="Kreditgeber" value={lender} onChange={setLender} placeholder="z. B. Autobank" maxLength={100} error={form.errors.lender_name} />
        <TextField label="Zinssatz (% pro Jahr)" value={rate} onChange={setRate} inputMode="decimal" placeholder="4,95" error={form.errors.annual_interest_rate} />
        {!editing ? (
          <SelectField label="Bank (optional)" value={institution} onChange={setInstitution} placeholder="keine"
            options={(institutions.data ?? []).map((i) => ({ value: String(i.id), label: i.name }))} />
        ) : <TextField label="Zinsbindung bis (optional)" type="date" value={fixedUntil} onChange={setFixedUntil} />}
      </div>

      {!editing && (
        <div className="form-grid">
          <MoneyField label="Restschuld heute" value={balance} onChange={setBalance} error={form.errors.current_balance}
            hint="Bei laufenden Krediten die aktuelle Restschuld laut Bank – nicht die ursprüngliche Summe." />
          <TextField label="Stichtag der Restschuld" type="date" value={balanceDate} onChange={setBalanceDate} error={form.errors.balance_date} />
          <TextField label="Nächste Rate fällig am" type="date" value={firstDue} onChange={setFirstDue} error={form.errors.first_due_date}
            hint="Leer: ein Monat nach dem Stichtag." />
          <MoneyField label="Ursprüngliche Summe (optional)" value={original} onChange={setOriginal}
            hint="Nur für die Fortschrittsanzeige." />
        </div>
      )}

      {type !== 'private' && (
        <Segmented<Basis> label="Plan berechnen aus" value={basis} onChange={setBasis} options={[
          { value: 'rate', label: type === 'annuity' ? 'Monatsrate' : 'Monatliche Tilgung' },
          { value: 'term', label: 'Laufzeit' },
        ]} />
      )}
      <div className="form-grid">
        {type === 'annuity' && basis === 'rate' && (
          <MoneyField label="Monatsrate (Zins + Tilgung)" value={installment} onChange={setInstallment} error={form.errors.installment_amount} />
        )}
        {type === 'installment' && basis === 'rate' && (
          <MoneyField label="Tilgung pro Monat" value={fixedPrincipal} onChange={setFixedPrincipal} error={form.errors.fixed_principal} />
        )}
        {type !== 'private' && basis === 'term' && (
          <TextField label="Restlaufzeit in Monaten" value={term} onChange={setTerm} inputMode="numeric" error={form.errors.term_months} />
        )}
        {type === 'private' && (
          <MoneyField label="Vereinbarte Rate (optional)" value={installment} onChange={setInstallment} error={form.errors.installment_amount} />
        )}
        <MoneyField label="Gebühr/Versicherung je Rate" value={extra} onChange={setExtra} />
      </div>

      <div className="form-grid">
        <SelectField label="Rate wird gezahlt vom" value={payAccount} onChange={setPayAccount} placeholder="Konto wählen"
          options={ownAccounts.map((a) => ({ value: String(a.id), label: a.name }))} error={form.errors.payment_account_id} />
        <TextField label="IBAN des Kreditgebers (optional)" value={lenderIban} onChange={setLenderIban} maxLength={42}
          hint="Damit erkennt der Import die Rate automatisch." error={form.errors.lender_iban} />
        <TextField className="span-2" label="Verwendungszweck / Vertragsnummer (optional)" value={reference} onChange={setReference} maxLength={140} />
        {!editing && <TextField label="Zinsbindung bis (optional)" type="date" value={fixedUntil} onChange={setFixedUntil} />}
      </div>
      {!editing && payAccount && (
        <Checkbox label="Neuer Kredit: Auszahlung auf das Zahlkonto buchen" checked={disburse} onChange={setDisburse}
          hint="Bucht die Kreditsumme am Stichtag als Umbuchung vom Kreditkonto auf das gewählte Konto." />
      )}
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}

      {editing && (
        <Confirm open={confirmDelete} title="Kredit löschen?"
          text="Nur möglich, solange keine Rate gebucht ist. Sonst die Raten stornieren oder den Kredit abbezahlt lassen."
          confirmLabel="Löschen" busy={remove.isPending} onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => {
              toast.ok('Kredit gelöscht')
              setConfirmDelete(false)
              onClose()
              onDeleted?.()
              const id = loan!.id
              window.setTimeout(() => refreshAfterDelete(id), 0)
            },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })} />
      )}
    </Dialog>
  )
}
