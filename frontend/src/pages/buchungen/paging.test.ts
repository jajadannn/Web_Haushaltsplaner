import { describe, expect, it } from 'vitest'
import { nextOffset, PAGE_SIZE } from './paging'

describe('nextOffset', () => {
  it('Seitengröße bleibt im API-Limit', () => expect(PAGE_SIZE).toBeLessThanOrEqual(200))
  it('liefert Offset der nächsten Seite', () => {
    expect(nextOffset({ total: 205, items: new Array(100) }, 100)).toBe(100)
    expect(nextOffset({ total: 205, items: new Array(100) }, 200)).toBe(200)
  })
  it('endet, wenn alles geladen ist oder die Seite leer war', () => {
    expect(nextOffset({ total: 205, items: new Array(5) }, 205)).toBeUndefined()
    expect(nextOffset({ total: 300, items: [] }, 100)).toBeUndefined()
  })
})
