import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { download, type Schemas } from '../../api/client'
import { useInstitutions, useProfileQuery, useTransactions } from '../../api/hooks'
import { fullDate, monthEnd, monthLabel, parseDate, shiftMonth, shortMonthLabel, todayISO } from '../../lib/dates'
import { formatEuro, isNegative } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { descendantIds, flattenCategoryTree } from '../../lib/categoryTree'
import { topRecipients } from './recipients'
import { currentStateNote, interestBreakdown } from './loanReport'
import { Button, Segmented } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { AskCard, MonthCompareCard } from './AiCards'
import { PairedBars, ShareBar } from './charts'
import './berichte.css'

/** Berichte (Entwurf C · Reiter mit Kategorie-Detail). Zeitraum steht in der URL (?von=…&bis=…). */

type Summary = Schemas['SummaryReport']
type CategoryReport = Schemas['CategoryReport']
type CategoryItem = Schemas['CategoryItem']
type Trends = Schemas['TrendReport']
type LoanReport = Schemas['LoanReport']
type Tab = 'ueberblick' | 'kategorien' | 'verlauf' | 'konten' | 'kredite'

const MONTH = /^\d{4}-\d{2}-01$/
const MONTHS_SHORT = ['Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.']

function periodLabel(from: string, to: string): string {
  return from === to ? monthLabel(from) : `${monthLabel(from)} – ${monthLabel(to)}`
}

function percent(share: string | number | null | undefined): string {
  if (share === null || share === undefined) return ''
  return `${Math.round(Number(share) * 100)} %`
}

export function ReportsPage() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const thisMonth = shiftMonth(todayISO(), 0)
  const from = MONTH.test(params.get('von') ?? '') ? params.get('von')! : shiftMonth(thisMonth, -1)
  const toRaw = MONTH.test(params.get('bis') ?? '') ? params.get('bis')! : thisMonth
  const to = toRaw < from ? from : toRaw
  const tab = (params.get('ansicht') as Tab) || 'ueberblick'
  const range = { date_from: from, date_to: monthEnd(to) }

  const set = (patch: Record<string, string>) => setParams({ von: from, bis: to, ansicht: tab, ...patch })
  const year = parseDate(thisMonth).year
  const presets = [
    { label: 'Dieser Monat', von: thisMonth, bis: thisMonth },
    { label: 'Letzte 3 Monate', von: shiftMonth(thisMonth, -2), bis: thisMonth },
    { label: 'Dieses Jahr', von: `${year}-01-01`, bis: thisMonth },
    { label: 'Letztes Jahr', von: `${year - 1}-01-01`, bis: `${year - 1}-12-01` },
  ]
  const monthOptions = Array.from({ length: 36 }, (_, i) => shiftMonth(thisMonth, -i))

  const summary = useProfileQuery<Summary>('reports', '/reports/summary', range)

  return (
    <div className="page reports-page">
      <header className="page-header reports-head">
        <div className="page-title"><h1>Berichte</h1></div>
        <div className="reports-period">
          <div className="period-row">
            <label className="filter-select period-select">
              <Icon name="calendar" size={20} />
              <span className="visually-hidden">Von</span>
              <select value={from} onChange={(e) => set({ von: e.target.value, bis: e.target.value > to ? e.target.value : to })}>
                {monthOptions.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
              </select>
            </label>
            <span aria-hidden="true">–</span>
            <label className="filter-select period-select">
              <span className="visually-hidden">Bis</span>
              <select value={to} onChange={(e) => set({ bis: e.target.value, von: e.target.value < from ? e.target.value : from })}>
                {monthOptions.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
              </select>
            </label>
            <Button variant="primary" icon="download"
              onClick={() => download('/export/report.pdf', 'bericht.pdf', range).catch(toast.error)}>
              PDF exportieren
            </Button>
          </div>
          <div className="period-presets">
            {presets.map((p) => (
              <button key={p.label} type="button" className={`chip small${p.von === from && p.bis === to ? ' is-active' : ''}`}
                onClick={() => set({ von: p.von, bis: p.bis })}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <AskCard />
      <MonthCompareCard key={to} month={to} />

      {summary.isError && <ErrorBox error={summary.error} onRetry={() => summary.refetch()} />}
      <div className="kpis">
        {summary.data ? (
          <>
            <Kpi label="Nettovermögen" value={summary.data.net_worth} note={`am ${monthEnd(to).split('-').reverse().join('.')}`} />
            <Kpi label="Vermögen" value={summary.data.assets} />
            <Kpi label="Schulden" value={fromCents(-toCents(summary.data.liabilities))} />
            <Kpi label="Einnahmen" value={summary.data.movements.income} />
            <Kpi label="Ausgaben" value={summary.data.movements.expenses} />
          </>
        ) : !summary.isError && <Loading />}
      </div>
      {summary.data && summary.data.accounts.some((a) => a.history_incomplete) && (
        <p className="muted reports-note">
          <Icon name="info" size={18} /> Für einige Konten beginnt die Aufzeichnung erst im Zeitraum – Bewegungen davor fehlen.
        </p>
      )}

      <nav className="report-tabs" role="tablist" aria-label="Bereiche">
        {([
          ['ueberblick', 'Überblick'], ['kategorien', 'Kategorien'], ['verlauf', 'Verlauf'], ['konten', 'Konten'], ['kredite', 'Kredite'],
        ] as [Tab, string][]).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'is-active' : ''}
            onClick={() => set({ ansicht: id })}>
            {label}
          </button>
        ))}
      </nav>

      {tab === 'ueberblick' && (
        <>
          <CategoriesPanel range={range} compact />
          <div className="reports-split">
            <TrendPanel to={to} months={6} />
            <AccountsPanel summary={summary.data} compact />
          </div>
        </>
      )}
      {tab === 'kategorien' && <CategoriesPanel range={range} />}
      {tab === 'verlauf' && <TrendPanel to={to} months={12} withTable />}
      {tab === 'konten' && <AccountsPanel summary={summary.data} />}
      {tab === 'kredite' && <LoansPanel to={to} />}
      <p className="muted reports-period-note">Zeitraum: {periodLabel(from, to)}</p>
    </div>
  )
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile kpi">
      <p className="kpi-label">{label}</p>
      <p className={`kpi-value${isNegative(value) ? ' is-negative' : ''}`}>{formatEuro(value)}</p>
      {note && <p className="kpi-note">{note}</p>}
    </div>
  )
}

