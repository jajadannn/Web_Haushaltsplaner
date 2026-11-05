import { useSearchParams, Link } from 'react-router-dom'
import { useBudgetMonth, useCategories, useLoans, useTransactions } from '../../api/hooks'
import { useAddEntry } from '../../app/AddEntry'
import { monthEnd, monthLabel, shiftMonth, todayISO } from '../../lib/dates'
import { formatEuro, isNegative } from '../../lib/money'
import { Button } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, Notice, Tile } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { Available, Breakdown, FixedList, LoanSummary, RecentList, ReserveHints } from './parts'
import { ForecastTile, PaymentHints } from './ForecastTile'
import './start.css'

const MONTH_NAMES = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']

/**
 * Persönliche Startseite (Entwurf A · Kachelraster): Spielraum mit Aufschlüsselung und
 * „Ausgabe hinzufügen“, Hinweis auf ungeklärte Eingänge, darunter Fixkosten, letzte
 * Ausgaben und Kredite.
 */
export function StartPage() {
  const [params, setParams] = useSearchParams()
  const thisMonth = shiftMonth(todayISO(), 0)
  const month = /^\d{4}-\d{2}-01$/.test(params.get('monat') ?? '') ? params.get('monat')! : thisMonth
  const isCurrent = month === thisMonth
  const addEntry = useAddEntry()

  const budget = useBudgetMonth(month)
  const categories = useCategories()
  const loans = useLoans()
  const range = { date_from: month, date_to: monthEnd(month) }
  const recent = useTransactions({ ...range, amount_max: '-0.01', kind: 'regular', limit: 5 })
  const unresolved = useTransactions({ ...range, uncategorized: true, amount_min: '0.01', kind: 'regular', limit: 1 })

  const go = (delta: number) => {
    const next = shiftMonth(month, delta)
    setParams(next === thisMonth ? {} : { monat: next })
  }

  const monthName = MONTH_NAMES[Number(month.slice(5, 7)) - 1]
  const loanItems = budget.data?.items.filter((i) => i.kind === 'loan').length ?? 0
  const activeLoans = (loans.data ?? []).filter((l) => l.status === 'active')
  const unresolvedCount = unresolved.data?.total ?? 0

  return (
    <div className="page start">
      <header className="month-nav">
        <button type="button" className="icon-btn" onClick={() => go(-1)} aria-label="Vormonat">
          <Icon name="chevronLeft" size={26} />
        </button>
        <h1>{monthLabel(month)}</h1>
        <button type="button" className="icon-btn" onClick={() => go(1)} aria-label="Folgemonat" disabled={isCurrent}>
          <Icon name="chevronRight" size={26} />
        </button>
        {!isCurrent && <button type="button" className="link" onClick={() => setParams({})}>Zum aktuellen Monat</button>}
      </header>

      {budget.isError ? (
        <ErrorBox error={budget.error} onRetry={() => budget.refetch()} />
      ) : (
        <section className={`tile hero${budget.data && isNegative(budget.data.available) ? ' is-overdrawn' : ''}`} aria-label="Spielraum">
          {budget.data ? (
            <>
              <Available budget={budget.data} />
              <Breakdown budget={budget.data} />
            </>
          ) : (
            <Loading />
          )}
          <div className="hero-action">
            <Button variant="primary" icon="plus" className="btn-large" onClick={() => addEntry.open()}>
              Ausgabe hinzufügen
            </Button>
          </div>
        </section>
      )}

      {budget.data && budget.data.income === '0.00' && isCurrent && (
        <Notice tone="info" icon="info">
          Für {monthName} ist noch keine Einnahme gebucht – der Spielraum zählt erst, wenn das Gehalt da ist.
        </Notice>
      )}

      {budget.data && budget.data.uncategorized_in !== '0.00' && (
        <Notice
          tone="due"
          action={<Link to="/pruefen" className="link">Prüfen</Link>}
        >
          {unresolvedCount === 1 ? '1 Eingang ungeklärt' : `${unresolvedCount || 'Einige'} Eingänge ungeklärt`}
          {' · '}
          {formatEuro(budget.data.uncategorized_in)}
        </Notice>
      )}

      {isCurrent && <PaymentHints />}
      {isCurrent && <ForecastTile />}

      <div className={`start-grid${activeLoans.length ? '' : ' no-loans'}`}>
        <Tile title={`Fixkosten ${monthName}`}>
          {budget.isLoading && <Loading />}
          {budget.data && (budget.data.items.length ? (
            <FixedList items={budget.data.items} loanCount={loanItems} />
          ) : budget.data.reserves.length > 0 ? null : (
            <EmptyState icon="calendar" title="Keine Fixkosten eingetragen"
              action={<Link className="btn btn-secondary" to="/einstellungen/fixkosten">Fixkosten anlegen</Link>}>
              Miete, Strom, Handy und Abos einmal eintragen – dann rechnet der Spielraum sie automatisch ein.
            </EmptyState>
          ))}
          {budget.data && <ReserveHints reserves={budget.data.reserves} />}
        </Tile>

        <Tile title="Letzte Ausgaben" action={<Link to="/buchungen" className="link">Alle</Link>}>
          {recent.isLoading && <Loading />}
          {recent.isError && <ErrorBox error={recent.error} onRetry={() => recent.refetch()} />}
          {recent.data && (recent.data.items.length ? (
            <RecentList transactions={recent.data.items} categories={categories.data ?? []} />
          ) : (
            <EmptyState icon="list" title={isCurrent ? 'Noch keine Ausgaben in diesem Monat' : 'Keine Ausgaben in diesem Monat'}
              action={isCurrent ? <Button variant="secondary" icon="plus" onClick={() => addEntry.open()}>Erste Ausgabe eintragen</Button> : undefined} />
          ))}
        </Tile>

        {activeLoans.length > 0 && (
          <Tile className="loans-tile" as="div">
            <div className="loan-stack">
              {activeLoans.map((loan) => <LoanSummary key={loan.id} loan={loan} />)}
            </div>
          </Tile>
        )}
      </div>
    </div>
  )
}
