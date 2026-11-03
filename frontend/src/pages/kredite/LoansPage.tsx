import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, download } from '../../api/client'
import {
  MONEY_AREAS, useAccounts, useApiMutation, useLoans, useProfileQuery,
  type Loan, type LoanPayment, type ScheduleEntry,
} from '../../api/hooks'
import type { Schemas } from '../../api/client'
import { fullDate, parseDate, shortMonthLabel, todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { fromCents, toCents } from '../../lib/moneyInput'
import { loanProgress } from '../../lib/loanProgress'
import { Button } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading, PageHeader, StatusBadge } from '../../ui/blocks'
import { Icon, type IconName } from '../../ui/Icon'
import { Confirm, useToast } from '../../ui/overlay'
import { ChargeDialog, LoanFormDialog, PaymentDialog } from './LoanDialogs'
import { LOAN_TYPE_LABEL, rateLabel } from './labels'
import './kredite.css'

function loanIcon(loan: Loan): IconName {
  return /auto|kfz|wagen/i.test(loan.name) ? 'car' : /haus|wohn|bau|immo/i.test(loan.name) ? 'home' : 'coins'
}

function Progress({ value }: { value: number | null }) {
  if (value === null) return null
  return (
    <div className="progress" role="progressbar" aria-label="Bereits getilgt" aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}>
      <span style={{ width: `${value * 100}%` }} />
    </div>
  )
}

function LoanCard({ loan, selected }: { loan: Loan; selected: boolean }) {
  const paidOff = loan.status === 'paid_off'
  // Ohne ursprüngliche Summe: Fortschritt aus dem Plan (bezahlte Tilgung)
  const schedule = useProfileQuery<ScheduleEntry[]>('loans', `/loans/${loan.id}/schedule`, undefined, { enabled: !loan.principal_original && !paidOff })
  return (
    <Link to={`/kredite/${loan.id}`} className={`tile loan-card${selected ? ' is-selected' : ''}`} aria-current={selected || undefined}>
      <header className="loan-card-head">
        <Icon name={loanIcon(loan)} size={34} />
        <span>
          <strong>{loan.name}</strong>
          <small>{loan.lender_name}, {LOAN_TYPE_LABEL[loan.loan_type]}, {rateLabel(loan.annual_interest_rate)}</small>
        </span>
      </header>
      {paidOff ? (
        <p className="status is-paid loan-card-done"><Icon name="check" /> Abbezahlt</p>
      ) : (
        <>
          <p className="muted">Restschuld</p>
          <p className="loan-card-debt">{formatEuro(loan.remaining_debt)}</p>
          {loan.next_installment && (
            <p className="loan-card-rate">Rate {formatEuro(loan.next_installment)} am {loan.payment_day}.</p>
          )}
          <Progress value={loanProgress(loan, schedule.data)} />
          <p className="loan-card-foot">
            <span>{loan.final_due_date ? `Abbezahlt ${shortMonthLabel(loan.final_due_date)}` : 'Ohne festen Plan'}</span>
            <span>noch {loan.open_installments} {loan.open_installments === 1 ? 'Rate' : 'Raten'}</span>
          </p>
          {loan.overdue_installments > 0 && <StatusBadge status="overdue" label={`${loan.overdue_installments} überfällig`} />}
        </>
      )}
    </Link>
  )
}

export function LoansPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const loans = useLoans()
  const [creating, setCreating] = useState(false)
  // Gelöschte sofort ausblenden – ihre Detailabfragen sollen nicht mehr laufen (404)
  const [deleted, setDeleted] = useState<number[]>([])
  const list = (loans.data ?? []).filter((l) => !deleted.includes(l.id))
  const selected = list.find((l) => String(l.id) === id) ?? list.find((l) => l.status === 'active') ?? list[0]

  return (
    <div className="page loans-page">
      <PageHeader title="Kredite">
        <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>Kredit anlegen</Button>
      </PageHeader>

      {loans.isLoading && <Loading />}
      {loans.isError && <ErrorBox error={loans.error} onRetry={() => loans.refetch()} />}
      {loans.isSuccess && list.length === 0 && (
        <div className="tile">
          <EmptyState icon="coins" title="Noch kein Kredit eingetragen"
            action={<Button variant="primary" icon="plus" onClick={() => setCreating(true)}>Kredit anlegen</Button>}>
            Laufende Kredite trägst du mit der heutigen Restschuld ein. Der Tilgungsplan wird daraus berechnet,
            jede Rate wird in Zinsen und Tilgung aufgeteilt.
          </EmptyState>
        </div>
      )}

      {list.length > 0 && (
        <div className={`loan-cards count-${Math.min(list.length, 3)}`}>
          {list.map((loan) => <LoanCard key={loan.id} loan={loan} selected={loan.id === selected?.id} />)}
        </div>
      )}

      {selected && <LoanDetail key={selected.id} loan={selected} onDeleted={() => { setDeleted((d) => [...d, selected.id]); navigate('/kredite') }} />}

      {creating && (
        <LoanFormDialog
          loan={null}
          onClose={() => setCreating(false)}
          onSaved={(loan) => {
            setCreating(false)
            navigate(`/kredite/${loan.id}`)
          }}
        />
      )}
    </div>
  )
}

