import { useState } from 'react'
import { formatEuro } from '../../lib/money'
import { toCents } from '../../lib/moneyInput'

/**
 * Schlichte Diagramme der Berichte (Regeln aus dem dataviz-Skill):
 * - eine Achse, dünne Balken mit 4px runden Datenenden an der Grundlinie, 2px Abstand
 * - Farben nach Aufgabe: Einnahmen Blau, Ausgaben Magenta (validiert auf #1f2328,
 *   CVD ΔE 15.9, normal ΔE 26.5); Status-Grün/Orange/Rot bleiben Status vorbehalten
 * - Legende ab zwei Reihen, Werte als Tooltip beim Hover/Fokus, Tabelle als Alternative
 */
const SERIES = { income: '#3987e5', expenses: '#d55181' } as const

const euro = (v: string) => Number(toCents(v)) / 100

export interface PairDatum {
  label: string
  income: string
  expenses: string
}

/** Monatsverlauf: Einnahmen und Ausgaben je Monat nebeneinander. */
export function PairedBars({ data, height = 220 }: { data: PairDatum[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const max = Math.max(1, ...data.flatMap((d) => [euro(d.income), euro(d.expenses)]))
  const step = niceStep(max)
  const top = Math.ceil(max / step) * step
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
  const plotH = height - 34
  const y = (v: number) => plotH - (v / top) * plotH

  return (
    <figure className="chart">
      <div className="chart-head">
        <ul className="legend" aria-label="Legende">
          <li><span className="swatch" style={{ background: SERIES.income }} />Einnahmen</li>
          <li><span className="swatch" style={{ background: SERIES.expenses }} />Ausgaben</li>
        </ul>
        <button type="button" className="link chart-toggle" onClick={() => setTable((t) => !t)}>
          {table ? 'Als Diagramm' : 'Als Tabelle'}
        </button>
      </div>
      {table ? (
        <table className="chart-table">
          <thead><tr><th scope="col">Monat</th><th scope="col" className="num">Einnahmen</th><th scope="col" className="num">Ausgaben</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.label}><td>{d.label}</td><td className="num">{formatEuro(d.income)}</td><td className="num">{formatEuro(d.expenses)}</td></tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="pair-chart" style={{ height }}>
          <div className="pair-axis" aria-hidden="true">
            {ticks.map((t) => (
              <span key={t} style={{ top: y(t) }}>{t >= 1000 ? `${(t / 1000).toLocaleString('de-DE')} Tsd.` : t.toLocaleString('de-DE')}</span>
            ))}
          </div>
          <div className="pair-plot" style={{ height: plotH }}>
            {ticks.map((t) => <span key={t} className="gridline" style={{ top: y(t) }} />)}
            <div className="pair-groups" role="list">
              {data.map((d, i) => (
                <div
                  key={d.label}
                  role="listitem"
                  tabIndex={0}
                  className={`pair-group${hover === i ? ' is-hover' : ''}`}
                  aria-label={`${d.label}: Einnahmen ${formatEuro(d.income)}, Ausgaben ${formatEuro(d.expenses)}`}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                >
                  <span className="bar" style={{ height: `${(euro(d.income) / top) * 100}%`, background: SERIES.income }} />
                  <span className="bar" style={{ height: `${(euro(d.expenses) / top) * 100}%`, background: SERIES.expenses }} />
                  <span className="pair-label">{d.label}</span>
                  {hover === i && (
                    <span className="tooltip" role="tooltip">
                      <strong>{d.label}</strong>
                      <span><i style={{ background: SERIES.income }} />Einnahmen <b>{formatEuro(d.income)}</b></span>
                      <span><i style={{ background: SERIES.expenses }} />Ausgaben <b>{formatEuro(d.expenses)}</b></span>
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </figure>
  )
}

function niceStep(max: number): number {
  const raw = max / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  const n = raw / pow
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * pow
}

/** Waagerechter Anteilsbalken (eine Reihe → keine Legende, Wert steht als Text daneben). */
export function ShareBar({ value, max }: { value: string; max: string }) {
  const m = euro(max)
  const width = m > 0 ? Math.max(0.6, (Math.max(0, euro(value)) / m) * 100) : 0
  return (
    <span className="share-bar" aria-hidden="true">
      <span style={{ width: `${width}%` }} />
    </span>
  )
}
