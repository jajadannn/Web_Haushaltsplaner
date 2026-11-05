import { useState } from 'react'
import { api } from '../../api/client'
import { useApiMutation, useProfileSettings, useSuggestionMetrics } from '../../api/hooks'
import { useProfile } from '../../app/ProfileContext'
import { Button, Checkbox, SelectField, TextField } from '../../ui/controls'
import { ErrorBox, Loading } from '../../ui/blocks'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'
import { AUTOMATION_HELP, AUTOMATION_KEYS, AUTOMATION_OPTIONS, KIND_LABELS, changedSettings, rateLabel } from './automation'

/** Automatik & KI: Einstellungen je Profil und die Qualität der bisherigen Vorschläge. */
export function AutomationSection() {
  const settings = useProfileSettings()
  return (
    <div className="settings-section">
      <header className="settings-head">
        <div>
          <h2>Automatik &amp; KI</h2>
          <p className="muted">Lege fest, wie viel der Finanzplaner selbst erledigen darf. Gilt nur für dieses Profil.</p>
        </div>
      </header>
      <section className="tile settings-profile">
        {settings.isLoading && <Loading />}
        {settings.isError && <ErrorBox error={settings.error} onRetry={() => settings.refetch()} />}
        {settings.data && <SettingsForm initial={settings.data} />}
      </section>
      <Metrics />
    </div>
  )
}

function SettingsForm({ initial }: { initial: Record<string, unknown> }) {
  const { profile } = useProfile()
  const toast = useToast()
  const form = useFormErrors()
  const [values, setValues] = useState<Record<string, unknown>>(initial)
  const set = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }))
  const save = useApiMutation(
    (changes: Record<string, unknown>) => api.patch(`/users/${profile!.id}/settings`, changes),
    ['settings', 'suggestions'],
  )

  function submit() {
    const horizon = Number(values['forecast.horizon_days'])
    if (!form.check({ horizon: (!Number.isInteger(horizon) || horizon < 1 || horizon > 366) && 'Bitte 1 bis 366 Tage angeben' })) return
    const changes = changedSettings(initial, { ...values, 'forecast.horizon_days': horizon })
    if (Object.keys(changes).length === 0) { toast.ok('Nichts geändert'); return }
    save.mutate(changes, { onSuccess: () => toast.ok('Einstellungen gespeichert'), onError: form.fail })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      {AUTOMATION_KEYS.map(({ key, label }) => (
        <SelectField key={key} label={label} value={String(values[key] ?? 'suggest')} onChange={(v) => set(key, v)}
          options={AUTOMATION_OPTIONS} hint={AUTOMATION_HELP[String(values[key] ?? 'suggest')]} />
      ))}
      <Checkbox label="Lokale KI darf Buchungen prüfen" checked={values['ai.enabled'] === true}
        onChange={(v) => set('ai.enabled', v)} hint="Die KI läuft auf diesem Rechner, es gehen keine Daten ins Internet." />
      <TextField label="Vorschau-Zeitraum in Tagen" type="number" value={String(values['forecast.horizon_days'] ?? 45)}
        onChange={(v) => set('forecast.horizon_days', v)} error={form.errors.horizon} />
      <Checkbox label="Profilübergreifend vergleichen" checked={values['household.cross_profile_matching'] === true}
        onChange={(v) => set('household.cross_profile_matching', v)}
        hint="Hilft z. B. bei Umbuchungen zwischen den Profilen des Haushalts." />
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <div className="form-actions">
        <Button variant="primary" type="submit" busy={save.isPending}>Speichern</Button>
      </div>
    </form>
  )
}

const COUNT_LABELS: [string, string][] = [
  ['open', 'offen'], ['accepted', 'übernommen'], ['auto_applied', 'automatisch'],
  ['rejected', 'abgelehnt'], ['reverted', 'zurückgenommen'],
]

function Metrics() {
  const metrics = useSuggestionMetrics()
  const items = metrics.data?.items ?? []
  return (
    <section className="tile" aria-labelledby="metrics-title">
      <h3 id="metrics-title">Wie gut sind die Vorschläge?</h3>
      {metrics.isLoading && <Loading />}
      {metrics.isError && <ErrorBox error={metrics.error} onRetry={() => metrics.refetch()} />}
      {metrics.isSuccess && items.length === 0 && <p className="muted">Noch keine Vorschläge vorhanden.</p>}
      {items.length > 0 && (
        <div className="table-scroll">
          <table className="metrics-table">
            <thead>
              <tr>
                <th scope="col">Art</th>
                {COUNT_LABELS.map(([, label]) => <th key={label} scope="col">{label}</th>)}
                <th scope="col">Annahmequote</th>
                <th scope="col">Rücknahmequote</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={`${m.kind}-${m.generator}`}>
                  <th scope="row">{KIND_LABELS[m.kind] ?? m.kind}</th>
                  {COUNT_LABELS.map(([key]) => <td key={key}>{m.counts[key] ?? 0}</td>)}
                  <td>{rateLabel(m.acceptance_rate)}</td>
                  <td>{rateLabel(m.revert_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