// --- Kategorien -------------------------------------------------------------------

function CategoriesPanel({ range, compact }: { range: { date_from: string; date_to: string }; compact?: boolean }) {
  const [type, setType] = useState<'expense' | 'income'>('expense')
  const report = useProfileQuery<CategoryReport>('reports', '/reports/categories', { ...range, type })
  const items = report.data?.items ?? []
  const roots = items.filter((i) => i.parent_id === null && toCents(i.net) !== 0n)
    .sort((a, b) => Number(toCents(b.net) - toCents(a.net)))
  const [selected, setSelected] = useState<number | null>(null)
  const current = roots.find((r) => r.category_id === selected) ?? roots[0]
  const max = roots[0]?.net ?? '0.00'
  const shown = compact ? roots.slice(0, 6) : roots

  return (
    <section className="tile report-panel categories-panel">
      <div className="categories-list">
        <header className="panel-head">
          <h2>{type === 'expense' ? 'Ausgaben' : 'Einnahmen'} nach Kategorie</h2>
          <Segmented label="Art" value={type} onChange={(t) => { setType(t); setSelected(null) }} options={[
            { value: 'expense', label: 'Ausgaben' }, { value: 'income', label: 'Einnahmen' },
          ]} />
        </header>
        {report.isLoading && <Loading />}
        {report.isError && <ErrorBox error={report.error} onRetry={() => report.refetch()} />}
        {report.isSuccess && roots.length === 0 && (
          <EmptyState icon="chart" title={`Keine ${type === 'expense' ? 'Ausgaben' : 'Einnahmen'} im Zeitraum`} />
        )}
        <ul className="category-bars">
          {shown.map((item) => (
            <li key={item.category_id}>
              <button type="button" className={`category-bar${current?.category_id === item.category_id ? ' is-selected' : ''}`}
                aria-pressed={current?.category_id === item.category_id} onClick={() => setSelected(item.category_id)}>
                <span className="category-name">{item.name}</span>
                <span className="category-value money">{formatEuro(item.net)}</span>
                <span className="category-share">{percent(item.share)}</span>
                <ShareBar value={item.net} max={max} />
              </button>
            </li>
          ))}
          {report.data && toCents(report.data.uncategorized) !== 0n && (
            <li>
              <div className="category-bar is-static">
                <span className="category-name">ohne Kategorie</span>
                <span className="category-value money">{formatEuro(report.data.uncategorized)}</span>
                <span className="category-share" />
                <ShareBar value={report.data.uncategorized} max={max} />
              </div>
            </li>
          )}
        </ul>
        {compact && roots.length > shown.length && <p className="muted">+ {roots.length - shown.length} weitere unter „Kategorien“</p>}
        {report.data && (
          <p className="muted category-total">
            Summe {formatEuro(report.data.total_net)}{report.data.share_basis !== report.data.total_net && ` · Anteile bezogen auf ${formatEuro(report.data.share_basis)}`}
          </p>
        )}
      </div>
      {current && <CategoryDetail item={current} all={items} range={range} type={type} />}
    </section>
  )
}

