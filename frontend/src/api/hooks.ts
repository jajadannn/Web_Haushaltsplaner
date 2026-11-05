/**
 * Daten-Hooks (TanStack Query). Alle profilbezogenen Schlüssel beginnen mit ['p', profilId, …],
 * damit ein Profilwechsel den Cache sauber trennt. Änderungen invalidieren gezielt die
 * betroffenen Bereiche (`invalidate`).
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useProfile } from '../app/ProfileContext'
import { nextOffset, PAGE_SIZE } from '../pages/buchungen/paging'
import { api, type Query, type Schemas } from './client'

export type User = Schemas['UserRead']
export type Account = Schemas['AccountRead']
export type Institution = Schemas['InstitutionRead']
export type Category = Schemas['CategoryRead']
export type Transaction = Schemas['TransactionRead']
export type TransactionPage = Schemas['TransactionPage']
export type TransactionCreate = Schemas['TransactionCreate']
export type TransactionUpdate = Schemas['TransactionUpdate']
export type BudgetMonth = Schemas['BudgetMonth']
export type MonthItem = Schemas['MonthItem']
export type FixedCost = Schemas['FixedCostRead']
export type Loan = Schemas['LoanRead']
export type Rule = Schemas['RuleRead']
export type ImportBatch = Schemas['ImportBatchRead']
export type ImportRow = Schemas['ImportRowRead']
export type ImportProfile = Schemas['ImportProfileRead']
export type WatchFolder = Schemas['WatchFolderRead']
export type ScheduleEntry = Schemas['ScheduleEntryRead']
export type LoanPayment = Schemas['LoanPaymentRead']
export type Merchant = Schemas['MerchantRead']
export type Suggestion = Schemas['SuggestionRead']
export type Change = Schemas['ChangeRead']
export type FixedCostPayment = Schemas['FixedCostPaymentRead']
export type MonthReserve = Schemas['MonthReserve']

/** Bereiche des Caches – eine Änderung invalidiert alle Bereiche, die sie berühren kann. */
export type Area =
  | 'accounts' | 'institutions' | 'categories' | 'transactions' | 'budget' | 'fixed-costs'
  | 'loans' | 'rules' | 'review' | 'imports' | 'import-profiles' | 'watch-folders' | 'reports'
  | 'suggestions' | 'changes' | 'settings' | 'merchants'

/** Buchungen verändern Salden, Spielraum, Prüfliste, Berichte und Kredite. */
export const MONEY_AREAS: Area[] = ['transactions', 'accounts', 'budget', 'review', 'reports', 'loans']

export function useProfileKey() {
  const { profile } = useProfile()
  return (area: Area, ...rest: unknown[]): QueryKey => ['p', profile?.id ?? 0, area, ...rest]
}

export function useInvalidate() {
  const client = useQueryClient()
  const { profile } = useProfile()
  return (areas: Area[]) =>
    Promise.all(areas.map((area) => client.invalidateQueries({ queryKey: ['p', profile?.id ?? 0, area] })))
}

function useProfileQuery<T>(area: Area, path: string, query?: Query, options?: {
  enabled?: boolean
  /** fest oder abhängig von den zuletzt geladenen Daten (z. B. nur solange etwas verarbeitet wird) */
  refetchInterval?: number | false | ((data: T | undefined) => number | false)
}) {
  const key = useProfileKey()
  const { profile } = useProfile()
  return useQuery({
    queryKey: key(area, path, query ?? null),
    queryFn: ({ signal }) => api.get<T>(path, query, signal),
    enabled: profile !== null && (options?.enabled ?? true),
    refetchInterval: typeof options?.refetchInterval === 'function'
      ? (q) => (options.refetchInterval as (data: T | undefined) => number | false)(q.state.data as T | undefined)
      : options?.refetchInterval,
  })
}

/** Änderung mit anschließendem Neuladen der betroffenen Bereiche. */
export function useApiMutation<TVars, TResult = unknown>(
  run: (vars: TVars) => Promise<TResult>,
  areas: Area[],
  /**
   * Läuft nach dem erfolgreichen Aufruf, sobald die betroffenen Daten neu geladen sind – so
   * passen Meldung und Liste zusammen (die gelöschte Zeile ist dann schon weg). Als Option des
   * Hooks läuft sie auch, wenn das Neuladen die aufrufende Komponente (z. B. den
   * Buchungseditor) ausgehängt hat; per-`mutate`-Callbacks würden dann entfallen.
   */
  onDone?: (result: TResult, vars: TVars) => void,
) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: run,
    onSuccess: async (result, vars) => {
      await invalidate(areas)
      onDone?.(result, vars)
    },
  })
}

