import { describe, expect, it } from 'vitest'
import type { ItemStatus, MonthItem } from '../api/wall'
import { dayX, layoutTimeline, type CardGeometry } from './timelineLayout'

const item = (day: number, status: ItemStatus, name = `i${day}`): MonthItem =>
  ({
    kind: 'fixed',
    ref_id: day,
    name,
    amount: '10.00',
    due_date: `2026-11-${String(day).padStart(2, '0')}`,
    status,
    paid_amount: null,
    paid_on: null,
  }) as unknown as MonthItem

const geo = (over: Partial<CardGeometry> = {}): CardGeometry => ({
  axisLeft: 56,
  axisRight: 1449,
  minX: 26,
  maxX: 1487,
  pinOffset: 29,
  gap: 14,
  lanes: 1,
  ...over,
})
const measure = () => 250
const perDay = 1393 / 29

describe('dayX', () => {
  it('Achsenpositionen', () => {
    expect(dayX(1, 30, geo())).toBe(56)
    expect(dayX(30, 30, geo())).toBeCloseTo(1449, 9)
    expect(dayX(15, 30, geo())).toBeCloseTo(56 + 14 * perDay, 9)
    expect(dayX(5, 1, geo())).toBe(56)
  })
})

describe('layoutTimeline', () => {
  it('(a) Vorlage: vier Karten in einer Spur, Nachbarn weichen nach links aus', () => {
    // Pins: Tag 1 = 56, Tag 15 = 56 + 14·1393/29 = 728,48, Tag 20 = 968,66, Tag 30 = 1449
    // von rechts: Tag 30 an maxX geklemmt → 1487 − 250 = 1237 (Grenze 1237 − 14 = 1223)
    // Tag 20 bevorzugt 939,66 < 1223 − 250 = 973 → bleibt (Grenze 925,66)
    // Tag 15 bevorzugt 699,48 > 925,66 − 250 = 675,66 → weicht aus auf 675,66 (≥ 728,48 + 29 − 250)
    // Tag 1 bevorzugt max(26, 56 − 29) = 27
    const items = [item(1, 'paid'), item(15, 'paid'), item(20, 'open'), item(30, 'open')]
    const r = layoutTimeline(items, 30, geo(), measure)
    expect(r.dots).toHaveLength(4)
    expect(r.hidden).toEqual({ paid: 0, open: 0, overdue: 0 })
    const by = (d: number) => r.cards.find((c) => c.item.ref_id === d)!
    expect(r.cards.every((c) => c.lane === 0)).toBe(true)
    expect(by(30).left).toBe(1237)
    expect(by(20).left).toBeCloseTo(56 + (19 * 1393) / 29 - 29, 6)
    expect(by(15).left).toBeCloseTo(56 + (19 * 1393) / 29 - 29 - 14 - 250, 6)
    expect(by(1).left).toBe(27)
  })

  it('(a2) Ausweichen endet, wo der Pin die Karte verlassen würde', () => {
    // Tag 15 und 17: Tag 17 bleibt bei 824,55 − 29 = 795,55; Tag 15 müsste auf 531,55,
    // darf aber höchstens bis 728,48 + 29 − 250 = 507,48 – passt. Tag 15 und 16 nicht mehr:
    // Tag 16 bei 747,52; Tag 15 müsste auf 483,52 < 507,48 → versteckt
    const fits = layoutTimeline([item(15, 'paid'), item(17, 'open')], 30, geo(), measure)
    expect(fits.cards).toHaveLength(2)
    const tight = layoutTimeline([item(15, 'paid'), item(16, 'open')], 30, geo(), measure)
    expect(tight.cards.map((c) => c.item.ref_id)).toEqual([16])
    expect(tight.hidden.paid).toBe(1)
  })

  it('(b) eine Spur: zweite Karte versteckt, Punkt bleibt', () => {
    const r = layoutTimeline([item(3, 'open'), item(4, 'open')], 30, geo(), measure)
    expect(r.cards).toHaveLength(1)
    expect(r.hidden.open).toBe(1)
    expect(r.dots).toHaveLength(2)
  })

  it('(c) zwei Spuren: Karte der oberen Spur würde den Pin der unteren überdecken', () => {
    // Pin Tag 4 = 200.1 liegt in [123.07-14, 373.07+14] -> kein Platz in Spur 1
    const r = layoutTimeline([item(3, 'open'), item(4, 'open')], 30, geo({ lanes: 2 }), measure)
    expect(r.cards).toHaveLength(1)
    expect(r.cards[0].item.ref_id).toBe(3)
    expect(r.hidden.open).toBe(1)
  })

  it('(d) Priorität: überfällig vor fällig vor bezahlt', () => {
    const r = layoutTimeline([item(3, 'open'), item(4, 'overdue'), item(5, 'paid')], 30, geo(), measure)
    expect(r.cards.map((c) => c.item.status)).toEqual(['overdue'])
    expect(r.hidden).toEqual({ paid: 1, open: 1, overdue: 0 })
  })

  it('(d2) bezahlt: jüngstes Datum zuerst', () => {
    const r = layoutTimeline([item(3, 'paid'), item(4, 'paid')], 30, geo(), measure)
    expect(r.cards.map((c) => c.item.ref_id)).toEqual([4])
  })

  it('(e) blocked sperrt eine Spur', () => {
    const blocked = (lane: number) => lane === 0
    const r = layoutTimeline([item(10, 'open')], 30, geo({ lanes: 2, blocked }), measure)
    expect(r.cards[0].lane).toBe(1)
    const r2 = layoutTimeline([item(10, 'open')], 30, geo({ lanes: 1, blocked }), measure)
    expect(r2.cards).toHaveLength(0)
    expect(r2.hidden.open).toBe(1)
  })
})
