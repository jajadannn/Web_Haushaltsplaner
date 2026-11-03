import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { download } from '../../api/client'
import { useAccounts, useCategories, useTransactions, type Category, type Transaction } from '../../api/hooks'
import { useAddEntry } from '../../app/AddEntry'
import { monthLabel, parseDate, shiftMonth, shortDate, todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { Button, Toggle } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, Money } from '../../ui/blocks'
import { Icon, type IconName } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { iconForName } from '../../lib/icons'
import { filterToParams, filterToQuery, parseFilter, type TxFilter } from './filters'
import { TransactionEditor } from './TransactionEditor'
import './buchungen.css'

const PAGE = 100

function rowIcon(tx: Transaction, category: Category | undefined, parent: Category | undefined): IconName {
  if (tx.kind === 'transfer') return 'transfer'
  if (tx.splits.length) return 'split'
  if (!category) return tx.amount.startsWith('-') ? 'tag' : 'person'
  return iconForName(category.name, iconForName(parent?.name))
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Buchungen (Entwurf B · Kacheln pro Tag). */
export function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const thisMonth = shiftMonth(todayISO(), 0)
  const filter = parseFilter(params, thisMonth)
  const selectedId = Number(params.get('id')) || null
  const [searchText, setSearchText] = useState(filter.search)
  const search = useDebounced(searchText, 300)
  const [pages, setPages] = useState(1)
  const addEntry = useAddEntry()
  const toast = useToast()

  const update = (patch: Partial<TxFilter>, keepId = false) => {
    const next = filterToParams({ ...filter, ...patch }, thisMonth)
    if (keepId && selectedId) next.id = String(selectedId)
    setParams(next)
    setPages(1)
  }

  // Suche erst nach kurzer Tipp-Pause in die URL übernehmen
  useEffect(() => {
    if (search !== filter.search) update({ search })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const query = filterToQuery(filter)
  const list = useTransactions({ ...query, limit: PAGE * pages, offset: 0 })
  const accounts = useAccounts({ include_archived: true })
  const categories = useCategories()
  const categoryById = useMemo(() => new Map((categories.data ?? []).map((c) => [c.id, c])), [categories.data])
  const accountName = (id: number) => accounts.data?.find((a) => a.id === id)?.name ?? ''

  const items = useMemo(() => list.data?.items ?? [], [list.data])
  const total = list.data?.total ?? 0

  // Summen über die geladenen Buchungen; Umbuchungen und Ausgeschlossene zählen nicht
  const sums = useMemo(() => {
    let income = 0n
    let expenses = 0n
    for (const t of items) {
      if (t.excluded_at) continue
      const lines = t.splits.length ? t.splits : [{ amount: t.amount, kind: t.kind }]
      for (const line of lines) {
        if (line.kind === 'transfer') continue
        const c = toCents(line.amount)
        if (c > 0n) income += c
        else expenses -= c
      }
    }
    return { income: fromCents(income), expenses: fromCents(expenses) }
  }, [items])

  const days = useMemo(() => {
    // Umbuchungspaar nur einmal zeigen (die abgehende Seite), wenn beide Seiten geladen sind
    const ids = new Set(items.map((t) => t.id))
    const shown = items.filter((t) => !(t.kind === 'transfer' && !t.amount.startsWith('-') && t.transfer_peer_id && ids.has(t.transfer_peer_id)))
    const map = new Map<string, Transaction[]>()
    for (const t of shown) map.set(t.booking_date, [...(map.get(t.booking_date) ?? []), t])
    return [...map.entries()]
  }, [items])

  const select = (id: number | null) => {
    const next = filterToParams(filter, thisMonth)
    if (id) next.id = String(id)
    setParams(next, { replace: true })
  }

  const monthOptions = Array.from({ length: 25 }, (_, i) => shiftMonth(thisMonth, -i))
  const allCategories = categories.data ?? []

  return (
    <div className="page tx-page">
      <header className="page-header">
        <div className="page-title"><h1>Buchungen</h1></div>
        <div className="page-actions">
          <Button variant="primary" icon="plus" onClick={() => addEntry.open()}>Ausgabe hinzufügen</Button>
        </div>
      </header>

      <div className="tx-filters" role="search">
        <label className="filter-select">
          <Icon name="calendar" size={20} />
          <span className="visually-hidden">Zeitraum</span>
          <select value={filter.month} onChange={(e) => update({ month: e.target.value })}>
            {monthOptions.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
            <option value="alle">Alle Monate</option>
          </select>
          <Icon name="chevronDown" size={18} />
        </label>
        <label className="filter-select">
          <Icon name="wallet" size={20} />
          <span className="visually-hidden">Konto</span>
          <select value={filter.account ?? ''} onChange={(e) => update({ account: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Alle Konten</option>
            {(accounts.data ?? []).filter((a) => a.type !== 'loan').map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.archived_at ? ' (archiviert)' : ''}</option>
            ))}
          </select>
          <Icon name="chevronDown" size={18} />
        </label>
        <label className="filter-select">
          <Icon name="list" size={20} />
          <span className="visually-hidden">Kategorie</span>
          <select value={filter.category ?? ''}
            onChange={(e) => update({ category: e.target.value === 'ohne' ? 'ohne' : e.target.value ? Number(e.target.value) : null })}>
            <option value="">Alle Kategorien</option>
            <option value="ohne">Ohne Kategorie</option>
            {allCategories.filter((c) => !c.parent_id).map((parent) => (
              <optgroup key={parent.id} label={parent.name}>
                <option value={parent.id}>{parent.name} (alle)</option>
                {allCategories.filter((c) => c.parent_id === parent.id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </optgroup>
            ))}
          </select>
          <Icon name="chevronDown" size={18} />
        </label>
        <label className="filter-search">
          <Icon name="search" size={20} />
          <span className="visually-hidden">Suchen</span>
          <input type="search" placeholder="Suchen …" value={searchText} onChange={(e) => setSearchText(e.target.value)} maxLength={200} />
        </label>
        <div className="filter-toggles">
          <Toggle label="Nur ungeprüfte" checked={filter.onlyReview} onChange={(v) => update({ onlyReview: v })} />
          <Toggle label="Ausgeschlossene" checked={filter.withExcluded} onChange={(v) => update({ withExcluded: v })} />
        </div>
      </div>

      <div className="tx-summary">
        <div className="tile tx-sum">
          <Icon name="import" size={26} />
          <span><small>Einnahmen</small><strong className="money">{formatEuro(sums.income)}</strong></span>
        </div>
        <div className="tile tx-sum">
          <Icon name="upload" size={26} />
          <span><small>Ausgaben</small><strong className="money">{formatEuro(sums.expenses)}</strong></span>
        </div>
        <div className="tile tx-sum">
          <Icon name="list" size={26} />
          <span><strong className="num">{total}</strong><small>{total === 1 ? 'Buchung' : 'Buchungen'}</small></span>
        </div>
      </div>
      {total > items.length && items.length > 0 && (
        <p className="muted tx-partial">Summen über die {items.length} geladenen von {total} Buchungen.</p>
      )}

      {list.isLoading && <Loading />}
      {list.isError && <ErrorBox error={list.error} onRetry={() => list.refetch()} />}
      {list.isSuccess && items.length === 0 && (
        <div className="tile">
          <EmptyState icon="list" title="Keine Buchungen gefunden">
            {filter.search || filter.account || filter.category || filter.onlyReview
              ? 'Mit diesen Filtern gibt es nichts. Filter lockern oder einen anderen Monat wählen.'
              : 'In diesem Zeitraum ist noch nichts gebucht. Trage eine Ausgabe ein oder importiere einen Kontoauszug.'}
          </EmptyState>
        </div>
      )}

      <div className="tx-days">
        {days.map(([day, txs]) => (
          <section key={day} className="tile tx-day" aria-label={shortDate(day)}>
            <h2 className="tx-day-date">{shortDate(day)}{parseDate(day).year !== parseDate(thisMonth).year ? parseDate(day).year : ''}</h2>
            <ul className="tx-rows">
              {txs.map((tx) => {
                const category = tx.category_id ? categoryById.get(tx.category_id) : undefined
                const open = tx.id === selectedId
                const needsReview = tx.review_status === 'needs_review' && !tx.excluded_at
                const transfer = tx.kind === 'transfer'
                const route = transfer && tx.counterparty
                  ? (tx.amount.startsWith('-') ? `${accountName(tx.account_id)} → ${tx.counterparty}` : `${tx.counterparty} → ${accountName(tx.account_id)}`)
                  : accountName(tx.account_id)
                const title = transfer ? 'Umbuchung' : tx.counterparty || tx.description
                const sub = transfer
                  ? tx.description
                  : tx.splits.length
                    ? `aufgeteilt in ${tx.splits.length} Teile`
                    : category?.name ?? (tx.amount.startsWith('-') ? 'ohne Kategorie' : 'ungeklärt')
                return (
                  <li key={tx.id} className={`tx-row${open ? ' is-open' : ''}${tx.excluded_at ? ' is-excluded' : ''}`}>
                    <button type="button" className="tx-line" aria-expanded={open} onClick={() => select(open ? null : tx.id)}>
                      <span className="tx-icon"><Icon name={rowIcon(tx, category, category?.parent_id ? categoryById.get(category.parent_id) : undefined)} size={26} /></span>
                      <span className="tx-what">
                        <strong>{title}</strong>
                        <span>{sub}{!transfer && tx.counterparty && tx.description !== sub && tx.description !== tx.counterparty ? ` · ${tx.description}` : ''}</span>
                      </span>
                      <span className="tx-account">{route}</span>
                      <span className="tx-amount"><Money value={tx.amount} signed /></span>
                      <span className="tx-state">
                        {tx.excluded_at ? (
                          <span className="status is-muted" title="ausgeschlossen"><Icon name="eyeOff" size={22} /></span>
                        ) : needsReview ? (
                          <span className="review-badge">prüfen</span>
                        ) : tx.kind === 'transfer' ? (
                          <span className="status is-muted" title="Umbuchung"><Icon name="transfer" size={22} /></span>
                        ) : (
                          <span className="status is-paid" title="geprüft"><Icon name="check" size={22} /></span>
                        )}
                      </span>
                    </button>
                    {tx.splits.length > 0 && (
                      <ul className="tx-splits">
                        {tx.splits.map((s) => (
                          <li key={s.id}>
                            <span>{s.kind === 'transfer' ? 'Umbuchung / Tilgung' : categoryById.get(s.category_id ?? 0)?.name ?? 'ohne Kategorie'}</span>
                            <Money value={s.amount} />
                          </li>
                        ))}
                      </ul>
                    )}
                    {open && (
                      <TransactionEditor
                        key={tx.id}
                        tx={tx}
                        accounts={accounts.data ?? []}
                        categories={allCategories}
                        onClose={() => select(null)}
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>

      <div className="tx-footer">
        {total > items.length && (
          <Button variant="secondary" busy={list.isFetching} onClick={() => setPages((p) => p + 1)}>
            Weitere {Math.min(PAGE, total - items.length)} laden
          </Button>
        )}
        <span className="spacer" />
        <button
          type="button"
          className="link tx-export"
          onClick={() => download('/export/transactions.csv', 'buchungen.csv', query).catch(toast.error)}
        >
          <Icon name="download" size={20} /> CSV exportieren
        </button>
      </div>
    </div>
  )
}

