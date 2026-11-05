/** Beschriftungen und kleine Hilfen für „Automatik & KI“ und „Verlauf“. */

export const AUTOMATION_OPTIONS = [
  { value: 'off', label: 'Aus' },
  { value: 'suggest', label: 'Nur Vorschläge' },
  { value: 'dry_run', label: 'Probelauf' },
  { value: 'auto', label: 'Automatisch' },
]

export const AUTOMATION_HELP: Record<string, string> = {
  off: 'Es wird nichts erkannt.',
  suggest: 'Funde erscheinen als Vorschlag. Du entscheidest.',
  dry_run: 'Funde werden nur vermerkt („wäre automatisch angelegt worden“), nichts wird verändert.',
  auto: 'Funde werden sofort angelegt. Im Verlauf lässt sich jede Änderung zurücknehmen.',
}

export const AUTOMATION_KEYS: { key: string; label: string }[] = [
  { key: 'automation.fixed_cost', label: 'Neue Fixkosten erkennen' },
  { key: 'automation.fixed_cost_change', label: 'Änderungen an Fixkosten erkennen (z. B. höherer Betrag)' },
  { key: 'automation.rules', label: 'Regeln vorschlagen' },
  { key: 'automation.split_templates', label: 'Aufteilungsvorlagen vorschlagen' },
]

export function changedSettings(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(after)) if (before[key] !== value) out[key] = value
  return out
}

export function rateLabel(rate: number | null): string {
  return rate === null ? '–' : `${Math.round(rate * 100)} %`
}

export const KIND_LABELS: Record<string, string> = {
  fixed_cost_new: 'Neue Fixkosten',
  fixed_cost_change: 'Fixkosten-Änderung',
  rule: 'Regeln',
  split_template: 'Aufteilungsvorlagen',
}

const OBJECTS: Record<string, string> = {
  fixed_cost: 'Fixkost',
  fixed_cost_payment: 'Zahlungsverknüpfung',
  mapping_rule: 'Regel',
  transaction: 'Buchung',
}
const ACTIONS: Record<string, string> = { create: 'angelegt', update: 'geändert', delete: 'gelöscht' }

export function changeSummary(c: {
  object_type: string
  action: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}): string {
  const object = OBJECTS[c.object_type]
  const action = ACTIONS[c.action]
  if (!object || !action) return `${c.object_type} ${c.action}`
  const name = (c.after ?? c.before)?.name
  return `${object} ${action}${typeof name === 'string' && name ? `: ${name}` : ''}`
}
