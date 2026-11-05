import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { ParsedEntry } from '../api/ai'
import { draftFromParsed, type EntryDraft } from './entryParse'
import { listen, speechAvailable } from './speech'
import { fieldErrors } from '../api/messages'
import { MONEY_AREAS, useAccounts, useApiMutation, useCategories, useTransactions, type Account, type Category } from '../api/hooks'
import { categoryPath } from '../lib/categoryTree'
import { fullDate, todayISO } from '../lib/dates'
import { formatEuro } from '../lib/money'
import { negate } from '../lib/moneyInput'
import { Button, ChipGroup, MoneyField, Segmented, SelectField, TextField } from '../ui/controls'
import { EmptyState, Notice } from '../ui/blocks'
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

  // „Beschreiben …“: natürliche Eingabe füllt den Entwurf, gespeichert wird nur über „Speichern“
  const [describe, setDescribe] = useState('')
  const [listening, setListening] = useState(false)
  const [duplicate, setDuplicate] = useState<EntryDraft['duplicate']>(null)
  const [parseNote, setParseNote] = useState<string | null>(null)
  const pendingCategory = useRef<number | null | undefined>(undefined)
  const stopListening = useRef<(() => void) | null>(null)
  const parse = useMutation({ mutationFn: (text: string) => api.post<ParsedEntry>('/entries/parse', { text }) })

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
    if (pendingCategory.current !== undefined) {
      setCategoryId(pendingCategory.current)
      pendingCategory.current = undefined
      return
    }
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

  function runParse() {
    const text = describe.trim()
    if (!text) return
    setParseNote(null)
    parse.mutate(text, {
      onSuccess: (result) => {
        const d = draftFromParsed(result)
        const nextMode = d.mode ?? (mode === 'transfer' ? 'expense' : mode)
        const wanted = d.categoryId !== null && categories.some((c) => c.id === d.categoryId && c.type === (nextMode === 'income' ? 'income' : 'expense'))
          ? d.categoryId : null
        if (nextMode !== mode) {
          pendingCategory.current = wanted
          setMode(nextMode)
        } else if (wanted !== null) setCategoryId(wanted)
        if (d.amount !== null) setAmount(d.amount)
        if (d.date) setDate(d.date)
        if (d.accountId && accounts.some((a) => String(a.id) === d.accountId)) setAccountId(d.accountId)
        if (d.text) setText(d.text)
        const missing: Record<string, string> = {}
        if (d.missing.includes('amount')) missing.amount = 'Fehlt noch – bitte ergänzen'
        if (d.missing.includes('date')) missing.booking_date = 'Fehlt noch – bitte ergänzen'
        if (d.missing.includes('account')) missing.account_id = 'Fehlt noch – bitte wählen'
        setErrors(missing)
        setFormError(null)
        setDuplicate(d.duplicate)
        setParseNote(d.missing.length ? 'Bitte die markierten Angaben ergänzen, dann speichern.' : 'Bitte prüfen und speichern.')
      },
    })
  }

  function toggleListening() {
    if (listening) {
      stopListening.current?.()
      return
    }
    setListening(true)
    stopListening.current = listen(setDescribe, () => { setListening(false); stopListening.current = null })
    if (!stopListening.current) setListening(false)
  }

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
          <div className="entry-describe">
            <TextField
              label="Beschreiben …"
              value={describe}
              onChange={setDescribe}
              placeholder="z. B. gestern 23,50 bei Rewe getankt"
              maxLength={500}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); runParse() } }}
            />
            {speechAvailable() && (
              <Button icon="sparkle" aria-pressed={listening} onClick={toggleListening}>{listening ? 'Stopp' : 'Sprechen'}</Button>
            )}
            <Button icon="sparkle" busy={parse.isPending} disabled={!describe.trim()} onClick={runParse}>Ausfüllen</Button>
          </div>
          {parse.isError && (
            <p className="field-error" role="alert">
              {parse.error instanceof ApiError && parse.error.code === 'ai_unavailable'
                ? 'Keine lokale KI eingerichtet – bitte die Felder von Hand ausfüllen.' : parse.error.message}
            </p>
          )}
          {parseNote && !parse.isError && <p className="muted" role="status">{parseNote}</p>}
          {duplicate && (
            <Notice tone="due" icon="alert">
              Ähnliche Buchung gibt es schon: {duplicate.counterparty || duplicate.description || 'Buchung'} am {fullDate(duplicate.booking_date)}
              {' · '}{formatEuro(duplicate.amount)}{' – '}
              <Link to={`/buchungen?id=${duplicate.id}`} onClick={onClose}>ansehen</Link>
            </Notice>
          )}
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
