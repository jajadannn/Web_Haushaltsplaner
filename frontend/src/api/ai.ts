/** Antworttypen der KI-nahen Endpunkte (im OpenAPI-Schema ohne Form, daher hier beschrieben). */

export interface ForecastEvent {
  date: string
  name: string
  amount: string
  kind: 'fixed_cost' | 'expected_income' | 'loan_installment' | 'transaction'
  expected: boolean
  ref_id: number
  range?: string[] | null
  balance_after: string
}

export interface Forecast {
  account_id: number
  as_of: string
  until: string
  start_balance: string
  events: ForecastEvent[]
  end_balance: string
  lowest: { date: string; balance: string }
}

export interface ComparisonCategory {
  category_id: number | null
  name: string
  current: string
  previous: string
  average_3: string
  delta: string
}

export interface ComparisonTransaction {
  transaction_id: number
  date: string
  amount: string
  counterparty: string | null
  description: string | null
}

export interface MonthComparison {
  month: string
  until: string
  incomplete: boolean
  expenses: string
  previous_expenses: string
  delta: string
  categories: ComparisonCategory[]
  largest: ComparisonTransaction[]
  one_offs: ComparisonTransaction[]
}

export interface MonthExplanation {
  text: string
  references: number[]
  comparison: MonthComparison
}

export interface AskAnswer {
  question: string
  tool: string
  parameters: Record<string, unknown>
  period: { from: string; to: string } | null
  data_as_of: string | null
  answer: string
  references: number[]
  result: unknown
}

export interface ParsedEntry {
  amount: string | number | null
  booking_date: string | null
  account_id: number | null
  category_id: number | null
  description: string | null
  questions: string[]
  possible_duplicate: {
    id: number
    booking_date: string
    amount: string
    description: string | null
    counterparty: string | null
  } | null
  ai_used: boolean
}
