import type { ItemStatus, MonthItem, WallProfile } from '../api/wall'
import { daysInMonth, parseDate } from '../lib/dates'
import { formatEuro } from '../lib/money'
import { StatusIcon } from './Icons'
import { textWidth } from './measure'
import { dayX, layoutTimeline, type CardGeometry } from './timelineLayout'

/** Maße der Zeitleisten-Kachel in Bühnenpixeln (Bühne 1536×1024, vermessen an wand-c.png). */
const FONT = "'Figtree Variable', Figtree, system-ui, sans-serif"

interface RowMetrics {
  compact: boolean
  axisLeft: number
  axisRight: number
  cardMinX: number
  cardHeight: number
  connector: number
  laneStep: number
  titleSize: number
  subSize: number
  iconSize: number
}

const NORMAL: Omit<RowMetrics, 'axisRight'> = {
  compact: false, axisLeft: 56, cardMinX: 26, cardHeight: 75, connector: 56, laneStep: 87,
  titleSize: 24, subSize: 21, iconSize: 36,
}
const COMPACT: Omit<RowMetrics, 'axisRight'> = {
  compact: true, axisLeft: 262, cardMinX: 240, cardHeight: 58, connector: 14, laneStep: 66,
  titleSize: 20, subSize: 17, iconSize: 28,
}
const NAME_SIZE = 40
const COMPACT_NAME_SIZE = 30
const COMPACT_NAME_WIDTH = 190
const NAME_BOTTOM = 62
const MAX_LANES = 4

const STATUS_WORD: Record<ItemStatus, string> = { paid: 'bezahlt', open: 'fällig', overdue: 'überfällig' }

function itemTitle(item: MonthItem, loanCount: number): string {
  const label = item.kind === 'loan' ? (loanCount === 1 ? 'Kreditrate' : `Rate ${item.name}`) : item.name
  return `${label} ${formatEuro(item.amount)}`
}

function hiddenLabel(hidden: Record<ItemStatus, number>): { total: string; parts: string } | null {
  const parts = (['overdue', 'open', 'paid'] as ItemStatus[])
    .filter((s) => hidden[s] > 0)
    .map((s) => `${hidden[s]} ${STATUS_WORD[s]}`)
  if (!parts.length) return null
  const total = hidden.overdue + hidden.open + hidden.paid
  return { total: `+${total} weitere`, parts: parts.join(' · ') }
}

/** Schriftgröße, bei der `text` in `maxWidth` passt – nie größer als `size`, nie abgeschnitten. */
function fitSize(text: string, weight: number, size: number, maxWidth: number): number {
  const width = textWidth(text, `${weight} ${size}px ${FONT}`)
  return width <= maxWidth ? size : Math.floor((size * maxWidth) / width)
}

interface RowProps {
  profile: WallProfile
  top: number
  height: number
  width: number
  days: number
  today: number
  showTodayLabel: boolean
}

