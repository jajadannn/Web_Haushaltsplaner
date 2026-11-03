import { describe, expect, it } from 'vitest'
import { brightnessAt } from './display'

describe('brightnessAt', () => {
  it.each([
    [5, 0.55], [6, 1], [12, 1], [18, 1], [19, 0.8], [21, 0.8], [22, 0.55], [0, 0.55],
  ])('%i Uhr → %f', (hour, expected) => {
    expect(brightnessAt(hour)).toBe(expected)
  })
})
