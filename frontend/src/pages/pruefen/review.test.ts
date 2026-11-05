import { describe, expect, it } from 'vitest'
import {
  confirmIds, consistencyText, parseChange, parseConsistency, parseQuestion, parseRule, ruleEvidenceText, sortSuggestions,
} from './review'

describe('parseRule / ruleEvidenceText', () => {
  it('liest Regelvorschlag und Belege', () => {
    const r = parseRule(
      { name: 'REWE', pattern: 'rewe', match_field: 'counterparty', match_type: 'contains', target_category_id: 7 },
      { confirmed: 3, would_match_open: 5, conflicts: [{ counterparty: 'REWE Bahnhof', category_name: 'Reisen' }] },
    )
    expect(r.pattern).toBe('rewe')
    expect(r.targetCategoryId).toBe(7)
    expect(r.confirmed).toBe(3)
    expect(r.wouldMatchOpen).toBe(5)
    expect(r.conflicts).toHaveLength(1)
    expect(ruleEvidenceText(r)).toBe('3× bestätigt, würde 5 offene Buchungen zuordnen')
  })
  it('kommt mit Zahlen als Konflikten und fehlenden Werten klar', () => {
    const r = parseRule({}, { conflicts: 2 })
    expect(r.matchField).toBe('counterparty')
    expect(r.conflictCount).toBe(2)
    expect(ruleEvidenceText(r)).toBe('0× bestätigt, würde 0 offene Buchungen zuordnen')
  })
  it('Einzahl', () => {
    expect(ruleEvidenceText(parseRule({}, { confirmed: 1, would_match_open: 1 }))).toBe('1× bestätigt, würde 1 offene Buchung zuordnen')
  })
})

describe('parseChange', () => {
  it('unterscheidet einmalig und dauerhaft', () => {
    const c = parseChange({ fixed_cost_id: 4, name: 'Strom', change: 'dauerhaft', old_amount: '50.00', new_amount: 60, valid_from: '2026-11-01' })
    expect(c).toMatchObject({ fixedCostId: 4, permanent: true, oldAmount: '50.00', newAmount: '60', validFrom: '2026-11-01' })
    expect(parseChange({ change: 'einmalig' }).permanent).toBe(false)
  })
})

describe('parseConsistency / consistencyText', () => {
  it('gemischte Kategorien', () => {
    const c = parseConsistency({ type: 'mixed_categories', counterparty: 'Amazon', category_ids: [1, 2], counts: { '1': 4, '2': 2 } })
    expect(c.type).toBe('mixed_categories')
    expect(consistencyText(c, (id) => `K${id}`)).toBe('„Amazon“ ist in mehreren Kategorien gebucht: K1 (4×), K2 (2×).')
  })
  it('ähnliche Kategorien', () => {
    const c = parseConsistency({ type: 'similar_categories', category_ids: [1, 2], names: ['Auto', 'KFZ'] })
    expect(consistencyText(c, String)).toBe('Diese Kategorien wirken ähnlich: Auto, KFZ.')
  })
})

describe('parseQuestion', () => {
  it('liest Optionen', () => {
    const q = parseQuestion({ type: 'contract_split', merchant: 'Telekom', question: 'Ein Vertrag?', options: [{ value: 'one', label: 'Ein Vertrag' }, { bad: 1 }] })
    expect(q.question).toBe('Ein Vertrag?')
    expect(q.options).toEqual([{ value: 'one', label: 'Ein Vertrag' }])
  })
})

describe('confirmIds', () => {
  it('lässt abgewählte Buchungen aus', () => {
    expect(confirmIds([1, 2, 3], new Set([2]))).toEqual([1, 3])
    expect(confirmIds([1, 2], new Set())).toEqual([1, 2])
  })
})

describe('sortSuggestions', () => {
  it('höhere Priorität zuerst, dann neuere', () => {
    const s = [{ id: 1, priority: 1 }, { id: 3, priority: 5 }, { id: 2, priority: 5 }]
    expect(sortSuggestions(s).map((x) => x.id)).toEqual([3, 2, 1])
  })
})