type Dialog = 'payment' | 'charge' | 'edit' | null

function LoanDetail({ loan, onDeleted }: { loan: Loan; onDeleted: () => void }) {
  const toast = useToast()
  const [dialog, setDialog] = useState<Dialog>(null)
  const [year, setYear] = useState(parseDate(todayISO()).year)
  const [confirm, setConfirm] = useState<{ kind: 'skip' | 'unskip' | 'storno'; seq?: number; payment?: LoanPayment } | null>(null)
  const [showAll, setShowAll] = useState(false)

  const schedule = useProfileQuery<ScheduleEntry[]>('loans', `/loans/${loan.id}/schedule`)
  const payments = useProfileQuery<LoanPayment[]>('loans', `/loans/${loan.id}/payments`)
  const summary = useProfileQuery<Schemas['LoanYearSummary']>('loans', `/loans/${loan.id}/summary`, { year })
  const accounts = useAccounts({ include_archived: true })
  const payAccount = accounts.data?.find((a) => a.id === loan.payment_account_id)

  const skip = useApiMutation((seq: number) => api.post(`/loans/${loan.id}/schedule/${seq}/skip`), ['loans', 'budget'])
  const unskip = useApiMutation((seq: number) => api.post(`/loans/${loan.id}/schedule/${seq}/unskip`), ['loans', 'budget'])
  const storno = useApiMutation((pid: number) => api.delete(`/loans/${loan.id}/payments/${pid}`), MONEY_AREAS)

  const entries = schedule.data ?? []
  const nextOpen = entries.find((e) => e.status === 'planned')
  const lastSkipped = [...entries].reverse().find((e) => e.status === 'skipped')
  const latestPayment = [...(payments.data ?? [])].sort((a, b) => b.booking_date.localeCompare(a.booking_date) || b.id - a.id)[0]
  // Bezahlte bleiben sichtbar, von den künftigen zunächst nur die nächsten 12
  const firstOpenIndex = entries.findIndex((e) => e.status !== 'paid')
  const visible = showAll || firstOpenIndex < 0 ? entries : entries.slice(0, firstOpenIndex + 12)
  const years = Array.from(new Set([
    ...entries.map((e) => parseDate(e.due_date).year),
    parseDate(todayISO()).year,
  ])).sort()

  const run = (kind: 'skip' | 'unskip' | 'storno') => {
    if (!confirm) return
    const done = { onSuccess: () => { setConfirm(null); toast.ok(kind === 'storno' ? 'Rate storniert' : kind === 'skip' ? 'Rate ausgesetzt' : 'Aussetzen zurückgenommen') }, onError: (e: unknown) => { setConfirm(null); toast.error(e) } }
    if (kind === 'skip' && confirm.seq) skip.mutate(confirm.seq, done)
    if (kind === 'unskip' && confirm.seq) unskip.mutate(confirm.seq, done)
    if (kind === 'storno' && confirm.payment) storno.mutate(confirm.payment.id, done)
  }

  return (
    <section className="tile loan-detail" aria-label={`Details ${loan.name}`}>
      <header className="loan-detail-head">
        <Icon name={loanIcon(loan)} size={38} />
        <h2>{loan.name}</h2>
      </header>

      <div className="loan-actions">
        {loan.status === 'active' && (
          <Button variant="primary" className="btn-large" onClick={() => setDialog('payment')}>Rate buchen</Button>
        )}
        <Button variant="secondary" onClick={() => setDialog('charge')}>Zinsen/Gebühr nachbuchen</Button>
        <Button variant="secondary" onClick={() => setDialog('edit')}>Konditionen ändern</Button>
        <Button variant="secondary" icon="download"
          onClick={() => download(`/export/loans/${loan.id}/schedule.pdf`, `tilgungsplan-${loan.id}.pdf`).catch(toast.error)}>
          Plan als PDF
        </Button>
        <Button variant="ghost" icon="download"
          onClick={() => download(`/export/loans/${loan.id}/schedule.csv`, `tilgungsplan-${loan.id}.csv`).catch(toast.error)}>
          CSV
        </Button>
      </div>

      <div className="loan-facts">
        <p className="loan-year">
          <label>
            <span className="visually-hidden">Jahr</span>
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          {summary.data ? (
            <span>
              Zinsen {formatEuro(fromCents(toCents(summary.data.interest_paid) + toCents(summary.data.interest_charged)))}
              {' · '}Tilgung {formatEuro(summary.data.principal_paid)}
              {toCents(summary.data.extra_paid) + toCents(summary.data.fees_charged) > 0n &&
                ` · Gebühren ${formatEuro(fromCents(toCents(summary.data.extra_paid) + toCents(summary.data.fees_charged)))}`}
              {' · '}{summary.data.payments} {summary.data.payments === 1 ? 'Rate' : 'Raten'} bezahlt
            </span>
          ) : <span className="muted">…</span>}
        </p>
        <p className="muted loan-meta">
          {payAccount ? `Zahlung vom ${payAccount.name}` : 'Kein Zahlkonto hinterlegt'}
          {loan.fixed_rate_until && ` · Zinsbindung bis ${fullDate(loan.fixed_rate_until)}`}
          {toCents(loan.extra_amount) > 0n && ` · Gebühr je Rate ${formatEuro(loan.extra_amount)}`}
        </p>
      </div>

      {schedule.isLoading && <Loading />}
      {schedule.isError && <ErrorBox error={schedule.error} onRetry={() => schedule.refetch()} />}
      {entries.length > 0 && (
        <div className="plan-wrap">
          <table className="plan">
            <thead>
              <tr>
                <th scope="col">Nr.</th>
                <th scope="col">Fällig</th>
                <th scope="col" className="num">Rate</th>
                <th scope="col" className="num">Zinsen</th>
                <th scope="col" className="num">Tilgung</th>
                <th scope="col" className="num">Restschuld</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((e) => {
                const status = e.status === 'paid' ? 'paid' : e.status === 'skipped' ? 'skipped' : e.overdue ? 'overdue' : e.seq === nextOpen?.seq ? 'open' : 'planned'
                return (
                  <tr key={e.seq} className={`is-${status}`}>
                    <td>{e.seq}</td>
                    <td>{fullDate(e.due_date)}</td>
                    <td className="num">{formatEuro(e.planned_installment)}</td>
                    <td className="num">{formatEuro(e.planned_interest)}</td>
                    <td className="num">{formatEuro(e.planned_principal)}</td>
                    <td className="num">{formatEuro(e.planned_remaining_after)}</td>
                    <td>
                      <span className="plan-status">
                        <StatusBadge status={status} />
                        {e.seq === nextOpen?.seq && loan.status === 'active' && (
                          <button type="button" className="mini-btn" onClick={() => setConfirm({ kind: 'skip', seq: e.seq })}>aussetzen</button>
                        )}
                        {e.seq === lastSkipped?.seq && (
                          <button type="button" className="mini-btn" onClick={() => setConfirm({ kind: 'unskip', seq: e.seq })}>zurücknehmen</button>
                        )}
                        {e.status === 'paid' && latestPayment && e.payment_id === latestPayment.id && (
                          <button type="button" className="mini-btn" onClick={() => setConfirm({ kind: 'storno', payment: latestPayment })}>stornieren</button>
                        )}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {visible.length < entries.length && (
            <Button variant="ghost" onClick={() => setShowAll(true)}>Alle {entries.length} Raten zeigen</Button>
          )}
        </div>
      )}
      {schedule.isSuccess && entries.length === 0 && loan.loan_type === 'private' && (
        <p className="muted">Privatkredit ohne festen Plan – Zahlungen frei mit „Rate buchen“ erfassen.</p>
      )}

      {dialog === 'payment' && <PaymentDialog loan={loan} next={nextOpen} onClose={() => setDialog(null)} />}
      {dialog === 'charge' && <ChargeDialog loan={loan} onClose={() => setDialog(null)} />}
      {dialog === 'edit' && (
        <LoanFormDialog loan={loan} onClose={() => setDialog(null)} onSaved={() => setDialog(null)} onDeleted={onDeleted} />
      )}

      <Confirm
        open={confirm !== null}
        danger={confirm?.kind === 'storno'}
        title={confirm?.kind === 'skip' ? `Rate ${confirm.seq} aussetzen?` : confirm?.kind === 'unskip' ? 'Aussetzen zurücknehmen?' : 'Rate stornieren?'}
        text={confirm?.kind === 'skip'
          ? 'Nur mit Absprache mit der Bank: Die Rate entfällt, Zinsen laufen weiter und der Plan verlängert sich.'
          : confirm?.kind === 'unskip'
            ? 'Die ausgesetzte Rate wird wieder eingeplant.'
            : `Die Zahlung vom ${confirm?.payment ? fullDate(confirm.payment.booking_date) : ''} wird zurückgenommen. Eine hier angelegte Zahlung wird gelöscht; eine verknüpfte Buchung (z. B. aus dem Import) bleibt und landet wieder in der Prüfliste.`}
        confirmLabel={confirm?.kind === 'skip' ? 'Aussetzen' : confirm?.kind === 'unskip' ? 'Zurücknehmen' : 'Stornieren'}
        busy={skip.isPending || unskip.isPending || storno.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => confirm && run(confirm.kind)}
      />
    </section>
  )
}
