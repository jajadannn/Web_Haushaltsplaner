import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { setApiProfile } from '../api/client'

/** Gewähltes Profil – einmal wählen, im Browser gemerkt (kein Passwort, siehe README). */
const STORAGE_KEY = 'finanzplaner.profile'

interface StoredProfile {
  id: number
  name: string
}

interface ProfileState {
  profile: StoredProfile | null
  choose: (profile: StoredProfile) => void
  clear: () => void
}

const ProfileContext = createContext<ProfileState | null>(null)

function readStored(): StoredProfile | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw)
    return typeof value?.id === 'number' && typeof value?.name === 'string' ? value : null
  } catch {
    return null
  }
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [profile, setProfile] = useState<StoredProfile | null>(() => {
    const stored = readStored()
    setApiProfile(stored?.id ?? null)
    return stored
  })

  const choose = useCallback((next: StoredProfile) => {
    setApiProfile(next.id)
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Ohne Speicher gilt die Wahl nur für diesen Tab
    }
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] === 'p' })
    setProfile(next)
  }, [queryClient])

  const clear = useCallback(() => {
    setApiProfile(null)
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // egal
    }
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] === 'p' })
    setProfile(null)
  }, [queryClient])

  const value = useMemo(() => ({ profile, choose, clear }), [profile, choose, clear])
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useProfile(): ProfileState {
  const value = useContext(ProfileContext)
  if (!value) throw new Error('useProfile außerhalb von ProfileProvider')
  return value
}
