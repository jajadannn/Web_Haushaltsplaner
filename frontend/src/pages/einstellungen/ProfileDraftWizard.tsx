import { useRef, useState } from 'react'
import { api } from '../../api/client'
import { useApiMutation, useInstitutions } from '../../api/hooks'
import { shortDate } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Button, SelectField, TextField } from '../../ui/controls'
import { Notice } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import {
  assignmentFromColumnMap, columnMapFromAssignment, isUncertainColumn, ROLE_OPTIONS, SIGN_MODE_LABELS,
  type Assignment, type DraftOptions, type DraftResult,
} from './importDraft'

/**
 * „Profil aus Datei erkennen“: Der Server errät den Aufbau einer CSV-Datei (Spaltenrollen,
 * Formate). Hier lässt sich der Entwurf korrigieren, mit der Vorschau prüfen und – sobald sich
 * die ganze Datei fehlerfrei lesen lässt – als Importprofil speichern.
 */
export function ProfileDraftWizard() {
  const toast = useToast()
  const form = useFormErrors()
  const institutions = useInstitutions()
  const input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [draft, setDraft] = useState<DraftResult | null>(null)
  const [options, setOptions] = useState<DraftOptions | null>(null)
  const [name, setName] = useState('')
  const [institutionId, setInstitutionId] = useState('')

  const upload = (f: File) => { const fd = new FormData(); fd.append('file', f); return fd }
  const load = useApiMutation(
    ({ f, ai }: { f: File; ai: boolean }) => api.upload<DraftResult>(`/import-profiles/draft?ai=${ai}`, upload(f)), [])
  const preview = useApiMutation((o: DraftOptions) => {
    const fd = upload(file!)
    fd.append('settings', JSON.stringify(o))
    return api.upload<DraftResult>('/import-profiles/preview', fd)
  }, [])
  const save = useApiMutation(() => api.post('/import-profiles', {
    name: name.trim(), institution_id: Number(institutionId), format: 'csv', ...options,
  }), ['import-profiles'])

  const busy = load.isPending || preview.isPending
  const reset = () => { setFile(null); setDraft(null); setOptions(null); setName(''); setInstitutionId(''); setOpen(false) }

  function applyDraft(d: DraftResult) { setDraft(d); setOptions(d.options) }
  const ask = (f: File, ai: boolean) => load.mutate({ f, ai }, {
    onSuccess: (d) => {
      applyDraft(d)
      if (ai) toast.ok(d.ai_used ? 'Die KI hat den Entwurf überarbeitet' : 'Die KI konnte nicht helfen – bitte Spalten selbst zuordnen')
    },
    onError: toast.error,
  })
  const change = (patch: Partial<DraftOptions>) => {
    if (!options) return
    const next = { ...options, ...patch }
    setOptions(next)
    preview.mutate(next, { onSuccess: applyDraft, onError: toast.error })
  }

  const header = draft?.header ?? []
  const assignment: Assignment = options ? assignmentFromColumnMap(options.column_map, header) : {}
  const setRole = (column: string, role: string) =>
    change({ column_map: columnMapFromAssignment({ ...assignment, [column]: role }, header, options!.column_map) })

  function submit() {
    if (!form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      institution_id: !institutionId && 'Bitte eine Bank wählen',
    })) return
    save.mutate(undefined, { onSuccess: () => { toast.ok('Profil angelegt'); reset() }, onError: form.fail })
  }

  if (!open) {
    return (
      <section className="tile settings-draft">
        <h3>Profil aus Datei erkennen</h3>
        <p className="muted">Lade eine Beispieldatei deiner Bank hoch – der Finanzplaner schlägt Spalten und Formate selbst vor.</p>
        <Button icon="search" onClick={() => setOpen(true)}>Profil aus Datei erkennen</Button>
      </section>
    )
  }

  return (
    <section className="tile settings-draft" aria-labelledby="draft-title">
      <h3 id="draft-title">Profil aus Datei erkennen</h3>
      <input ref={input} type="file" accept=".csv,.txt" hidden onChange={(e) => {
        const f = e.target.files?.[0]
        if (!f) return
        setFile(f); setDraft(null); setOptions(null)
        ask(f, false)
        e.target.value = ''
      }} />
      <div className="draft-file">
        <Button icon="upload" busy={load.isPending && !draft} onClick={() => input.current?.click()}>{file ? 'Andere Datei wählen' : 'CSV-Datei wählen'}</Button>
        {file && <span className="muted">{file.name}</span>}
        <span className="spacer" />
        <Button variant="ghost" onClick={reset}>Schließen</Button>
      </div>

      {draft && options && (
        <>
          <Notice tone={draft.safe ? 'info' : 'due'} icon={draft.safe ? 'check' : 'alert'}
            action={file && <Button icon="sparkle" busy={load.isPending} onClick={() => ask(file, true)}>KI fragen</Button>}>
            {draft.safe
              ? `Die ganze Datei lässt sich lesen (${draft.rows_parsed} Zeilen). Bitte die Vorschau prüfen.`
              : 'Der Entwurf ist noch nicht sicher. Bitte die markierten Spalten und Formate prüfen oder die KI fragen.'}
            {draft.ai_used && ' · mit KI überarbeitet'}
          </Notice>

          <h4>Spalten</h4>
          <div className="draft-columns">
            {header.map((column) => {
              const uncertain = isUncertainColumn(column, options.column_map, draft.uncertain)
              const unused = !assignment[column]
              return (
                <div key={column} className={`draft-column${uncertain ? ' is-uncertain' : ''}`}>
                  <SelectField label={column || '(ohne Namen)'} value={assignment[column] ?? ''} onChange={(v) => setRole(column, v)}
                    options={ROLE_OPTIONS} hint={uncertain ? 'Unsicher – bitte prüfen' : unused && draft.unassigned.includes(column) ? 'Nicht zugeordnet' : undefined} />
                </div>
              )
            })}
          </div>
          {draft.uncertain.filter((u) => !isUncertainRole(u, options.column_map)).length > 0 && (
            <p className="field-error" role="note">
              Noch nicht gefunden: {draft.uncertain.filter((u) => !isUncertainRole(u, options.column_map)).join(', ')}
            </p>
          )}

          <h4>Formate</h4>
          <div className="form-grid">
            <SelectField label="Betrag in der Datei" value={options.sign_mode} onChange={(v) => change({ sign_mode: v })}
              options={Object.entries(SIGN_MODE_LABELS).map(([value, label]) => ({ value, label }))} />
            <TextField label="Datumsformat" value={options.date_format} onChange={(v) => setOptions({ ...options, date_format: v })}
              onBlur={() => change({})} maxLength={20} className={draft.uncertain.includes('date_format') ? 'is-uncertain' : undefined}
              hint="%d.%m.%Y = 31.01.2026, %Y-%m-%d = 2026-01-31" />
          </div>
          <div className="form-grid">
            <TextField label="Dezimaltrenner" value={options.decimal_sep} onChange={(v) => setOptions({ ...options, decimal_sep: v })}
              onBlur={() => change({})} maxLength={1} />
            <TextField label="Tausendertrenner" value={options.thousands_sep} onChange={(v) => setOptions({ ...options, thousands_sep: v })}
              onBlur={() => change({})} maxLength={1} />
          </div>

          <h4>Vorschau {preview.isPending && <Icon name="refresh" size={16} className="spin" />}</h4>
          {draft.preview.length === 0 ? <p className="muted">Keine Zeilen gelesen.</p> : (
            <div className="draft-preview">
              <table>
                <thead><tr><th>Zeile</th><th>Datum</th><th>Empfänger / Zweck</th><th className="num">Betrag</th></tr></thead>
                <tbody>
                  {draft.preview.slice(0, 10).map((r) => (
                    <tr key={r.row_no}>
                      <td>{r.row_no}</td>
                      <td>{r.booking_date ? shortDate(r.booking_date) : '–'}</td>
                      <td><strong>{r.counterparty || r.description || '–'}</strong>{r.counterparty && r.description ? <span className="muted"> · {r.description}</span> : null}</td>
                      <td className="num money">{r.amount ? formatEuro(r.amount) : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {draft.errors.length > 0 && (
            <ul className="batch-errors" aria-label="Zeilenfehler">
              {draft.errors.slice(0, 10).map((e) => <li key={e.row_no}>Zeile {e.row_no}: {e.message}</li>)}
              {draft.errors.length > 10 && <li>… und {draft.errors.length - 10} weitere</li>}
            </ul>
          )}

          <h4>Speichern</h4>
          <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
            <div className="form-grid">
              <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} placeholder="z. B. Sparkasse Girokonto" />
              <SelectField label="Bank" value={institutionId} onChange={setInstitutionId} placeholder="Bitte wählen" error={form.errors.institution_id}
                options={(institutions.data ?? []).map((i) => ({ value: String(i.id), label: i.name }))} />
            </div>
            {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
            <div className="form-actions">
              <span className="spacer" />
              <Button variant="primary" type="submit" busy={save.isPending} disabled={!draft.safe || busy}
                title={draft.safe ? undefined : 'Erst speichern, wenn sich die ganze Datei fehlerfrei lesen lässt'}>
                Profil speichern
              </Button>
            </div>
          </form>
        </>
      )}
    </section>
  )
}

/** Rolle ist zugeordnet (dann steht sie schon an einer Spalte und braucht keinen Extrahinweis). */
function isUncertainRole(role: string, map: DraftOptions['column_map']): boolean {
  return role === 'date_format' || role in map
}
