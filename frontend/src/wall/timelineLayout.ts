import type { ItemStatus, MonthItem } from '../api/wall'
import { parseDate } from '../lib/dates'

/**
 * Verteilt die Fälligkeitskarten einer Zeitleiste auf Spuren über der Achse.
 *
 * - Jede Fälligkeit bekommt einen Punkt auf der Achse – immer.
 * - Karten werden nach Wichtigkeit gesetzt (überfällig → fällig, nächste zuerst → bezahlt,
 *   jüngste zuerst). Eine Karte landet in der untersten Spur, in der sie keine andere Karte
 *   und keinen Pin-Strich einer anderen Karte überdeckt.
 * - Was keinen Platz findet, bleibt nur Punkt und wird gezählt (`hidden`).
 */

export interface CardGeometry {
  axisLeft: number // x von Tag 1
  axisRight: number // x des letzten Tags
  minX: number // linker Rand für Karten
  maxX: number // rechter Rand für Karten
  pinOffset: number // Abstand Kartenkante → Pin, wenn die Karte frei steht
  gap: number // Mindestabstand zwischen Karten einer Spur
  lanes: number // verfügbare Spuren (0 = direkt über der Achse)
  /** x der Heute-Linie: Karten halten links und rechts `avoidGap` Abstand (außer am heutigen Tag). */
  avoidX?: number
  avoidGap?: number
  /** Sperrt Bereiche einer Spur, z. B. hinter dem Profilnamen. */
  blocked?: (lane: number, left: number, right: number) => boolean
}

export interface PlacedCard {
  item: MonthItem
  lane: number
  left: number
  width: number
  pinX: number
}

export interface TimelineLayout {
  dots: { item: MonthItem; x: number }[]
  cards: PlacedCard[]
  hidden: Record<ItemStatus, number>
}

export function dayX(day: number, days: number, g: Pick<CardGeometry, 'axisLeft' | 'axisRight'>): number {
  if (days <= 1) return g.axisLeft
  return g.axisLeft + ((day - 1) * (g.axisRight - g.axisLeft)) / (days - 1)
}

const STATUS_RANK: Record<ItemStatus, number> = { overdue: 0, open: 1, paid: 2 }

export function byImportance(a: MonthItem, b: MonthItem): number {
  const rank = STATUS_RANK[a.status] - STATUS_RANK[b.status]
  if (rank !== 0) return rank
  const order = a.due_date.localeCompare(b.due_date)
  if (order !== 0) return a.status === 'paid' ? -order : order // bezahlt: jüngste zuerst
  return a.name.localeCompare(b.name, 'de')
}

export function layoutTimeline(
  items: MonthItem[],
  days: number,
  geometry: CardGeometry,
  measure: (item: MonthItem) => number,
): TimelineLayout {
  const dots = items.map((item) => ({ item, x: dayX(parseDate(item.due_date).day, days, geometry) }))
  const xOf = new Map(dots.map((d) => [d.item, d.x]))
  let cards: PlacedCard[] = []
  const hidden: Record<ItemStatus, number> = { paid: 0, open: 0, overdue: 0 }

  for (const item of [...items].sort(byImportance)) {
    const candidate = { item, lane: 0, left: 0, width: measure(item), pinX: xOf.get(item)! }
    let placed: PlacedCard[] | null = null
    for (let lane = 0; lane < geometry.lanes && !placed; lane++) {
      placed = arrange([...cards, { ...candidate, lane }], geometry)
    }
    if (placed) cards = placed
    else hidden[item.status] += 1
  }
  cards.sort((a, b) => a.pinX - b.pinX || a.lane - b.lane)
  return { dots, cards, hidden }
}

/**
 * Setzt alle Karten neu: je Spur von rechts nach links zusammengeschoben. Eine Karte steht
 * möglichst mit dem Pin `pinOffset` hinter ihrer linken Kante; muss sie ausweichen, wandert
 * sie nach links, bis der Pin `pinOffset` vor ihrer rechten Kante steht. Liefert null,
 * wenn das nicht aufgeht oder eine Karte den Pin-Strich einer tieferen Spur verdeckt.
 */
function arrange(cards: PlacedCard[], g: CardGeometry): PlacedCard[] | null {
  const result: PlacedCard[] = []
  const lanes = [...new Set(cards.map((c) => c.lane))]
  for (const lane of lanes) {
    const inLane = cards.filter((c) => c.lane === lane).sort((a, b) => b.pinX - a.pinX)
    let limit = g.maxX
    for (const card of inLane) {
      let preferred = Math.max(g.minX, card.pinX - g.pinOffset)
      let lowest = Math.max(g.minX, Math.min(card.pinX + g.pinOffset, g.maxX) - card.width)
      if (g.avoidX !== undefined && Math.abs(card.pinX - g.avoidX) > 0.5) {
        const clear = g.avoidGap ?? g.gap
        if (card.pinX < g.avoidX) {
          limit = Math.min(limit, g.avoidX - clear)
        } else {
          // rechts der Linie: Karte beginnt hinter ihr, der Pin bleibt aber in der Karte
          if (g.avoidX + clear > card.pinX - 12) return null
          preferred = Math.max(preferred, g.avoidX + clear)
          lowest = Math.max(lowest, g.avoidX + clear)
        }
      }
      const left = Math.min(preferred, limit - card.width)
      if (left < lowest - 0.5) return null
      if (g.blocked?.(lane, left, left + card.width)) return null
      result.push({ ...card, left })
      limit = left - g.gap
    }
  }
  for (const upper of result) {
    for (const lower of result) {
      if (lower.lane >= upper.lane) continue
      // Der Pin-Strich der höheren Karte läuft durch die tiefere Spur
      if (upper.pinX >= lower.left - g.gap && upper.pinX <= lower.left + lower.width + g.gap) return null
    }
  }
  return result
}
