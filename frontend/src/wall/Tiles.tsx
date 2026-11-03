import type { CSSProperties } from 'react'
import type { WallLoan, WallProfile } from '../api/wall'
import { shortMonthLabel } from '../lib/dates'
import { formatEuro, isNegative } from '../lib/money'

/** Text, der seine Schriftgröße an die Kachelbreite anpasst (Container-Einheiten) – nie abgeschnitten. */
function Fit({ text, className, as: Tag = 'p' }: { text: string; className: string; as?: 'p' | 'h2' }) {
  return (
    <Tag className={`fit ${className}`} style={{ '--chars': text.length } as CSSProperties}>
      {text}
    </Tag>
  )
}

function Amount({ value, className }: { value: string; className: string }) {
  return <Fit text={formatEuro(value)} className={className} />
}

export function ProfileTile({ profile }: { profile: WallProfile }) {
  const overdrawn = isNegative(profile.available)
  return (
    <section className={`tile profile-tile${overdrawn ? ' is-overdrawn' : ''}`} aria-label={profile.name}>
      <Fit as="h2" text={profile.name} className="tile-name" />
      <Fit text={overdrawn ? 'Überzogen' : 'Frei verfügbar'} className="tile-label" />
      <Amount value={profile.available} className="available-amount" />
      <Fit
        text={profile.available_per_day ? `${formatEuro(profile.available_per_day)} pro Tag` : 'kein Spielraum mehr'}
        className="tile-sub"
      />
    </section>
  )
}

function installmentsLabel(count: number): string {
  return count === 1 ? 'noch 1 Rate' : `noch ${count} Raten`
}

function LoanBlock({ loan, compact }: { loan: WallLoan; compact: boolean }) {
  const paidOff = loan.status === 'paid_off' || loan.remaining_installments === 0
  return (
    <div className={`loan${compact ? ' is-compact' : ''}`}>
      <Fit as="h2" text={loan.name} className="loan-name" />
      {paidOff ? (
        compact ? (
          <>
            <p className="loan-done">Abbezahlt</p>
            {loan.payoff_date && <Fit text={`seit ${shortMonthLabel(loan.payoff_date)}`} className="tile-sub" />}
          </>
        ) : (
          <>
            <p className="tile-label">Abbezahlt</p>
            <p className="loan-done">
              {loan.payoff_date ? `seit ${shortMonthLabel(loan.payoff_date)}` : 'keine Restschuld'}
            </p>
          </>
        )
      ) : (
        <>
          <p className="tile-label">Restschuld</p>
          {loan.remaining_debt && <Amount value={loan.remaining_debt} className="loan-debt" />}
          {compact ? (
            <Fit
              text={`${loan.payoff_date ? `bis ${shortMonthLabel(loan.payoff_date)} · ` : ''}${
                loan.remaining_installments === 1 ? '1 Rate' : `${loan.remaining_installments} Raten`}`}
              className="tile-sub"
            />
          ) : (
            <p className="tile-sub">
                {loan.payoff_date && <>Abbezahlt {shortMonthLabel(loan.payoff_date)}</>}
                <br />
                {installmentsLabel(loan.remaining_installments)}
            </p>
          )}
        </>
      )}
    </div>
  )
}

export function LoanTile({ loans }: { loans: WallLoan[] }) {
  const compact = loans.length > 1
  return (
    <section className={`tile loan-tile${compact ? ' is-list' : ''}`} aria-label="Kredite">
      {loans.map((loan) => (
        <LoanBlock key={loan.loan_id} loan={loan} compact={compact} />
      ))}
    </section>
  )
}