// --- Lesen ---------------------------------------------------------------------

export function useUsers() {
  return useQuery({ queryKey: ['users'], queryFn: () => api.anonymous.get<User[]>('/users') })
}

export const useAccounts = (query?: { include_archived?: boolean }) =>
  useProfileQuery<Account[]>('accounts', '/accounts', query)
export const useInstitutions = () => useProfileQuery<Institution[]>('institutions', '/institutions')
export const useCategories = (query?: { type?: 'income' | 'expense'; active?: boolean }) =>
  useProfileQuery<Category[]>('categories', '/categories', query)
export const useBudgetMonth = (month?: string) =>
  useProfileQuery<BudgetMonth>('budget', '/budget/month', { month })
export const useTransactions = (query: Query) =>
  useProfileQuery<TransactionPage>('transactions', '/transactions', query)
/** Buchungsliste seitenweise (feste Seitengröße, Offset); geladene Seiten bleiben bei Folgefehlern erhalten. */
export function useTransactionsInfinite(query: Query) {
  const key = useProfileKey()
  const { profile } = useProfile()
  return useInfiniteQuery({
    queryKey: key('transactions', '/transactions', 'seiten', query),
    queryFn: ({ signal, pageParam }) =>
      api.get<TransactionPage>('/transactions', { ...query, limit: PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (last, all) => nextOffset(last, all.reduce((n, p) => n + p.items.length, 0)),
    enabled: profile !== null,
  })
}
export const useFixedCosts = () => useProfileQuery<FixedCost[]>('fixed-costs', '/fixed-costs')
export const useLoans = () => useProfileQuery<Loan[]>('loans', '/loans')
export const useRules = () => useProfileQuery<Rule[]>('rules', '/mapping-rules')
export const useReview = (query: Query, options?: { refetchInterval?: number | false }) =>
  useProfileQuery<Schemas['ReviewPage']>('review', '/review', query, options)
/** Lokale KI der Prüfliste; fragt alle 10 s nach, solange sie noch Buchungen prüft. */
export const useAiStatus = () =>
  useProfileQuery<Schemas['AiStatus']>('review', '/review/ai', undefined, {
    refetchInterval: (data) => (data?.enabled && data.pending > 0 ? 10_000 : false),
  })
/** Gruppierte Prüfliste (z. B. „Rewe · 4 Buchungen“) mit den enthaltenen Buchungs-IDs. */
export const useReviewGroups = () => useProfileQuery<Schemas['ReviewGroup'][]>('review', '/review/groups')
export const useImportProfiles = () => useProfileQuery<ImportProfile[]>('import-profiles', '/import-profiles')
export const useWatchFolders = () => useProfileQuery<WatchFolder[]>('watch-folders', '/watch-folders')

// --- Vorschläge, Verlauf, Automatik --------------------------------------------

/** Annehmen/Ablehnen/Rücknahme verändern Fixkosten, Spielraum, Verlauf und die Vorschlagsliste. */
export const SUGGESTION_AREAS: Area[] = [
  'suggestions', 'changes', 'fixed-costs', 'budget', 'review', 'rules', 'transactions', 'imports', 'import-profiles', 'merchants',
]

export const useSuggestions = (query: Query) => useProfileQuery<Suggestion[]>('suggestions', '/suggestions', query)
export const useSuggestionSummary = () =>
  useProfileQuery<Record<string, number>>('suggestions', '/suggestions/summary')
export interface SuggestionMetrics {
  items: { kind: string; generator: string; counts: Record<string, number>; acceptance_rate: number | null; revert_rate: number | null }[]
  reverted_changes: number
}
export const useSuggestionMetrics = () => useProfileQuery<SuggestionMetrics>('suggestions', '/suggestions/metrics')
export const useChanges = (query: Query) => useProfileQuery<Change[]>('changes', '/changes', query)
export const useFixedCostPayments = (fixedCostId: number | undefined) =>
  useProfileQuery<FixedCostPayment[]>('fixed-costs', `/fixed-costs/${fixedCostId}/payments`, undefined, {
    enabled: fixedCostId !== undefined,
  })
export const useFixedCostAmounts = (fixedCostId: number | undefined) =>
  useProfileQuery<Schemas['FixedCostAmountRead'][]>('fixed-costs', `/fixed-costs/${fixedCostId}/amounts`, undefined, {
    enabled: fixedCostId !== undefined,
  })
export function useProfileSettings() {
  const { profile } = useProfile()
  return useProfileQuery<Record<string, unknown>>('settings', `/users/${profile?.id ?? 0}/settings`)
}

export { useProfileQuery }