function TimelineRow({ profile, top, height, width, days, today, showTodayLabel }: RowProps) {
  const m: RowMetrics = { ...(height >= 240 ? NORMAL : COMPACT), axisRight: width - 48 }
  const axisY = height - (m.compact ? 44 : 80)
  const lane0Top = axisY - m.connector - m.cardHeight
  const laneTop = (lane: number) => lane0Top - lane * m.laneStep
  const nameWidth = textWidth(profile.name.toUpperCase(), `700 ${NAME_SIZE}px ${FONT}`) * 1.06
  let lanes = 0
  while (lanes < MAX_LANES && laneTop(lanes) >= 6) lanes++

  const loanCount = profile.timeline.filter((i) => i.kind === 'loan').length
  const geometry: CardGeometry = {
    axisLeft: m.axisLeft,
    axisRight: m.axisRight,
    minX: m.cardMinX,
    maxX: width - 10,
    pinOffset: m.compact ? 22 : 29,
    gap: 14,
    lanes,
    avoidX: today > 0 ? dayX(today, days, m) : undefined,
    avoidGap: 12,
    blocked: (lane, left) => !m.compact && laneTop(lane) < NAME_BOTTOM && left < 34 + nameWidth + 24,
  }
  const titleFont = `700 ${m.titleSize}px ${FONT}`
  const subFont = `400 ${m.subSize}px ${FONT}`
  const measure = (item: MonthItem) => {
    const sub = `${parseDate(item.due_date).day}.  ${STATUS_WORD[item.status]}`
    const text = Math.max(textWidth(itemTitle(item, loanCount), titleFont), textWidth(sub, subFont))
    return Math.ceil(18 + m.iconSize + 14 + text + 22)
  }
  const layout = layoutTimeline(profile.timeline, days, geometry, measure)
  const hidden = hiddenLabel(layout.hidden)
  const todayX = dayX(today, days, m)
  const dayList = Array.from({ length: days }, (_, i) => i + 1)

  return (
    <div className={`timeline-row${m.compact ? ' is-compact' : ''}`} style={{ top, height }}>
      <h3
        className="timeline-name"
        style={m.compact ? {
          top: axisY - 56,
          fontSize: fitSize(profile.name.toUpperCase(), 700, COMPACT_NAME_SIZE, COMPACT_NAME_WIDTH),
        } : undefined}
      >
        {profile.name}
      </h3>
      {hidden && (
        m.compact ? (
          <p
            className="timeline-hidden"
            style={{ top: axisY - 12, fontSize: fitSize(hidden.parts, 400, 20, COMPACT_NAME_WIDTH) }}
          >
            {hidden.total}
            <br />
            {hidden.parts}
          </p>
        ) : (
          <p className="timeline-hidden">{hidden.total}: {hidden.parts}</p>
        )
      )}

      {today > 0 && (
        <div
          className="today-line"
          style={{ left: todayX, top: showTodayLabel ? (m.compact ? 30 : 60) : 0, height: axisY + 6 - (showTodayLabel ? (m.compact ? 30 : 60) : 0) }}
        />
      )}
      {today > 0 && showTodayLabel && (
        <p className="today-label" style={{ left: todayX, top: m.compact ? 2 : 22 }}>
          heute {today}.
        </p>
      )}

      <div className="axis" style={{ top: axisY, left: m.axisLeft, width: m.axisRight - m.axisLeft }}>
        <div className="axis-past" style={{ width: Math.max(0, todayX - m.axisLeft) }} />
      </div>
      {dayList.map((day) => {
        const x = dayX(day, days, m)
        return (
          <div key={day}>
            <div className={`tick${day <= today ? ' is-past' : ''}`} style={{ left: x, top: axisY - 6 }} />
            <span className={`day${day === today ? ' is-today' : day < today ? ' is-past' : ''}`} style={{ left: x, top: axisY + (m.compact ? 12 : 18) }}>
              {day}
            </span>
          </div>
        )
      })}

      {layout.cards.map((card) => (
        <div key={`pin-${card.item.kind}-${card.item.ref_id}-${card.item.due_date}`}>
          <div
            className="pin"
            style={{ left: card.pinX, top: laneTop(card.lane) + m.cardHeight, height: axisY - laneTop(card.lane) - m.cardHeight }}
          />
          <article
            className={`event-card status-${card.item.status}`}
            style={{ left: card.left, top: laneTop(card.lane), width: card.width, height: m.cardHeight }}
          >
            <span className="event-icon">
              <StatusIcon status={card.item.status} size={m.iconSize} />
            </span>
            <span className="event-text">
              <strong>{itemTitle(card.item, loanCount)}</strong>
              <span>
                <span className="event-day">{parseDate(card.item.due_date).day}.</span>
                {STATUS_WORD[card.item.status]}
              </span>
            </span>
          </article>
        </div>
      ))}

      {layout.dots.map(({ item, x }) => (
        <div key={`dot-${item.kind}-${item.ref_id}-${item.due_date}`} className={`dot status-${item.status}`} style={{ left: x, top: axisY }} />
      ))}

      {profile.timeline.length === 0 && (
        <p className="timeline-empty" style={{ top: lane0Top + m.cardHeight / 2, left: m.compact ? m.axisLeft : 56 }}>
          Keine Fixkosten oder Kreditraten in diesem Monat
        </p>
      )}
    </div>
  )
}

interface TimelinePanelProps {
  profiles: WallProfile[]
  month: string
  asOf: string
  width: number
  height: number
}

export function TimelinePanel({ profiles, month, asOf, width, height }: TimelinePanelProps) {
  const { year, month: monthNo } = parseDate(month)
  const days = daysInMonth(year, monthNo)
  const asOfDate = parseDate(asOf)
  const today = asOfDate.year === year && asOfDate.month === monthNo ? asOfDate.day : 0
  const rowsTop = 8
  const rowHeight = (height - rowsTop - 12) / Math.max(1, profiles.length)

  return (
    <section className="tile timeline-panel" style={{ width, height }} aria-label="Fälligkeiten im Monat">
      {profiles.map((profile, index) => (
        <TimelineRow
          key={profile.profile_id}
          profile={profile}
          top={rowsTop + index * rowHeight}
          height={rowHeight}
          width={width}
          days={days}
          today={today}
          showTodayLabel={index === 0}
        />
      ))}
    </section>
  )
}
