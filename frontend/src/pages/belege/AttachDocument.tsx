import { useRef } from 'react'
import { useUploadDocument } from '../../api/documents'
import { Button } from '../../ui/controls'
import { useToast } from '../../ui/overlay'
import { ACCEPTED_TYPES, type DocumentItem, type DocumentKind } from './documents'

/** Verstecktes Dateifeld hinter einem Knopf; lädt hoch und meldet das neue Dokument. */
export function UploadButton({ kind, label, onUploaded, variant = 'secondary' }: {
  kind: DocumentKind
  label: string
  onUploaded?: (doc: DocumentItem) => void
  variant?: 'primary' | 'secondary' | 'ghost'
}) {
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const upload = useUploadDocument()
  return (
    <>
      <input ref={input} type="file" accept={ACCEPTED_TYPES} hidden aria-label={label}
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          upload.mutate({ file, kind }, {
            onSuccess: (doc) => { toast.ok('Datei hochgeladen'); onUploaded?.(doc) },
            onError: toast.error,
          })
        }} />
      <Button variant={variant} icon="upload" busy={upload.isPending} onClick={() => input.current?.click()}>{label}</Button>
    </>
  )
}
