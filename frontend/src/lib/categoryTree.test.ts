import { describe, expect, it } from 'vitest'
import { categoryPath, descendantIds, flattenCategoryTree } from './categoryTree'

const c = (id: number, parent_id: number | null, name = `K${id}`) => ({ id, parent_id, name })

describe('flattenCategoryTree', () => {
  it('liefert Eltern vor ihren Kindern mit Tiefe, auch ab Ebene drei', () => {
    const all = [c(1, null), c(2, 1), c(3, 2), c(4, null), c(5, 1)]
    expect(flattenCategoryTree(all).map((n) => [n.item.id, n.depth])).toEqual([
      [1, 0], [2, 1], [3, 2], [5, 1], [4, 0],
    ])
  })

  it('behandelt Kategorien mit unbekanntem Elternteil als Wurzel', () => {
    const all = [c(2, 99), c(3, 2)]
    expect(flattenCategoryTree(all).map((n) => [n.item.id, n.depth])).toEqual([[2, 0], [3, 1]])
  })

  it('lässt keine Kategorie verschwinden, auch nicht bei Zyklen', () => {
    const all = [c(1, 2), c(2, 1)]
    expect(flattenCategoryTree(all).map((n) => n.item.id).sort()).toEqual([1, 2])
  })
})

describe('descendantIds', () => {
  it('enthält die Kategorie selbst und alle Nachkommen rekursiv', () => {
    const all = [c(1, null), c(2, 1), c(3, 2), c(4, null)]
    expect([...descendantIds(all, 1)].sort()).toEqual([1, 2, 3])
    expect([...descendantIds(all, 4)]).toEqual([4])
  })
})

describe('categoryPath', () => {
  it('verbindet die Vorfahren mit ›', () => {
    const all = [c(1, null, 'A'), c(2, 1, 'B'), c(3, 2, 'C')]
    expect(categoryPath(all, 3)).toBe('A › B › C')
    expect(categoryPath(all, 99)).toBe('')
  })
})
