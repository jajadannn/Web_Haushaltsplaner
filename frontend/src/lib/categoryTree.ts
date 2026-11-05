/**
 * Kategoriebaum: Die API erlaubt beliebig tiefe Verschachtelung (z. B. nach dem
 * Zusammenführen). Diese Hilfen stellen den Baum rekursiv dar, ohne dass eine Kategorie
 * verschwindet.
 */

export interface TreeNode {
  id: number
  parent_id: number | null
}

export interface FlatNode<T> {
  item: T
  depth: number
}

/** Tiefensuche: Eltern direkt vor ihren Kindern, Geschwister in Eingabereihenfolge. */
export function flattenCategoryTree<T extends TreeNode>(all: T[]): FlatNode<T>[] {
  const ids = new Set(all.map((c) => c.id))
  const children = new Map<number, T[]>()
  const roots: T[] = []
  for (const c of all) {
    if (c.parent_id === null || !ids.has(c.parent_id) || c.parent_id === c.id) roots.push(c)
    else children.set(c.parent_id, [...(children.get(c.parent_id) ?? []), c])
  }
  const out: FlatNode<T>[] = []
  const seen = new Set<number>()
  const visit = (item: T, depth: number) => {
    if (seen.has(item.id)) return
    seen.add(item.id)
    out.push({ item, depth })
    for (const child of children.get(item.id) ?? []) visit(child, depth + 1)
  }
  for (const r of roots) visit(r, 0)
  // Zyklen (kaputte Daten) dürfen nichts verschlucken
  for (const c of all) visit(c, 0)
  return out
}

/** Die Kategorie selbst plus alle Nachkommen (rekursiv). */
export function descendantIds(all: TreeNode[], id: number): Set<number> {
  const result = new Set<number>([id])
  let grew = true
  while (grew) {
    grew = false
    for (const c of all) {
      if (c.parent_id !== null && result.has(c.parent_id) && !result.has(c.id)) {
        result.add(c.id)
        grew = true
      }
    }
  }
  return result
}

/** „Haupt › Unter › Unterunter“; leer, wenn die Kategorie unbekannt ist. */
export function categoryPath(all: (TreeNode & { name: string })[], id: number): string {
  const byId = new Map(all.map((c) => [c.id, c]))
  const names: string[] = []
  const seen = new Set<number>()
  let cur = byId.get(id)
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id)
    names.unshift(cur.name)
    cur = cur.parent_id === null ? undefined : byId.get(cur.parent_id)
  }
  return names.join(' › ')
}
