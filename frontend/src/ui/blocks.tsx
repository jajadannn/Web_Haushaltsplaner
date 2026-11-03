import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { formatEuro, isNegative } from '../lib/money'
import { Icon, type IconName } from './Icon'

/** Kachel der Smart-Home-Sprache, optional mit Titelzeile und Aktion rechts. */
export function Tile({ title, action, children, className = '', as: Tag = 'section' }: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article'
}) {
  return (
    <Tag className={`tile ${className}`}>
      {(title || action) && (
        <header className="tile-header">
          {title && <h2 className="tile-title">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </Tag>
  )
}

/** Seitenkopf: Titel links, Aktionen rechts. */
export function PageHeader({ title, children, back }: { title: ReactNode; children?: ReactNode; back?: string }) {
  return (
    <header className="page-header">
      <div className="page-title">
        {back && (
          <Link to={back} className="icon-btn" aria-label="Zurück">
            <Icon name="chevronLeft" />
          </Link>
        )}
        <h1>{title}</h1>
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  )
}

/** Betrag mit Vorzeichenfarbe: Eingänge grün mit „+“, Ausgänge in Textfarbe. */
export function Money({ value, signed = false, className = '' }: { value: string; signed?: boolean; className?: string }) {
  const negative = isNegative(value)
  const text = formatEuro(value)
  const shown = signed && !negative && value !== '0.00' && !/^0+(\.0+)?$/.test(value) ? `+${text}` : text
  return <span className={`money${signed && !negative ? ' is-income' : ''} ${className}`}>{shown}</span>
}

const STATUS: Record<string, { icon: IconName; label: string; tone: string }> = {
  paid: { icon: 'check', label: 'bezahlt', tone: 'paid' },
  open: { icon: 'clock', label: 'fällig', tone: 'due' },
  overdue: { icon: 'alert', label: 'überfällig', tone: 'overdue' },
  planned: { icon: 'calendar', label: 'geplant', tone: 'muted' },
  skipped: { icon: 'eyeOff', label: 'ausgesetzt', tone: 'muted' },
}

export function StatusBadge({ status, label }: { status: keyof typeof STATUS | string; label?: string }) {
  const s = STATUS[status] ?? STATUS.planned
  return (
    <span className={`status is-${s.tone}`}>
      <Icon name={s.icon} size={18} />
      {label ?? s.label}
    </span>
  )
}

export function EmptyState({ icon = 'info', title, children, action }: {
  icon?: IconName
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <Icon name={icon} size={28} />
      <p className="empty-title">{title}</p>
      {children && <p className="empty-text">{children}</p>}
      {action}
    </div>
  )
}

export function Loading({ label = 'Wird geladen …' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <Icon name="alert" />
      <span>{error instanceof Error ? error.message : 'Das hat nicht geklappt.'}</span>
      {onRetry && <button type="button" className="btn btn-ghost" onClick={onRetry}>Erneut versuchen</button>}
    </div>
  )
}

/** Hinweisleiste (z. B. „1 Eingang ungeklärt · 50,00 €  Prüfen“). */
export function Notice({ tone = 'due', icon = 'info', children, action }: {
  tone?: 'due' | 'overdue' | 'info'
  icon?: IconName
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`notice is-${tone}`}>
      <Icon name={icon} />
      <span className="notice-text">{children}</span>
      {action}
    </div>
  )
}
