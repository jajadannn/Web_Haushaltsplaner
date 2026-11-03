import type { MonthItem, WallProfile, WallView } from '../api/wall'

/**
 * Demodaten mit den Zahlen der freigegebenen Vorlage (wand-c.png).
 * Aufruf: /wand?demo – zum Vergleich mit der Vorlage und zum Entwickeln ohne Daten.
 * Mit ?demo=voll gibt es einen dichten Monat (4 Profile, viele Fixkosten, 2 Kredite).
 */

function item(name: string, amount: string, day: number, status: MonthItem['status'], kind: MonthItem['kind'] = 'fixed'): MonthItem {
  const dueDate = `2026-11-${String(day).padStart(2, '0')}`
  return {
    kind, ref_id: day * 100 + name.length, name, amount, due_date: dueDate, status,
    paid_amount: status === 'paid' ? amount : null, paid_on: status === 'paid' ? dueDate : null,
  }
}

const compItems = (): MonthItem[] => [
  item('Miete', '850.00', 1, 'paid'),
  item('Strom', '90.00', 15, 'paid'),
  item('Handy', '24.99', 20, 'open'),
  item('Autokredit', '230.30', 30, 'open', 'loan'),
]

function profile(id: number, name: string, available: string, perDay: string | null, timeline: MonthItem[]): WallProfile {
  const open = timeline.filter((i) => i.status !== 'paid')
  return {
    profile_id: id, name, available, income: '0.00', fixed_total: '0.00', variable_spent: '0.00',
    available_per_day: perDay, timeline, upcoming: open.slice(0, 6), open_items: open.length,
  }
}

const base = { generated_at: '2026-11-18T20:04:00Z', month: '2026-11-01', as_of: '2026-11-18', days_left: 13 }

export const DEMO_COMP: WallView = {
  ...base,
  profiles: [
    profile(1, 'Fabian', '412.30', '31.72', compItems()),
    profile(2, 'Lea', '286.10', '22.01', compItems()),
  ],
  loans: [{
    loan_id: 1, profile_id: 1, profile_name: 'Fabian', name: 'Autokredit', status: 'active',
    remaining_debt: '7840.12', payoff_date: '2029-12-30', remaining_installments: 38,
    next_due_date: '2026-11-30', next_installment: '230.30',
  }],
}

export const DEMO_FULL: WallView = {
  ...base,
  profiles: [
    profile(1, 'Fabian', '1749.21', '134.55', [
      item('Miete', '850.00', 1, 'paid'), item('Kita', '180.00', 1, 'paid'), item('Strom', '90.00', 2, 'paid'),
      item('Internet', '39.99', 3, 'paid'), item('Versicherung', '62.40', 5, 'paid'), item('Fitness', '29.90', 10, 'overdue'),
      item('Streaming', '13.99', 15, 'paid'), item('Handy', '24.99', 20, 'open'), item('Zeitung', '18.90', 21, 'open'),
      item('Autokredit', '230.30', 30, 'open', 'loan'), item('Möbelkredit', '80.00', 28, 'open', 'loan'),
    ]),
    profile(2, 'Lea', '-15.00', null, [item('Handy Lea', '15.00', 25, 'open')]),
    profile(3, 'Maximilian', '640.00', '49.23', [item('Bahnabo', '58.00', 1, 'paid'), item('Sport', '25.00', 18, 'open')]),
    profile(4, 'Mia', '120.50', '9.27', []),
  ],
  loans: [
    { ...DEMO_COMP.loans[0] },
    { loan_id: 2, profile_id: 1, profile_name: 'Fabian', name: 'Möbelkredit', status: 'active', remaining_debt: '960.00',
      payoff_date: '2027-10-28', remaining_installments: 12, next_due_date: '2026-11-28', next_installment: '80.00' },
    { loan_id: 3, profile_id: 3, profile_name: 'Maximilian', name: 'Laptop', status: 'paid_off', remaining_debt: '0.00',
      payoff_date: '2026-09-15', remaining_installments: 0, next_due_date: null, next_installment: null },
  ],
}

export function demoFromLocation(search: string): WallView | null {
  const value = new URLSearchParams(search).get('demo')
  if (value === null) return null
  return value === 'voll' ? DEMO_FULL : DEMO_COMP
}
