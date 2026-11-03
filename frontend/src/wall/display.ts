/** Abends gedämpft: 1 tagsüber, 0,8 ab 19 Uhr, 0,55 von 22 bis 6 Uhr. */
export function brightnessAt(hour: number): number {
  if (hour >= 22 || hour < 6) return 0.55
  if (hour >= 19) return 0.8
  return 1
}

