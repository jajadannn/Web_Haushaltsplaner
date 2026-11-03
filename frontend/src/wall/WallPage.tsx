import { useEffect, useState } from 'react'
import type { WallView } from '../api/wall'
import { daysLeftLabel, monthLabel, standLabel } from '../lib/dates'
import { demoFromLocation } from './demo'
import { brightnessAt } from './display'
import { LoanTile, ProfileTile } from './Tiles'
import { TimelinePanel } from './Timeline'
import { STALE_AFTER_MS, useNow, useWall } from './useWall'
import './wall.css'

/** Bühne in Pixeln der freigegebenen Vorlage; sie wird als Ganzes aufs Display skaliert. */
const STAGE_W = 1536
const STAGE_H = 1024
const STAGE_MAX_W = 2048 // breiter als 2:1 wird nicht gestreckt
const PANEL = { x: 18, y: 393, h: 595, rightGap: 21 }

/** Einbrennschutz: alle 5 Minuten wandert die Bühne um wenige Pixel auf einem kleinen Kreis. */
const SHIFT_STEPS = [[0, 0], [4, 2], [6, -3], [2, -6], [-3, -4], [-6, 1], [-4, 5], [1, 6]]
const SHIFT_MS = 5 * 60_000

/** Höhe ist fest 1024; auf breiteren Displays (16:9) wächst die Bühne in die Breite mit. */
function stageFor(viewW: number, viewH: number) {
  const width = Math.round(Math.min(STAGE_MAX_W, Math.max(STAGE_W, (STAGE_H * viewW) / viewH)))
  return { width, scale: Math.min(viewW / width, viewH / STAGE_H) }
}

function useStage() {
  const [stage, setStage] = useState(() => stageFor(window.innerWidth, window.innerHeight))
  useEffect(() => {
    const onResize = () => setStage(stageFor(window.innerWidth, window.innerHeight))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return stage
}

interface WallProps {
  data: WallView
  width: number
  stale: boolean
  connectionLost: boolean
}

function Wall({ data, width, stale, connectionLost }: WallProps) {
  return (
    <>
      <header className="wall-header">
        <h1 className="month-title">{monthLabel(data.month)}</h1>
        <p className={`status-line${stale ? ' is-stale' : ''}`}>
          <span>Stand {standLabel(data.generated_at)}</span>
          {connectionLost && <span className="status-warn">keine Verbindung</span>}
          <span className="days-left">{daysLeftLabel(data.days_left)}</span>
        </p>
      </header>

      <div className="tile-row">
        {data.profiles.map((profile) => (
          <ProfileTile key={profile.profile_id} profile={profile} />
        ))}
        {data.loans.length > 0 && <LoanTile loans={data.loans} />}
      </div>

      {data.profiles.length > 0 ? (
        <div className="panel-slot" style={{ left: PANEL.x, top: PANEL.y }}>
          <TimelinePanel profiles={data.profiles} month={data.month} asOf={data.as_of} width={width - PANEL.x - PANEL.rightGap} height={PANEL.h} />
        </div>
      ) : (
        <p className="wall-message" style={{ top: PANEL.y + 200 }}>
          Noch keine Profile angelegt. Sobald es ein Profil mit Fixkosten gibt, erscheint hier der Monat.
        </p>
      )}
    </>
  )
}

export function WallPage() {
  const [demo] = useState(() => demoFromLocation(window.location.search))
  const live = useWall(demo === null)
  const { data, error, loadedAt } = demo ? { data: demo, error: null, loadedAt: null } : live
  const { width: stageWidth, scale } = useStage()
  const now = useNow(30_000)
  const [dx, dy] = SHIFT_STEPS[Math.floor(now / SHIFT_MS) % SHIFT_STEPS.length]
  const stale = loadedAt !== null && now - loadedAt > STALE_AFTER_MS

  // Kartenbreiten werden mit der Webschrift vermessen – nach dem Laden einmal neu setzen.
  const [, setFontsReady] = useState(false)
  useEffect(() => {
    document.title = 'Finanzplaner · Wand'
    document.fonts.ready.then(() => setFontsReady(true))
  }, [])

  return (
    <main className="wall-viewport" style={{ filter: `brightness(${brightnessAt(new Date(now).getHours())})` }}>
      <div
        className="wall-stage"
        style={{ width: stageWidth, height: STAGE_H, transform: `translate(-50%, -50%) translate(${dx}px, ${dy}px) scale(${scale})` }}
      >
        {data ? (
          <Wall data={data} width={stageWidth} stale={stale} connectionLost={error !== null} />
        ) : (
          <p className="wall-message" style={{ top: 440 }}>
            {error ? error.message : 'Übersicht wird geladen …'}
          </p>
        )}
      </div>
    </main>
  )
}
