import type { IconName } from '../ui/Icon'

/**
 * Linien-Icon zu einem Kategorie- oder Fixkostennamen (gemeinsam für Startseite, Buchungen,
 * Fixkosten). Erste passende Regel gewinnt; sonst ein neutrales Etikett.
 */
const RULES: [RegExp, IconName][] = [
  [/kredit|darlehen|rate|zins|tilgung/i, 'coins'],
  [/miete|wohn|nebenkosten|haus|garten/i, 'home'],
  [/strom|energie|gas|heizung|wasser/i, 'bolt'],
  [/handy|mobil|telefon|internet|telekom|kommunikation/i, 'phone'],
  [/streaming|abo|medien|netflix|tv|rundfunk/i, 'monitor'],
  [/fitness|sport|verein|hobby|freizeit/i, 'dumbbell'],
  [/lebensmittel|supermarkt|einkauf|rewe|edeka|aldi|lidl/i, 'cart'],
  [/restaurant|café|cafe|bäcker|essen|imbiss/i, 'cup'],
  [/kraftstoff|tank|lade/i, 'fuel'],
  [/auto|kfz|mobilität|bahn|verkehr|parken/i, 'car'],
  [/versicherung/i, 'shield'],
  [/gesundheit|apotheke|arzt|drogerie|körperpflege|friseur/i, 'heart'],
  [/gehalt|lohn|arbeit|bonus/i, 'briefcase'],
  [/bank|gebühr|konto|dividend|sparen|zinsertr/i, 'bank'],
  [/shopping|kleidung|online/i, 'card'],
]

export function iconForName(name: string | null | undefined, fallback: IconName = 'tag'): IconName {
  if (!name) return fallback
  return RULES.find(([re]) => re.test(name))?.[1] ?? fallback
}
