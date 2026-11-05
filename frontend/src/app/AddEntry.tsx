import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { fieldErrors } from '../api/messages'
import { MONEY_AREAS, useAccounts, useApiMutation, useCategories, useTransactions, type Account, type Category } from '../api/hooks'
import { categoryPath } from '../lib/categoryTree'
import { todayISO } from '../lib/dates'
import { formatEuro } from '../lib/money'
import { negate } from '../lib/moneyInput'
import { Button, ChipGroup, MoneyField, Segmented, SelectField, TextField } from '../ui/controls'
import { EmptyState } from '../ui/blocks'
import { Dialog, useToast } from '../ui/overlay'

/**
 * „Ausgabe hinzufügen“ – von überall mit einem Tipp erreichbar (Knopf, Plus, Taste N).
 * Betrag, Kategorie, Konto in wenigen Schritten; Kategorie und Konto merken sich die
 * letzte Wahl. Daneben Einnahme und Umbuchung zwischen eigenen Konten.
 */

type Mode = 'expense' | 'income' | 'transfer'

const LAST_KEY = 'finanzplaner.lastEntry'
const CHIP_COUNT = 6

interface LastChoice {
  account?: number
  expense?: number
  income?: number
  recent?: number[] // zuletzt genutzte Ausgaben-Kategorien, neueste zuerst
}

function readLast(): LastChoice {
  try {
    return JSON.parse(window.localStorage.getItem(LAST_KEY) ?? '{}') ?? {}
  } catch {
    return {}
  }
}

function writeLast(value: LastChoice) {
  try {
    window.localStorage.setItem(LAST_KEY, JSON.stringify(value))
  } catch {
    // ohne Speicher keine Vorbelegung
  }
}

interface AddEntryState {
  open: (mode?: Mode) => void
}

const AddEntryContext = createContext<AddEntryState | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useAddEntry(): AddEntryState {
  const value = useContext(AddEntryContext)
  if (!value) throw new Error('useAddEntry außerhalb von AddEntryProvider')
  return value
}

export function AddEntryProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode | null>(null)
  const open = useCallback((next: Mode = 'expense') => setMode(next), [])

  // Taste N öffnet die Erfassung (nicht beim Tippen in Feldern)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (e.key.toLowerCase() !== 'n' || e.metaKey || e.ctrlKey || e.altKey) return
      if (target.closest('input, textarea, select, [contenteditable], dialog')) return
      e.preventDefault()
      setMode('expense')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const value = useMemo(() => ({ open }), [open])
  return (
    <AddEntryContext.Provider value={value}>
      {children}
      {mode && <AddEntryDialog initialMode={mode} onClose={() => setMode(null)} />}
    </AddEntryContext.Provider>
  )
}

/** Konten, auf die man direkt bucht – Kreditkonten laufen über die Kreditseite. */
function bookable(accounts: Account[] | undefined): Account[] {
  return (accounts ?? []).filter((a) => !a.archived_at && a.type !== 'loan')
}

function categoryLabel(category: Category, all: Category[]): string {
  return categoryPath(all, category.id) || category.name
}

