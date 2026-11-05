import { useState } from 'react'
import { api } from '../../api/client'
import { SUGGESTION_AREAS, useAccounts, useApiMutation, useForecast, useProfileSettings, useSuggestions } from '../../api/hooks'
import { fullDate, shortDate, todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { EmptyState, ErrorBox, Loading, Money, Tile } from '../../ui/blocks'
import { Button, SelectField } from '../../ui/controls'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { parseMissingPayment, parseUnusual } from '../einstellungen/suggestions'
import { eventKindLabel, eventRangeText, forecastAccounts, forecastHorizon, forecastUntil, isLowestEvent, pickForecastAccount } from './forecast'

/** Kachel „Vorschau bis …“: erwartete Ereignisse und Kontostand für das gewählte Zahlkonto. */
export function ForecastTile() {
  const accounts = useAccounts()
  const settings = useProfileSettings()
  const options = forecastAccounts(accounts.data ?? [])
  const [chosen, setChosen] = useState<number | null>(null)
  const accountId = chosen !== null && options.some((a) => a.id === chosen) ? chosen : pickForecastAccount(options)
  const until = forecastUntil(todayISO(), forecastHorizon(settings.data))
  const forecast = useForecast(accountId, until)
  const f = forecast.data

  return (
    <Tile
      className="forecast-tile"
      title={`Vorschau bis ${fullDate(f?.until ?? until)}`}
      action={options.length > 1 && accountId !== null ? (
        <SelectField label="Konto" value={String(accountId)} onChange={(v) => setChosen(Number(v))}
          options={options.map((a) => ({ value: String(a.id), label: a.name }))} />
      ) : undefined}
    >
      {(accounts.isLoading || forecast.isLoading) && <Loading />}
      {forecast.isError && <ErrorBox error={forecast.error} onRetry={() => forecast.refetch()} />}
      {accounts.isSuccess && accountId === null && (
        <EmptyState icon="wallet" title="Kein Zahlkonto für die Vorschau" />
      )}
      {f && (
        <>
          <p className="forecast-start">
            Kontostand heute <Money value={f.start_balance} className="forecast-balance" />
          </p>
          {f.events.length === 0 ? (
            <p className="muted">Bis zu diesem Datum sind keine Zahlungen erwartet.</p>
          ) : (
            <ul className="forecast-events">
              {f.events.map((e) => {
                const range = eventRangeText(e.range)
                const lowest = isLowestEvent(e, f.lowest)
                return (
                  <li key={`${e.kind}-${e.ref_id}-${e.date}`} className={`forecast-event${lowest ? ' is-lowest' : ''}`}>
                    <span className="forecast-date">{shortDate(e.date)}</span>
                    <span className="forecast-name">
                      <strong>{e.name}</strong>
                      <span className="muted">
                        {eventKindLabel(e.kind)}{e.expected ? ' · erwartet' : ''}{range ? ` · ${range}` : ''}
                      </span>
                    </span>
                    <Money value={e.amount} signed />
                    <span className="forecast-after muted">Stand {formatEuro(e.balance_after)}</span>
                    {lowest && <span className="forecast-low-flag"><Icon name="alert" size={16} /> niedrigster Stand</span>}
                  </li>
                )
              })}
            </ul>
          )}
          <p className={`forecast-summary${Number(f.lowest.balance) < 0 ? ' is-negative' : ''}`}>
            Niedrigster Stand: <strong>{formatEuro(f.lowest.balance)}</strong> am {fullDate(f.lowest.date)}
            {' · '}Stand am Ende: <strong>{formatEuro(f.end_balance)}</strong>
          </p>
        </>
      )}
    </Tile>
  )
}

/** Kompakte Hinweise zu fehlenden und auffälligen Zahlungen mit „Zur Kenntnis genommen“. */
export function PaymentHints() {
  const toast = useToast()
  const missing = useSuggestions({ kind: 'missing_payment' })
  const unusual = useSuggestions({ kind: 'unusual_payment' })
  const ack = useApiMutation((id: number) => api.post(`/suggestions/${id}/accept`), SUGGESTION_AREAS)
  const open = (list: typeof missing.data) => (list ?? []).filter((s) => s.status === 'open')
  const items = [
    ...open(missing.data).map((s) => {
      const p = parseMissingPayment(s.payload)
      return { s, text: `${p.name}${p.amount ? ` (${formatEuro(p.amount)})` : ''}: noch keine Zahlung${p.dueDate ? ` seit ${fullDate(p.dueDate)}` : ''} gefunden.` }
    }),
    ...open(unusual.data).map((s) => {
      const p = parseUnusual(s.payload)
      return {
        s,
        text: p.type === 'duplicate'
          ? `${p.name}: möglicherweise doppelt bezahlt.`
          : `${p.name}: ungewöhnlich hohe Zahlung${p.paidAmount ? ` (${formatEuro(p.paidAmount)}${p.amount ? ` statt ${formatEuro(p.amount)}` : ''})` : ''}.`,
      }
    }),
  ]
  if (items.length === 0) return null
  return (
    <Tile className="payment-hints" title={`Zahlungshinweise (${items.length})`}>
      <ul className="hint-list">
        {items.map(({ s, text }) => (
          <li key={s.id} className="hint-row">
            <Icon name="alert" size={18} />
            <span>{text}{s.reason ? <span className="muted"> {s.reason}</span> : null}</span>
            <Button disabled={ack.isPending}
              onClick={() => ack.mutate(s.id, { onSuccess: () => toast.ok('Zur Kenntnis genommen'), onError: toast.error })}>
              Zur Kenntnis genommen
            </Button>
          </li>
        ))}
      </ul>
    </Tile>
  )
}
