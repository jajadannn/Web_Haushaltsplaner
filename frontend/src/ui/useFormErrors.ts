import { useState } from 'react'
import { ApiError } from '../api/client'
import { fieldErrors } from '../api/messages'

/** Fehler eines Formulars: je Feld (aus der API-Validierung) und ein Satz für das ganze Formular. */
export function useFormErrors() {
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  return {
    errors,
    formError,
    reset: () => {
      setErrors({})
      setFormError(null)
    },
    /** Lokale Prüfung: gibt true zurück, wenn alles passt. */
    check: (local: Record<string, string | false | null | undefined>) => {
      const found = Object.fromEntries(Object.entries(local).filter(([, v]) => v)) as Record<string, string>
      setErrors(found)
      setFormError(null)
      return Object.keys(found).length === 0
    },
    fail: (error: unknown) => {
      if (error instanceof ApiError) {
        setErrors(fieldErrors(error.details))
        setFormError(error.message)
      } else setFormError('Das hat nicht geklappt.')
    },
  }
}
