import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { fieldErrors } from '../../api/messages'
import { MONEY_AREAS, useApiMutation, type Account, type Category, type Transaction } from '../../api/hooks'
import { formatEuro } from '../../lib/money'
import { negate } from '../../lib/moneyInput'
import { Button, MoneyField, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { splitProblem, splitRemainder, SPLIT_PROBLEM_TEXT, toApiSplits, type SplitDraft } from './splits'

interface Props {
  tx: Transaction
  accounts: Account[]
  categories: Category[]
  onClose: () => void
}

function categoryOptions(categories: Category[], sign: 'in' | 'out') {
  // Erstattungen dürfen gegen den Kategorietyp laufen – deshalb beide Typen, passende zuerst
  const first = sign === 'out' ? 'expense' : 'income'
  const sorted = [...categories].sort((a, b) => (a.type === first ? 0 : 1) - (b.type === first ? 0 : 1))
  return sorted.map((c) => ({
    value: String(c.id),
    label: `${c.parent_id ? `${categories.find((p) => p.id === c.parent_id)?.name ?? ''} › ` : ''}${c.name}${c.type !== first ? (c.type === 'income' ? ' (Einnahme)' : ' (Ausgabe)') : ''}`,
  }))
}

/** Aufgeklappte Bearbeitung einer Buchung (Entwurf B: unter der Zeile in der Tageskachel). */
export function TransactionEditor({ tx, accounts, categories, onClose }: Props) {
  const toast = useToast()
  const imported = tx.source === 'import'
  const loan = tx.source === 'loan'
  const transfer = tx.kind === 'transfer'
  const sign = tx.amount.startsWith('-') ? 'out' : 'in'

  const [amount, setAmount] = useState<string | null>(tx.amount.replace('-', ''))
  const [date, setDate] = useState(tx.booking_date)
  const [accountId, setAccountId] = useState(String(tx.account_id))
  const [categoryId, setCategoryId] = useState(tx.category_id ? String(tx.category_id) : '')
  const [description, setDescription] = useState(tx.description)
  const [counterparty, setCounterparty] = useState(tx.counterparty ?? '')
  const [splitting, setSplitting] = useState(tx.splits.length > 0)
  const [drafts, setDrafts] = useState<SplitDraft[]>(() =>
    tx.splits.length
      ? tx.splits.map((s) => ({ amount: s.amount.replace('-', ''), categoryId: s.category_id, transfer: s.kind === 'transfer' }))
      : [{ amount: tx.amount.replace('-', ''), categoryId: tx.category_id, transfer: false }, { amount: null, categoryId: null, transfer: false }],
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<'delete' | 'exclude' | null>(null)
  const [reason, setReason] = useState('')

  const signed = (value: string) => (sign === 'out' ? negate(value) : value)

  const save = useApiMutation(() => {
    const body: Record<string, unknown> = {}
    if (!imported) {
      if (amount && signed(amount) !== tx.amount) body.amount = signed(amount)
      if (date !== tx.booking_date) body.booking_date = date
      if (Number(accountId) !== tx.account_id) body.account_id = Number(accountId)
    }
    if (description.trim() !== tx.description) body.description = description.trim()
    if ((counterparty.trim() || null) !== (tx.counterparty ?? null)) body.counterparty = counterparty.trim() || null
    if (!transfer) {
      if (splitting) {
        body.splits = toApiSplits(signed(amount ?? tx.amount.replace('-', '')), drafts)
        body.category_id = null
      } else {
        if (tx.splits.length) body.splits = []
        const next = categoryId ? Number(categoryId) : null
        if (next !== tx.category_id || tx.splits.length) body.category_id = next
      }
    }
    return api.patch<Transaction>(`/transactions/${tx.id}`, body)
  }, MONEY_AREAS)

  const remove = useApiMutation(() => api.delete(`/transactions/${tx.id}`), MONEY_AREAS)
  const exclude = useApiMutation(() => api.post(`/transactions/${tx.id}/exclude`, { reason: reason.trim() }), MONEY_AREAS)
  const include = useApiMutation(() => api.post(`/transactions/${tx.id}/include`), MONEY_AREAS)

  const fail = (error: unknown) => {
    if (error instanceof ApiError) {
      setErrors(fieldErrors(error.details))
      setFormError(error.message)
    } else setFormError('Das hat nicht geklappt.')
  }

  function submit() {
    setErrors({})
    setFormError(null)
    if (!imported && !amount) {
      setErrors({ amount: 'Bitte einen Betrag eingeben' })
      return
    }
    if (!description.trim()) {
      setErrors({ description: 'Bitte einen Text eingeben' })
      return
    }
    if (splitting) {
      const problem = splitProblem(amount ?? tx.amount, drafts)
      if (problem) {
        setFormError(SPLIT_PROBLEM_TEXT[problem])
        return
      }
    }
    save.mutate(undefined, {
      onSuccess: () => {
        toast.ok('Buchung gespeichert')
        onClose()
      },
      onError: fail,
    })
  }

  if (loan) {
    return (
      <div className="tx-editor">
        <p className="muted">
          Diese Buchung gehört zu einer Kreditrate. Aufteilung und Betrag werden auf der Kreditseite geändert.
        </p>
        <div className="tx-editor-actions">
          <Button variant="ghost" onClick={onClose}>Schließen</Button>
          <Link className="btn btn-secondary" to="/kredite">Zu den Krediten</Link>
        </div>
      </div>
    )
  }

  const remainder = splitting ? splitRemainder(amount ?? '0.00', drafts) : '0.00'
  const categoryOpts = categoryOptions(categories.filter((c) => c.active || c.id === tx.category_id), sign)

  return (
    <form
      className="tx-editor"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      {tx.excluded_at && (
        <p className="tx-editor-note is-warn">
          <Icon name="eyeOff" size={18} /> Ausgeschlossen{tx.excluded_reason ? `: ${tx.excluded_reason}` : ''} – zählt nicht in Salden und Berichten.
        </p>
      )}
      {imported && <p className="tx-editor-note">Importiert: Konto, Datum und Betrag kommen von der Bank und sind fest.</p>}
      {transfer && <p className="tx-editor-note">Umbuchung zwischen eigenen Konten – zählt weder als Einnahme noch als Ausgabe.</p>}

      <div className="tx-editor-grid">
        <MoneyField label={sign === 'out' ? 'Betrag (Ausgang)' : 'Betrag (Eingang)'} value={amount} onChange={setAmount}
          error={errors.amount} className={imported ? 'is-readonly' : ''} />
        <TextField label="Datum" type="date" value={date} onChange={setDate} disabled={imported} error={errors.booking_date} />
        <SelectField label="Konto" value={accountId} onChange={setAccountId} disabled={imported || transfer}
          options={accounts.filter((a) => a.type !== 'loan' && (!a.archived_at || a.id === tx.account_id)).map((a) => ({ value: String(a.id), label: a.name }))}
          error={errors.account_id} />
        {!transfer && !splitting && (
          <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="ohne Kategorie"
            options={categoryOpts} error={errors.category_id} />
        )}
        <TextField label="Empfänger / Auftraggeber" value={counterparty} onChange={setCounterparty} maxLength={200}
          error={errors.counterparty} />
        <TextField label="Text" value={description} onChange={setDescription} maxLength={1000} error={errors.description} />
      </div>

      {splitting && !transfer && (
        <fieldset className="split-editor">
          <legend>Aufteilung von {amount ? formatEuro(amount) : '–'}</legend>
          {drafts.map((d, i) => (
            <div key={i} className="split-row">
              <MoneyField label={`Teil ${i + 1}`} value={d.amount}
                onChange={(v) => setDrafts((list) => list.map((x, j) => (j === i ? { ...x, amount: v } : x)))} />
              <SelectField label="Kategorie" value={d.transfer ? 'transfer' : d.categoryId ? String(d.categoryId) : ''}
                placeholder="Kategorie wählen"
                options={[...categoryOpts, { value: 'transfer', label: 'Umbuchung (z. B. Tilgung)' }]}
                onChange={(v) => setDrafts((list) => list.map((x, j) => (j === i
                  ? { ...x, transfer: v === 'transfer', categoryId: v && v !== 'transfer' ? Number(v) : null }
                  : x)))} />
              <button type="button" className="icon-btn" aria-label={`Teil ${i + 1} entfernen`} disabled={drafts.length <= 2}
                onClick={() => setDrafts((list) => list.filter((_, j) => j !== i))}>
                <Icon name="trash" size={20} />
              </button>
            </div>
          ))}
          <div className="split-footer">
            <Button variant="ghost" icon="plus" onClick={() => setDrafts((list) => [...list, {
              amount: remainder.startsWith('-') || remainder === '0.00' ? null : remainder, categoryId: null, transfer: false,
            }])}>
              Zeile hinzufügen
            </Button>
            <span className={`split-rest${remainder === '0.00' ? ' is-ok' : ''}`}>
              {remainder === '0.00' ? 'Vollständig verteilt' : remainder.startsWith('-')
                ? `${formatEuro(remainder.slice(1))} zu viel`
                : `Noch ${formatEuro(remainder)} zu verteilen`}
            </span>
          </div>
        </fieldset>
      )}

      {formError && <p className="field-error" role="alert">{formError}</p>}

      <div className="tx-editor-actions">
        {!transfer && (
          <Button variant="secondary" icon="split" onClick={() => setSplitting((s) => !s)}>
            {splitting ? 'Nicht aufteilen' : 'Aufteilen'}
          </Button>
        )}
        {tx.excluded_at ? (
          <Button variant="secondary" icon="refresh" busy={include.isPending}
            onClick={() => include.mutate(undefined, { onSuccess: () => { toast.ok('Buchung zählt wieder'); onClose() }, onError: fail })}>
            Wieder einschließen
          </Button>
        ) : imported ? (
          <Button variant="secondary" icon="eyeOff" onClick={() => setConfirm('exclude')}>Ausschließen</Button>
        ) : (
          <Button variant="danger" icon="trash" onClick={() => setConfirm('delete')}>Löschen</Button>
        )}
        <span className="spacer" />
        <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
        <Button variant="primary" type="submit" busy={save.isPending}>Speichern</Button>
      </div>

      <Confirm
        open={confirm === 'delete'}
        title="Buchung löschen?"
        text={transfer
          ? 'Das löscht beide Seiten der Umbuchung. Das lässt sich nicht rückgängig machen.'
          : `„${tx.counterparty || tx.description}“ über ${formatEuro(tx.amount)} wird endgültig gelöscht.`}
        confirmLabel="Löschen"
        busy={remove.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => remove.mutate(undefined, {
          onSuccess: () => { toast.ok('Buchung gelöscht'); setConfirm(null); onClose() },
          onError: (e) => { setConfirm(null); fail(e) },
        })}
      />
      <Confirm
        open={confirm === 'exclude'}
        title="Buchung ausschließen?"
        danger={false}
        text={
          <>
            Ausgeschlossene Buchungen bleiben gespeichert, zählen aber nicht mehr – so holt ein erneuter Import sie nicht zurück.
            <span className="confirm-field">
              <TextField label="Grund" value={reason} onChange={setReason} placeholder="z. B. doppelt von der Bank geliefert" maxLength={500} />
            </span>
          </>
        }
        confirmLabel="Ausschließen"
        busy={exclude.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (!reason.trim()) return
          exclude.mutate(undefined, {
            onSuccess: () => { toast.ok('Buchung ausgeschlossen'); setConfirm(null); onClose() },
            onError: (e) => { setConfirm(null); fail(e) },
          })
        }}
      />
    </form>
  )
}

