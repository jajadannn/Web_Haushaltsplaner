/** Belege & Verträge: Lesen, Hochladen, Verknüpfen, Datei öffnen (Typen im Schema ohne Form, daher eigene). */
import { useEffect, useState } from 'react'
import { api, fetchBlob } from './client'
import { useApiMutation, useProfileQuery, type Area } from './hooks'
import { hasPending, type DocumentItem, type DocumentKind } from '../pages/belege/documents'

export const DOCUMENT_AREAS: Area[] = ['documents', 'suggestions']

/** Solange ein Dokument noch ausgelesen wird, alle 3 Sekunden neu laden. */
export const useDocuments = () =>
  useProfileQuery<DocumentItem[]>('documents', '/documents', undefined, {
    refetchInterval: (data) => (hasPending(data) ? 3000 : false),
  })

export function useUploadDocument(onDone?: (doc: DocumentItem) => void) {
  return useApiMutation(({ file, kind }: { file: File; kind: DocumentKind }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    return api.upload<DocumentItem>('/documents', form)
  }, DOCUMENT_AREAS, onDone)
}

export type LinkTarget = { transaction_id: number } | { fixed_cost_id: number } | { contract_id: number }

export const useLinkDocument = (onDone?: () => void) =>
  useApiMutation(({ id, target }: { id: number; target: LinkTarget }) => api.post(`/documents/${id}/links`, target),
    [...DOCUMENT_AREAS, 'transactions'], onDone)

export const useDeleteDocument = (onDone?: () => void) =>
  useApiMutation((id: number) => api.delete(`/documents/${id}`), [...DOCUMENT_AREAS, 'transactions'], onDone)

/** Gescheitertes Auslesen erneut versuchen. */
export const useRetryDocument = (onDone?: () => void) =>
  useApiMutation((id: number) => api.post(`/documents/${id}/retry`), DOCUMENT_AREAS, onDone)

/** Öffnet die Originaldatei in einem neuen Tab (per Blob, da der Profil-Header nötig ist). */
export async function openDocumentFile(id: number): Promise<void> {
  const url = URL.createObjectURL(await fetchBlob(`/documents/${id}/file`))
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** Blob-URL der Originaldatei für die Vorschau; wird beim Wechsel freigegeben. */
export function useDocumentFileUrl(id: number | null): { url: string | null; error: boolean } {
  const [state, setState] = useState<{ id: number | null; url: string | null; error: boolean }>({ id: null, url: null, error: false })
  useEffect(() => {
    if (id === null) return
    let cancelled = false
    let created: string | null = null
    fetchBlob(`/documents/${id}/file`).then((blob) => {
      created = URL.createObjectURL(blob)
      if (cancelled) URL.revokeObjectURL(created)
      else setState({ id, url: created, error: false })
    }).catch(() => { if (!cancelled) setState({ id, url: null, error: true }) })
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [id])
  return state.id === id ? { url: state.url, error: state.error } : { url: null, error: false }
}
