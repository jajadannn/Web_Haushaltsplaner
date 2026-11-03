import { Link } from 'react-router-dom'
import { useProfileQuery, type BudgetMonth, type Category, type Loan, type MonthItem, type ScheduleEntry, type Transaction } from '../../api/hooks'
import { loanProgress } from '../../lib/loanProgress'
import { daysLeftLabel, parseDate, shortDate, shortMonthLabel } from '../../lib/dates'
import { formatEuro, isNegative } from '../../lib/money'
import { Money, StatusBadge } from '../../ui/blocks'
import { Icon, type IconName } from '../../ui/Icon'
import { iconForName } from '../../lib/icons'

/** Spielraum: „Frei verfügbar“ als größte Zahl, darunter pro Tag und verbleibende Tage. */
export function Available({ budget }: { budget: BudgetMonth }) {
  const overdrawn = isNegative(budget.available)
  return (
    <div className={`available${overdrawn ? ' is-overdrawn' : ''}`}>
      <p className="available-label">{overdrawn ? 'Überzogen' : 'Frei verfügbar'}</p>
      <p className="available-amount">{formatEuro(budget.available)}</p>
      <p className="available-sub">
        {budget.available_per_day ? `${formatEuro(budget.available_per_day)} pro Tag` : 'kein Spielraum mehr'}
        {budget.days_left > 0 && ` · ${daysLeftLabel(budget.days_left)}`}
      </p>
    </div>
  )
}

/** Aufschlüsselung: Einnahmen − Fixkosten − Ausgaben bisher = frei verfügbar. */
export function Breakdown({ budget }: { budget: BudgetMonth }) {
  return (
    <dl className="breakdown">
      <div>
        <dt>Einnahmen</dt>
        <dd className="money">{formatEuro(budget.income)}</dd>
      </div>
      <div>
        <dt>Fixkosten</dt>
        <dd className="money">{formatEuro(budget.fixed_total)}</dd>
      </div>
      <div>
        <dt>Ausgaben bisher</dt>
        <dd className="money">{formatEuro(budget.variable_spent)}</dd>
      </div>
    </dl>
  )
}

function itemIcon(item: MonthItem): IconName {
  return item.kind === 'loan' ? 'coins' : iconForName(item.name)
}

/** Fixkosten und Raten des Monats mit Status (bezahlt / fällig / überfällig). */
export function FixedList({ items, loanCount }: { items: MonthItem[]; loanCount: number }) {
  return (
    <ul className="rows">
      {items.map((item) => (
        <li key={`${item.kind}-${item.ref_id}-${item.due_date}`} className="row-card">
          <span className="row-icon"><Icon name={itemIcon(item)} size={26} /></span>
          <span className="row-main">
            <strong>{item.kind === 'loan' ? (loanCount === 1 ? 'Kreditrate' : `Rate ${item.name}`) : item.name}</strong>
            <span>{parseDate(item.due_date).day}.</span>
          </span>
          <span className="row-end">
            <Money value={item.amount} />
            <StatusBadge status={item.status} />
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Letzte eigene Ausgaben (Datum, Empfänger · Kategorie, Betrag). */
export function RecentList({ transactions, categories }: { transactions: Transaction[]; categories: Category[] }) {
  const name = (id: number | null) => categories.find((c) => c.id === id)?.name
  return (
    <ul className="rows">
      {transactions.map((t) => {
        const category = t.splits.length ? 'aufgeteilt' : t.kind === 'transfer' ? 'Umbuchung' : name(t.category_id) ?? 'ohne Kategorie'
        return (
          <li key={t.id}>
            <Link to={`/buchungen?id=${t.id}`} className="row-card recent-row">
              <span className="row-icon">
                <Icon name={t.kind === 'transfer' ? 'transfer' : t.splits.length ? 'split' : iconForName(name(t.category_id), 'tag')} size={26} />
              </span>
              <span className="row-main">
                <span className="recent-date">{shortDate(t.booking_date)}</span>
                <span className="recent-what">
                  <strong>{t.counterparty || t.description}</strong>
                  {' · '}
                  {category}
                </span>
              </span>
              <span className="row-end"><Money value={t.amount} signed /></span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** Kredit mit Restschuld, Abbezahlt-Datum, Restraten und Fortschritt. */
export function LoanSummary({ loan }: { loan: Loan }) {
  const remaining = loan.remaining_debt ?? '0.00'
  const paidOff = loan.status === 'paid_off'
  // Getilgter Anteil: aus der ursprünglichen Summe, sonst aus dem Plan (bezahlte Tilgung)
  const schedule = useProfileQuery<ScheduleEntry[]>('loans', `/loans/${loan.id}/schedule`, undefined, { enabled: !loan.principal_original && !paidOff })
  const progress = loanProgress(loan, schedule.data)
  return (
    <Link to={`/kredite/${loan.id}`} className="loan-summary">
      <p className="loan-summary-name"><Icon name="car" size={26} /> {loan.name}</p>
      {paidOff ? (
        <p className="status is-paid"><Icon name="check" /> Abbezahlt</p>
      ) : (
        <>
          <p className="muted">Restschuld</p>
          <p className="loan-summary-debt">{formatEuro(remaining)}</p>
          <p className="muted">
            {loan.final_due_date && <>Abbezahlt {shortMonthLabel(loan.final_due_date)} · </>}
            noch {loan.open_installments} {loan.open_installments === 1 ? 'Rate' : 'Raten'}
          </p>
          {progress !== null && (
            <div className="progress" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}
              aria-label="Bereits getilgt">
              <span style={{ width: `${progress * 100}%` }} />
            </div>
          )}
          {loan.overdue_installments > 0 && (
            <StatusBadge status="overdue" label={`${loan.overdue_installments} überfällig`} />
          )}
        </>
      )}
    </Link>
  )
}
