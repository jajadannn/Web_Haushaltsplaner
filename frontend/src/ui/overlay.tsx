import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Icon } from './Icon'

// --- Dialog (Desktop: mittig; Handy: Blatt von unten) ----------------------------

interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}

/** Modaler Dialog über das native <dialog> – Fokusfalle, Esc und Hintergrund-Sperre inklusive. */
export function Dialog({ open, onClose, title, children, footer, wide }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={`dialog${wide ? ' is-wide' : ''}`}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose() // Klick auf den abgedunkelten Rand
      }}
    >
      {open && (
        <div className="dialog-body">
          <header className="dialog-header">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Schließen">
              <Icon name="close" />
            </button>
          </header>
          <div className="dialog-content">{children}</div>
          {footer && <footer className="dialog-footer">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}

/** Rückfrage vor endgültigen Aktionen (Löschen, Stornieren). */
export function Confirm({ open, title, text, confirmLabel, onConfirm, onCancel, busy, danger = true }: {
  open: boolean
  title: string
  text: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
  danger?: boolean
}) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Abbrechen</button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="dialog-text">{text}</div>
    </Dialog>
  )
}

// --- Meldungen ------------------------------------------------------------------

interface Toast {
  id: number
  text: string
  tone: 'ok' | 'error'
  action?: { label: string; run: () => void }
}

const ToastContext = createContext<((t: Omit<Toast, 'id'>) => void) | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)
  const push = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = next.current++
    setToasts((list) => [...list.slice(-2), { ...toast, id }])
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), toast.tone === 'error' ? 8000 : 4500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast is-${t.tone}`}>
            <Icon name={t.tone === 'ok' ? 'check' : 'alert'} size={20} />
            <span>{t.text}</span>
            {t.action && (
              <button type="button" onClick={() => { t.action?.run(); setToasts((l) => l.filter((x) => x.id !== t.id)) }}>
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const push = useContext(ToastContext)
  if (!push) throw new Error('useToast außerhalb von ToastProvider')
  return {
    ok: (text: string, action?: Toast['action']) => push({ text, tone: 'ok', action }),
    error: (error: unknown) => push({ text: error instanceof Error ? error.message : String(error), tone: 'error' }),
  }
}
