/** Seitengröße der Buchungsliste (die API erlaubt höchstens 200). */
export const PAGE_SIZE = 100

/** Offset der nächsten Seite, oder undefined wenn alles geladen ist. */
export function nextOffset(last: { total: number; items: unknown[] }, loaded: number): number | undefined {
  if (last.items.length === 0) return undefined
  return loaded < last.total ? loaded : undefined
}
