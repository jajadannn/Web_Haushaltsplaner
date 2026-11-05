import { describe, expect, it } from 'vitest'
import { mergeBatches, pickSelected } from './batches'

const b = (id: number, status = 'done') => ({ id, status })

describe('mergeBatches', () => {
  it('führt Listen ohne Doppelte zusammen, neueste (höchste ID) zuerst', () => {
    const merged = mergeBatches([b(5), b(4)], [b(1, 'awaiting_review'), b(4)], undefined, [b(9)])
    expect(merged.map((x) => x.id)).toEqual([9, 5, 4, 1])
  })

  it('nimmt bei gleicher ID die erste (aktuellere) Fassung', () => {
    expect(mergeBatches([b(2, 'done')], [b(2, 'awaiting_review')])[0].status).toBe('done')
  })
})

describe('pickSelected', () => {
  const list = [b(9), b(3, 'awaiting_review'), b(2, 'failed')]
  it('bevorzugt den separat geladenen Import, auch wenn er nicht in der Liste steht', () => {
    expect(pickSelected(list, 1, b(1, 'done'))?.id).toBe(1)
  })
  it('wählt ohne ID den ersten offenen oder fehlgeschlagenen Import', () => {
    expect(pickSelected(list, null, undefined)?.id).toBe(3)
  })
  it('wählt bei angefragter, aber noch nicht geladener ID nichts anderes', () => {
    expect(pickSelected(list, 77, undefined)).toBeUndefined()
  })
})
