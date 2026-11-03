import { useEffect, useRef, useState } from 'react'
import { fetchWall, WallError, type WallView } from '../api/wall'

const REFRESH_MS = 60_000
/** Ab diesem Alter gilt die Anzeige als veraltet, auch wenn der letzte Abruf klappte. */
export const STALE_AFTER_MS = 5 * 60_000

export interface WallState {
  data: WallView | null
  error: WallError | null
  /** Zeitpunkt des letzten erfolgreichen Abrufs (Uhr des Displays). */
  loadedAt: number | null
}

/** Lädt GET /wall sofort und danach jede Minute; behält bei Fehlern den letzten Stand. */
export function useWall(enabled = true): WallState {
  const [state, setState] = useState<WallState>({ data: null, error: null, loadedAt: null })
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false

    async function load() {
      controller.current?.abort()
      const current = new AbortController()
      controller.current = current
      try {
        const data = await fetchWall(current.signal)
        if (!cancelled) setState({ data, error: null, loadedAt: Date.now() })
      } catch (error) {
        if (cancelled || (error as Error).name === 'AbortError') return
        const wallError = error instanceof WallError ? error : new WallError('unknown', 'Unbekannter Fehler.')
        setState((previous) => ({ ...previous, error: wallError }))
      }
    }

    load()
    const timer = window.setInterval(load, REFRESH_MS)
    const onVisible = () => document.visibilityState === 'visible' && load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      controller.current?.abort()
    }
  }, [enabled])

  return state
}

/** Liefert alle `intervalMs` die aktuelle Uhrzeit – für Helligkeit, Einbrennschutz und Altersprüfung. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