function CategoryDetail({ item, all, range, type }: {
  item: CategoryItem
  all: CategoryItem[]
  range: { date_from: string; date_to: string }
  type: 'expense' | 'income'
}) {
  // Größte Empfänger der Kategorie im Zeitraum (aus den Buchungen, inkl. Unterkategorien)
  const txs = useTransactions({ ...range, category_id: item.category_id, kind: 'regular', limit: 200 })
  // Nur die passenden regulären Splitanteile der Kategorie inkl. aller Unterkategorien zählen
  const nodes = useMemo(() => all.map((c) => ({ id: c.category_id, parent_id: c.parent_id, item: c })), [all])
  const top = useMemo(
    () => topRecipients(txs.data?.items ?? [], descendantIds(nodes, item.category_id), type),
    [txs.data, nodes, item.category_id, type],
  )
  const subcategories = useMemo(
    () => flattenCategoryTree(nodes.filter((n) => n.id !== item.category_id))
      .filter((n) => descendantIds(nodes, item.category_id).has(n.item.id) && toCents(n.item.item.net) !== 0n)
      .map((n) => ({ ...n.item.item, depth: n.depth })),
    [nodes, item.category_id],
  )
  const topMax = top[0]?.[1] ?? 1n

  return (
    <aside className="category-detail" aria-label={`Details ${item.name}`}>
      <h3>{item.name}</h3>
      <dl className="detail-figures">
        <div><dt>Brutto</dt><dd className="money">{formatEuro(item.gross)}</dd></div>
        <div><dt>{type === 'expense' ? 'Erstattungen' : 'Rückbuchungen'}</dt><dd className="money">{formatEuro(item.refunds)}</dd></div>
        <div className="is-net"><dt>Netto</dt><dd className="money">{formatEuro(item.net)}</dd></div>
      </dl>
      {subcategories.length > 0 && (
        <ul className="detail-children">
          {subcategories.map((c) => (
            <li key={c.category_id} style={c.depth > 0 ? { paddingLeft: `${c.depth * 16}px` } : undefined}><span>{c.name}</span><span className="money">{formatEuro(c.net)}</span></li>
          ))}
        </ul>
      )}
      {top.length > 0 && (
        <>
          <h4>Größte Empfänger</h4>
          <ul className="detail-top">
            {top.map(([name, cents]) => (
              <li key={name}>
                <span className="detail-top-name">{name}</span>
                <span className="money">{formatEuro(fromCents(cents))}</span>
                <span className="share-bar" aria-hidden="true"><span style={{ width: `${Number((cents * 100n) / topMax)}%` }} /></span>
              </li>
            ))}
          </ul>
          {(txs.data?.total ?? 0) > 200 && <p className="muted">aus den letzten 200 Buchungen</p>}
        </>
      )}
    </aside>
  )
}

// --- Verlauf ----------------------------------------------------------------------

