/**
 * Zugriff auf die Finanzplaner-API.
 *
 * - Basis `/api` (Vite leitet in der Entwicklung weiter, app/server.py im Betrieb).
 * - Das gewählte Profil geht als `X-User-Id` mit.
 * - Fehler kommen immer als `{error: {code, message, details}}` und werden zu `ApiError`.
 * - Typen stammen aus `schema.d.ts` (npm run gen:api) – nie von Hand nachbauen.
 */
import type { components } from './schema'
import { messageFor } from './messages'

export type Schemas = components['schemas']

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let currentProfileId: number | null = null

/** Wird vom ProfileContext gesetzt; alle folgenden Anfragen laufen für dieses Profil. */
export function setApiProfile(id: number | null): void {
  currentProfileId = id
}

export type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>

/** Query-String ohne leere Werte; Listen als wiederholte Parameter (account_ids=1&account_ids=2). */
export function toQuery(query?: Query): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)))
    else params.append(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

interface RequestOptions {
  query?: Query
  body?: unknown
  form?: FormData
  signal?: AbortSignal
  /** Ohne Profil-Header (z. B. /users vor der Profilwahl). */
  anonymous?: boolean
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (!options.anonymous && currentProfileId !== null) headers['X-User-Id'] = String(currentProfileId)
  let body: BodyInit | undefined
  if (options.form) body = options.form
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}${toQuery(options.query)}`, {
      method, headers, body, signal: options.signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError(0, 'network', messageFor('network'))
  }

  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = payload?.error
    const code: string = error?.code ?? `http_${response.status}`
    throw new ApiError(response.status, code, messageFor(code, error?.message, error?.details), error?.details ?? null)
  }
  return payload as T
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body, query }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  delete: (path: string) => request<void>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
  anonymous: {
    get: <T>(path: string) => request<T>('GET', path, { anonymous: true }),
    post: <T>(path: string, body: unknown) => request<T>('POST', path, { body, anonymous: true }),
  },
}

/**
 * Export herunterladen (CSV/PDF). Der Profil-Header lässt sich an einem Link nicht setzen,
 * deshalb per fetch als Blob und dann über einen temporären Link speichern.
 */
export async function download(path: string, fallbackName: string, query?: Query): Promise<void> {
  const headers: Record<string, string> = {}
  if (currentProfileId !== null) headers['X-User-Id'] = String(currentProfileId)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}${toQuery(query)}`, { headers })
  } catch {
    throw new ApiError(0, 'network', messageFor('network'))
  }
  if (!response.ok) {
    const error = (await response.json().catch(() => null))?.error
    const code: string = error?.code ?? `http_${response.status}`
    throw new ApiError(response.status, code, messageFor(code, error?.message, error?.details))
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName
  const url = URL.createObjectURL(await response.blob())
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Datei (z. B. Beleg) als Blob laden – der Profil-Header lässt sich an einem Link nicht setzen. */
export async function fetchBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (currentProfileId !== null) headers['X-User-Id'] = String(currentProfileId)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { headers })
  } catch {
    throw new ApiError(0, 'network', messageFor('network'))
  }
  if (!response.ok) {
    const error = (await response.json().catch(() => null))?.error
    const code: string = error?.code ?? `http_${response.status}`
    throw new ApiError(response.status, code, messageFor(code, error?.message, error?.details))
  }
  return response.blob()
}