function AddEntryDialog({ initialMode, onClose }: { initialMode: Mode; onClose: () => void }) {
  const toast = useToast()
  const last = useMemo(readLast, [])
  const accountsQuery = useAccounts()
  const categoriesQuery = useCategories({ active: true })
  const accounts = bookable(accountsQuery.data)
  const categories = categoriesQuery.data ?? []
  // Häufigste Kategorien der letzten Buchungen – bestimmen die Chips, solange es keinen Verlauf gibt
  const history = useTransactions({ kind: 'regular', limit: 100 })

  const [mode, setMode] = useState<Mode>(initialMode)
  const [amount, setAmount] = useState<string | null>(null)
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [accountId, setAccountId] = useState<string>('')
  const [toAccountId, setToAccountId] = useState<string>('')
  const [date, setDate] = useState(todayISO())
  const [text, setText] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)

  const typed = categories.filter((c) => c.type === (mode === 'income' ? 'income' : 'expense') && !c.system_key)

  // Vorbelegung, sobald Konten und Kategorien geladen sind
  useEffect(() => {
    if (!accountId && accounts.length) {
      const remembered = accounts.find((a) => a.id === last.account)
      setAccountId(String((remembered ?? accounts.find((a) => a.type === 'checking') ?? accounts[0]).id))
    }
  }, [accounts, accountId, last.account])

  useEffect(() => {
    if (mode === 'transfer') return
    const remembered = mode === 'income' ? last.income : last.expense
    setCategoryId(typed.some((c) => c.id === remembered) ? remembered! : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, categoriesQuery.data])

  // Chips: zuletzt hier gewählte zuerst, dann nach Häufigkeit in den letzten Buchungen
  const chips = useMemo(() => {
    const recent = mode === 'expense' ? (last.recent ?? []) : []
    const counts = new Map<number, number>()
    for (const t of history.data?.items ?? []) {
      const ids = t.splits.length ? t.splits.map((s) => s.category_id) : [t.category_id]
      for (const id of ids) if (id) counts.set(id, (counts.get(id) ?? 0) + 1)
    }
    const byUse = [...typed].sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0))
    const ordered = [
      ...recent.map((id) => typed.find((c) => c.id === id)).filter((c): c is Category => !!c),
      ...byUse.filter((c) => !recent.includes(c.id)),
    ]
    const shown = ordered.slice(0, CHIP_COUNT)
    if (categoryId && !shown.some((c) => c.id === categoryId)) {
      const selected = typed.find((c) => c.id === categoryId)
      if (selected) shown[shown.length - 1] = selected
    }
    return shown
  }, [typed, mode, last.recent, categoryId, history.data])

  const save = useApiMutation(async () => {
    if (!amount) throw new ApiError(422, 'validation_error', 'Bitte einen Betrag eingeben.', [{ loc: ['body', 'amount'] }])
    if (mode === 'transfer') {
      return api.post('/transfers', {
        from_account_id: Number(accountId),
        to_account_id: Number(toAccountId),
        booking_date: date,
        amount,
        description: text.trim() || 'Umbuchung',
      })
    }
    const category = typed.find((c) => c.id === categoryId)
    return api.post('/transactions', {
      account_id: Number(accountId),
      booking_date: date,
      amount: mode === 'expense' ? negate(amount) : amount,
      description: text.trim() || category?.name || (mode === 'expense' ? 'Ausgabe' : 'Einnahme'),
      category_id: categoryId,
    })
  }, MONEY_AREAS)

  function submit() {
    setErrors({})
    setFormError(null)
    const local: Record<string, string> = {}
    if (!amount) local.amount = 'Bitte einen Betrag eingeben'
    if (!accountId) local.account_id = 'Bitte ein Konto wählen'
    if (mode === 'transfer' && !toAccountId) local.to_account_id = 'Bitte das Zielkonto wählen'
    if (mode === 'transfer' && toAccountId === accountId) local.to_account_id = 'Bitte ein anderes Konto wählen'
    if (mode !== 'transfer' && !categoryId) local.category_id = 'Bitte eine Kategorie wählen'
    if (Object.keys(local).length) {
      setErrors(local)
      return
    }
    save.mutate(undefined, {
      onSuccess: () => {
        const next: LastChoice = { ...last, account: Number(accountId) }
        if (mode === 'expense' && categoryId) {
          next.expense = categoryId
          next.recent = [categoryId, ...(last.recent ?? []).filter((id) => id !== categoryId)].slice(0, 12)
        }
        if (mode === 'income' && categoryId) next.income = categoryId
        writeLast(next)
        const what = mode === 'expense' ? 'Ausgabe' : mode === 'income' ? 'Einnahme' : 'Umbuchung'
        toast.ok(`${what} über ${formatEuro(amount!)} gespeichert`)
        onClose()
      },
      onError: (error) => {
        if (error instanceof ApiError) {
          setErrors(fieldErrors(error.details))
          setFormError(error.message)
        } else setFormError('Das hat nicht geklappt.')
      },
    })
  }

  const title = mode === 'expense' ? 'Ausgabe hinzufügen' : mode === 'income' ? 'Einnahme hinzufügen' : 'Umbuchung'
  const loading = accountsQuery.isLoading || categoriesQuery.isLoading
  const noAccounts = !loading && accounts.length === 0

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      footer={noAccounts ? undefined : (
        <>
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button variant="primary" icon="check" busy={save.isPending} onClick={submit}>Speichern</Button>
        </>
      )}
    >
      {noAccounts ? (
        <EmptyState icon="wallet" title="Noch kein Konto angelegt"
          action={<Link className="btn btn-primary" to="/einstellungen/konten" onClick={onClose}>Konto anlegen</Link>}>
          Lege zuerst ein Konto an, zum Beispiel dein Girokonto mit dem heutigen Kontostand.
        </EmptyState>
      ) : (
        <form
          className="entry-form"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <Segmented<Mode>
            label="Art"
            value={mode}
            onChange={(m) => {
              setMode(m)
              setErrors({})
            }}
            options={[
              { value: 'expense', label: 'Ausgabe' },
              { value: 'income', label: 'Einnahme' },
              { value: 'transfer', label: 'Umbuchung' },
            ]}
          />
          <MoneyField label="Betrag" value={amount} onChange={setAmount} error={errors.amount} large autoFocus />

          {mode !== 'transfer' && (
            <>
              {chips.length > 0 && (
                <ChipGroup<number>
                  label="Kategorie"
                  value={categoryId}
                  onChange={setCategoryId}
                  options={chips.map((c) => ({ value: c.id, label: c.name }))}
                />
              )}
              <SelectField
                label={chips.length ? 'Andere Kategorie' : 'Kategorie'}
                value={categoryId ? String(categoryId) : ''}
                onChange={(v) => setCategoryId(v ? Number(v) : null)}
                placeholder="Kategorie wählen"
                options={typed.map((c) => ({ value: String(c.id), label: categoryLabel(c, categories) }))}
                error={errors.category_id}
              />
            </>
          )}

          <div className="form-grid">
            <SelectField
              label={mode === 'transfer' ? 'Von Konto' : 'Konto'}
              value={accountId}
              onChange={setAccountId}
              options={accounts.map((a) => ({ value: String(a.id), label: a.name }))}
              error={errors.account_id}
            />
            {mode === 'transfer' ? (
              <SelectField
                label="Auf Konto"
                value={toAccountId}
                onChange={setToAccountId}
                placeholder="Zielkonto wählen"
                options={accounts.filter((a) => String(a.id) !== accountId).map((a) => ({ value: String(a.id), label: a.name }))}
                error={errors.to_account_id}
              />
            ) : (
              <TextField label="Datum" type="date" value={date} onChange={setDate} error={errors.booking_date} max={todayISO()} />
            )}
            {mode === 'transfer' && (
              <TextField label="Datum" type="date" value={date} onChange={setDate} error={errors.booking_date} max={todayISO()} />
            )}
            <TextField
              className={mode === 'transfer' ? '' : 'span-2'}
              label="Wofür (optional)"
              value={text}
              onChange={setText}
              placeholder={mode === 'expense' ? 'z. B. Rewe' : mode === 'income' ? 'z. B. Gehalt' : 'Umbuchung'}
              maxLength={1000}
              error={errors.description}
            />
          </div>
          {formError && <p className="field-error" role="alert">{formError}</p>}
          <button type="submit" hidden />
        </form>
      )}
    </Dialog>
  )
}
