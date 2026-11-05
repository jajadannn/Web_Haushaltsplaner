/** Listen von Importen zusammenführen und den angezeigten Import bestimmen. */

interface BatchLike {
  id: number
  status: string
}

/** Ohne Doppelte (die erste Fassung gewinnt), neueste ID zuerst. */
export function mergeBatches<T extends BatchLike>(...lists: (T[] | undefined)[]): T[] {
  const byId = new Map<number, T>()
  for (const list of lists) for (const b of list ?? []) if (!byId.has(b.id)) byId.set(b.id, b)
  return [...byId.values()].sort((a, b) => b.id - a.id)
}

/**
 * Der per URL gewählte Import kommt aus einer eigenen Abfrage (er muss nicht unter den
 * neuesten Listeneinträgen sein). Ohne Wahl: erster Import, der Klärung braucht oder fehlschlug.
 */
export function pickSelected<T extends BatchLike>(list: T[], selectedId: number | null, loaded: T | undefined): T | undefined {
  if (selectedId !== null) return loaded?.id === selectedId ? loaded : list.find((b) => b.id === selectedId)
  return list.find((b) => b.status === 'awaiting_review' || b.status === 'failed')
}
