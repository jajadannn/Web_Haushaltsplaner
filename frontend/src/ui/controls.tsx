import {
  useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
} from 'react'
import { moneyToInput, parseMoneyInput } from '../lib/moneyInput'
import { Icon, type IconName } from './Icon'

// --- Knöpfe ----------------------------------------------------------------------

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  icon?: IconName
  busy?: boolean
}

export function Button({ variant = 'secondary', icon, busy, children, className = '', disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`btn btn-${variant} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {icon && <Icon name={icon} size={20} />}
      {children}
    </button>
  )
}

// --- Felder ----------------------------------------------------------------------

interface FieldProps {
  label: string
  error?: string | null
  hint?: ReactNode
  children: (id: string) => ReactNode
  className?: string
}

export function Field({ label, error, hint, children, className = '' }: FieldProps) {
  const id = useId()
  return (
    <div className={`field${error ? ' has-error' : ''} ${className}`}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {error ? <p className="field-error" role="alert">{error}</p> : hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  )
}

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string | null
  hint?: ReactNode
}

export function TextField({ label, value, onChange, error, hint, className, ...rest }: TextFieldProps) {
  return (
    <Field label={label} error={error} hint={hint} className={className}>
      {(id) => (
        <input id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined} {...rest} />
      )}
    </Field>
  )
}

interface MoneyFieldProps {
  label: string
  /** Dezimalstring ("12.50") oder null, solange nichts Gültiges eingegeben ist */
  value: string | null
  onChange: (value: string | null) => void
  error?: string | null
  hint?: ReactNode
  large?: boolean
  autoFocus?: boolean
  allowNegative?: boolean
  className?: string
}

/** Betrag im deutschen Format eingeben; liefert den Dezimalstring für die API. */
export function MoneyField({ label, value, onChange, error, hint, large, autoFocus, allowNegative, className }: MoneyFieldProps) {
  const [text, setText] = useState(() => moneyToInput(value))
  const lastEmitted = useRef<string | null>(value)
  const [touched, setTouched] = useState(false)

  // Wert von außen (z. B. Formular zurückgesetzt) übernehmen
  useEffect(() => {
    if (value !== lastEmitted.current) {
      setText(moneyToInput(value))
      lastEmitted.current = value
    }
  }, [value])

  const parsed = parseMoneyInput(text)
  const invalid = text.trim() !== '' && (parsed === null || (!allowNegative && parsed.startsWith('-')))
  const shownError = error ?? (touched && invalid ? 'Bitte einen Betrag wie 12,50 eingeben' : null)

  return (
    <Field label={label} error={shownError} hint={hint} className={className}>
      {(id) => (
        <div className={`money-input${large ? ' is-large' : ''}`}>
          <input
            id={id}
            className="input"
            inputMode="decimal"
            autoComplete="off"
            placeholder="0,00"
            autoFocus={autoFocus}
            value={text}
            aria-invalid={shownError ? true : undefined}
            onChange={(e) => {
              setText(e.target.value)
              const next = parseMoneyInput(e.target.value)
              const ok = next !== null && (allowNegative || !next.startsWith('-')) ? next : null
              lastEmitted.current = ok
              onChange(ok)
            }}
            onBlur={() => {
              setTouched(true)
              if (parsed !== null && !invalid) setText(moneyToInput(parsed))
            }}
          />
          <span className="money-suffix" aria-hidden="true">€</span>
        </div>
      )}
    </Field>
  )
}

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'> {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string; disabled?: boolean }[]
  placeholder?: string
  error?: string | null
  hint?: ReactNode
}

export function SelectField({ label, value, onChange, options, placeholder, error, hint, className, ...rest }: SelectFieldProps) {
  return (
    <Field label={label} error={error} hint={hint} className={className}>
      {(id) => (
        <div className="select">
          <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}
            aria-invalid={error ? true : undefined} {...rest}>
            {placeholder !== undefined && <option value="">{placeholder}</option>}
            {options.map((o) => (
              <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
            ))}
          </select>
          <Icon name="chevronDown" size={18} className="select-chevron" />
        </div>
      )}
    </Field>
  )
}

export function Checkbox({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {hint && <small>{hint}</small>}
      </span>
    </label>
  )
}

/** Auswahl als Chips (z. B. Kategorien beim Erfassen). */
export function ChipGroup<T extends string | number>({ label, options, value, onChange }: {
  label: string
  options: { value: T; label: string }[]
  value: T | null
  onChange: (value: T) => void
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="chips" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            className={`chip${value === o.value ? ' is-active' : ''}`}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Umschalter mit 2–4 Segmenten (Ausgabe | Einnahme | Umbuchung). */
export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T
  onChange: (value: T) => void
  options: { value: T; label: string }[]
  label: string
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          className={value === o.value ? 'is-active' : ''} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Beschrifteter Schalter (z. B. „Nur ungeprüfte“ in einer Filterzeile). */
export function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-track" aria-hidden="true"><span /></span>
      {label}
    </label>
  )
}
