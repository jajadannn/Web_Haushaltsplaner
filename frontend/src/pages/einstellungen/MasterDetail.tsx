import { useEffect, useState, type ReactNode } from 'react'
import { Button } from '../../ui/controls'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { Icon, type IconName } from '../../ui/Icon'

/**
 * Grundmuster der Einstellungen (Entwurf B): Kopf mit Titel, Hinweis und „… anlegen“,
 * links die Liste als Zeilenkarten, rechts das Formular der gewählten Zeile in einer
 * eigenen Kachel. Auf dem Handy öffnet das Formular als Blatt von unten.
 *
 * Jede Einstellungsseite liefert nur Zeile (`renderRow`) und Formular (`renderForm`).
 */
interface Props<T extends { id: number }> {
  title: string
  hint?: ReactNode
  createLabel?: string
  items: T[] | undefined
  isLoading: boolean
  error: unknown
  onRetry: () => void
  renderRow: (item: T, selected: boolean) => ReactNode
  /** item = null: neu anlegen. `done` schließt das Formular (nach Speichern/Löschen). */
  renderForm: (item: T | null, done: () => void) => ReactNode
  formTitle: (item: T | null) => string
  footer?: ReactNode
  empty: { icon: IconName; title: string; text: ReactNode }
}

function useNarrow(): boolean {
  const query = '(max-width: 1100px)'
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const list = window.matchMedia(query)
    const on = () => setNarrow(list.matches)
    list.addEventListener('change', on)
    return () => list.removeEventListener('change', on)
  }, [])
  return narrow
}

export function MasterDetail<T extends { id: number }>(props: Props<T>) {
  const { title, hint, createLabel, items, isLoading, error, onRetry, renderRow, renderForm, formTitle, footer, empty } = props
  // 'new' = Anlegen, Zahl = gewählte Zeile, null = nichts offen
  const [chosen, setSelected] = useState<number | 'new' | null>(null)
  // Gelöschte Zeile → Formular gilt als geschlossen (abgeleitet statt per Effekt nachgezogen)
  const selected = typeof chosen === 'number' && items && !items.some((i) => i.id === chosen) ? null : chosen
  const narrow = useNarrow()
  const current = typeof selected === 'number' ? items?.find((i) => i.id === selected) ?? null : null
  const formOpen = selected === 'new' || current !== null
  const done = () => setSelected(null)

  // Esc schließt das Blatt (wie bisher beim Dialog)
  useEffect(() => {
    if (!narrow || !formOpen) return
    const on = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelected(null) }
    document.addEventListener('keydown', on)
    return () => document.removeEventListener('keydown', on)
  }, [narrow, formOpen])

  const form = formOpen ? renderForm(selected === 'new' ? null : current, done) : null

  return (
    <div className="settings-section">
      <header className="settings-head">
        <div>
          <h2>{title}</h2>
          {hint && <p className="muted">{hint}</p>}
        </div>
        {createLabel && (
          <Button variant="primary" icon="plus" onClick={() => setSelected('new')}>{createLabel}</Button>
        )}
      </header>

      <div className={`settings-split${!narrow ? ' has-form' : ''}`}>
        <div className="tile settings-list">
          {isLoading && <Loading />}
          {error != null && <ErrorBox error={error} onRetry={onRetry} />}
          {items && items.length === 0 && (
            <EmptyState icon={empty.icon} title={empty.title}>
              {empty.text}
            </EmptyState>
          )}
          {items && items.length > 0 && (
            <ul className="rows">
              {items.map((item) => (
                <li key={item.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    className={`row-card settings-row${item.id === selected ? ' is-selected' : ''}`}
                    aria-pressed={item.id === selected}
                    onClick={() => setSelected(item.id === selected ? null : item.id)}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
                        e.preventDefault()
                        setSelected(item.id === selected ? null : item.id)
                      }
                    }}
                  >
                    {renderRow(item, item.id === selected)}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {footer}
        </div>

        {narrow && formOpen && <button type="button" className="settings-sheet-backdrop" aria-label="Schließen" onClick={done} />}
        {/* Ein einziger, an derselben Stelle stehender Formularbaum: beim Wechsel zwischen
            Seitenbereich und Blatt ändert sich nur die Klasse, nichts wird neu eingehängt –
            ungespeicherte Eingaben bleiben beim Ändern der Fensterbreite erhalten. */}
        {(!narrow || formOpen) && (
          <aside
            className={`tile settings-form${narrow ? ' is-sheet' : ''}${formOpen ? '' : ' is-empty'}`}
            aria-label={formOpen ? formTitle(current) : undefined}
            role={narrow ? 'dialog' : undefined}
            aria-modal={narrow ? true : undefined}
          >
            {formOpen ? (
              <>
                <div className="settings-form-head">
                  <h3>{formTitle(selected === 'new' ? null : current)}</h3>
                  {narrow && (
                    <button type="button" className="icon-btn" onClick={done} aria-label="Schließen"><Icon name="close" /></button>
                  )}
                </div>
                {form}
              </>
            ) : (
              <EmptyState icon="edit" title="Eintrag wählen"
                action={createLabel ? <Button variant="secondary" icon="plus" onClick={() => setSelected('new')}>{createLabel}</Button> : undefined}>
                Wähle links einen Eintrag zum Bearbeiten{createLabel ? ' oder lege einen neuen an' : ''}.
              </EmptyState>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

/** Schalter für aktiv/pausiert direkt in der Zeile (stoppt den Klick auf die Zeile). */
export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`switch${checked ? ' is-on' : ''}`}
      onClick={(e) => {
        e.stopPropagation()
        onChange(!checked)
      }}
    >
      <span />
    </button>
  )
}

/** Fußzeile der Formulare: Löschen links, Speichern rechts. */
export function FormActions({ onDelete, busy, deleteLabel = 'Löschen', saveLabel = 'Speichern', extra }: {
  onDelete?: () => void
  busy?: boolean
  deleteLabel?: string
  saveLabel?: string
  extra?: ReactNode
}) {
  return (
    <div className="form-actions">
      {onDelete && <Button variant="danger" onClick={onDelete}>{deleteLabel}</Button>}
      {extra}
      <span className="spacer" />
      <Button variant="primary" type="submit" busy={busy}>{saveLabel}</Button>
    </div>
  )
}