function TrendPanel({ to, months, withTable }: { to: string; months: number; withTable?: boolean }) {
  const trends = useProfileQuery<Trends>('reports', '/reports/trends', { months, until: monthEnd(to) })
  const data = (trends.data?.months ?? []).map((m) => ({
    label: MONTHS_SHORT[parseDate(m.month).month - 1] + (parseDate(m.month).month === 1 ? ` ${parseDate(m.month).year}` : ''),
    income: m.income,
    expenses: m.expenses,
    net: m.net,
    month: m.month,
  }))
  return (
    <section className="tile report-panel">
      <header className="panel-head"><h2>Monatsverlauf</h2></header>
      {trends.isLoading && <Loading />}
      {trends.isError && <ErrorBox error={trends.error} onRetry={() => trends.refetch()} />}
      {data.length > 0 && <PairedBars data={data} height={withTable ? 300 : 240} />}
      {withTable && data.length > 0 && (
        <table className="chart-table net-table">
          <thead><tr><th scope="col">Monat</th><th scope="col" className="num">Saldo (Einnahmen − Ausgaben)</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.month}><td>{monthLabel(d.month)}</td><td className={`num${isNegative(d.net) ? ' is-negative' : ''}`}>{formatEuro(d.net)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// --- Konten -----------------------------------------------------------------------

function AccountsPanel({ summary, compact }: { summary?: Summary; compact?: boolean }) {
  const institutions = useInstitutions()
  if (!summary) return <section className="tile report-panel"><Loading /></section>
  const accounts = summary.accounts.filter((a) => !a.archived || (a.balance && toCents(a.balance) !== 0n))
  const groups = compact
    ? [{ name: '', items: accounts }]
    : [
        ...(institutions.data ?? []).map((i) => ({ name: i.name, items: accounts.filter((a) => a.institution_id === i.id) })),
        { name: 'Ohne Bank', items: accounts.filter((a) => a.institution_id === null) },
      ].filter((g) => g.items.length)

  return (
    <section className="tile report-panel">
      <header className="panel-head"><h2>Konten</h2></header>
      {groups.map((g) => (
        <div key={g.name} className="account-group">
          {g.name && <h3>{g.name}</h3>}
          <ul className="account-rows">
            {g.items.map((a) => (
              <li key={a.account_id}>
                <span>{a.name}{a.history_incomplete ? ' *' : ''}</span>
                <span className={`money${a.balance && isNegative(a.balance) ? ' is-negative' : ''}`}>{a.balance ? formatEuro(a.balance) : '–'}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {!compact && (
        <ul className="account-rows totals">
          <li><span>Vermögen</span><span className="money">{formatEuro(summary.assets)}</span></li>
          <li><span>Schulden</span><span className="money">{formatEuro(summary.liabilities)}</span></li>
          <li className="is-net"><span>Nettovermögen</span><span className="money">{formatEuro(summary.net_worth)}</span></li>
        </ul>
      )}
    </section>
  )
}

// --- Kredite ----------------------------------------------------------------------

function LoansPanel({ to }: { to: string }) {
  const report = useProfileQuery<LoanReport>('reports', '/reports/loans', { months: 12, until: monthEnd(to) })
  if (report.isLoading) return <section className="tile report-panel"><Loading /></section>
  if (report.isError) return <ErrorBox error={report.error} onRetry={() => report.refetch()} />
  const loans = report.data?.loans ?? []
  const stateNote = report.data ? currentStateNote(monthEnd(to), report.data.current_as_of) : null
  if (!loans.length) return <section className="tile report-panel"><EmptyState icon="coins" title="Keine Kredite" /></section>
  return (
    <section className="tile report-panel">
      <header className="panel-head">
        <h2>Kredite</h2>
        <p className="muted">
          Monatliche Belastung durch Raten{stateNote && ` – ${stateNote}`}: <strong className="money">{formatEuro(report.data!.monthly_burden)}</strong>
        </p>
      </header>
      {loans.map((loan) => {
        const points = loan.remaining_by_month.filter((p) => p.remaining_debt !== null)
        return (
          <div key={loan.loan_id} className="loan-report">
            <h3>{loan.name} <span className="muted">· Restschuld am {fullDate(monthEnd(to))} {loan.remaining_debt ? formatEuro(loan.remaining_debt) : '–'}</span></h3>
            <p className="muted">
              Status{stateNote && ` – ${stateNote}`}: {loan.status === 'paid_off' ? 'abbezahlt' : 'läuft'}
              {loan.next_installment && ` · nächste Rate ${formatEuro(loan.next_installment)}`}
            </p>
            <table className="chart-table">
              <thead>
                <tr><th scope="col">Monatsende</th>{points.map((p) => <th key={p.month_end} scope="col" className="num">{shortMonthLabel(p.month_end)}</th>)}</tr>
              </thead>
              <tbody>
                <tr><th scope="row">Restschuld</th>{points.map((p) => <td key={p.month_end} className="num">{formatEuro(p.remaining_debt!)}</td>)}</tr>
              </tbody>
            </table>
            {loan.interest_paid_by_year.length > 0 && (
              <p className="muted">
                Zinskosten: {loan.interest_paid_by_year.map((y) => {
                  const d = interestBreakdown(y)
                  const parts = [d.paid && `${formatEuro(d.paid)} gezahlt`, d.charged && `${formatEuro(d.charged)} der Schuld zugeschlagen`].filter(Boolean)
                  return `${d.year}: ${formatEuro(d.total)}${parts.length ? ` (${parts.join(', ')})` : ''}`
                }).join(' · ')}
              </p>
            )}
          </div>
        )
      })}
    </section>
  )
}
