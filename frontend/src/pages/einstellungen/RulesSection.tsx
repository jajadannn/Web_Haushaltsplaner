import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useApiMutation, useCategories, useRules, type Category, type Rule } from '../../api/hooks'
import type { Schemas } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { Button, Checkbox, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail, Switch } from './MasterDetail'
import { MATCH_FIELD_LABELS, MATCH_TYPE_LABELS } from './labels'

const AREAS = ['rules', 'transactions', 'review', 'budget', 'reports'] as const

type MatchType = Rule['match_type']
type MatchField = Rule['match_field']
type Preview = Schemas['RulePreview']
type ApplyResult = Schemas['ApplyResult']

const label = (r: Rule) => r.name?.trim() || r.pattern

export function RulesSection() {
  const list = useRules()
  const categories = useCategories()
  const toast = useToast()
  const toggle = useApiMutation(
    (item: Rule) => api.patch(`/mapping-rules/${item.id}`, { active: !item.active }),
    [...AREAS],
  )
  const items = useMemo(
    () => (list.data ? [...list.data].sort((a, b) => a.priority - b.priority || a.id - b.id) : undefined),
    [list.data],
  )
  const catName = (id: number) => categories.data?.find((c) => c.id === id)?.name ?? '–'

  return (
    <MasterDetail<Rule>
      title="Regeln"
      hint="Regeln sortieren Buchungen beim Import automatisch in Kategorien. Die Regel mit der kleinsten Priorität zuerst, die erste passende gewinnt."
      createLabel="Regel anlegen"
      items={items}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'list', title: 'Noch keine Regeln', text: 'Eine Regel wie „Rewe“ → Lebensmittel spart dir das Sortieren jeder einzelnen Buchung.' }}
      formTitle={(item) => (item ? label(item) : 'Neue Regel')}
      renderRow={(item) => (
        <>
          <span className="settings-prio" title="Priorität">{item.priority}</span>
          <span className="row-main">
            <strong>{label(item)}</strong>
            <span>
              {MATCH_TYPE_LABELS[item.match_type]} „{item.pattern}“ · {MATCH_FIELD_LABELS[item.match_field]} → {catName(item.target_category_id)}
            </span>
          </span>
          <span className={`settings-state${item.active ? ' is-on' : ''}`}>{item.active ? 'aktiv' : 'aus'}</span>
          <Switch
            checked={item.active}
            label={`Regel ${label(item)} ${item.active ? 'ausschalten' : 'einschalten'}`}
            disabled={toggle.isPending}
            onChange={() => toggle.mutate(item, { onError: toast.error })}
          />
        </>
      )}
      footer={<ApplyRules />}
      renderForm={(item, done) => <RuleForm key={item?.id ?? 'neu'} item={item} categories={categories.data ?? []} done={done} />}
    />
  )
}

function ApplyRules() {
  const toast = useToast()
  const [result, setResult] = useState<ApplyResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const categories = useCategories()
  const name = (id: number | null) => (id === null ? 'ohne Kategorie' : categories.data?.find((c) => c.id === id)?.name ?? '–')

  const dry = useApiMutation(() => api.post<ApplyResult>('/mapping-rules/apply', undefined, { dry_run: true }), [])
  const real = useApiMutation(() => api.post<ApplyResult>('/mapping-rules/apply', undefined, { dry_run: false }), [...AREAS])

  function preview() {
    setError(null)
    dry.mutate(undefined, {
      onSuccess: (r) => { setResult(r as ApplyResult); setOpen(true) },
      onError: (e) => setError((e as Error).message),
    })
  }

  return (
    <div className="settings-apply">
      <Button variant="secondary" icon="refresh" busy={dry.isPending} onClick={preview}>
        Regeln auf ungeprüfte Buchungen anwenden
      </Button>
      {error && <p className="field-error" role="alert">{error}</p>}
      <Confirm
        open={open && result !== null}
        title={result?.affected === 0 ? 'Keine Buchung betroffen' : `${result?.affected} ${result?.affected === 1 ? 'Buchung würde' : 'Buchungen würden'} kategorisiert`}
        text={
          result && result.affected > 0 ? (
            <>
              <p>Manuell bestätigte Buchungen bleiben unberührt. Beispiele:</p>
              <ul className="settings-sample">
                {result.sample.slice(0, 5).map((s) => (
                  <li key={s.transaction_id}>
                    <strong>{s.description}</strong>
                    <span>{shortDate(s.booking_date)} · {name(s.old_category_id)} → {name(s.new_category_id)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : 'Mit den aktuellen Regeln würde sich nichts ändern.'
        }
        confirmLabel={result && result.affected > 0 ? 'Jetzt anwenden' : 'Schließen'}
        danger={false}
        busy={real.isPending}
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          if (!result || result.affected === 0) { setOpen(false); return }
          real.mutate(undefined, {
            onSuccess: (r) => { toast.ok(`${(r as ApplyResult).affected} Buchungen kategorisiert`); setOpen(false) },
            onError: (e) => { setOpen(false); toast.error(e) },
          })
        }}
      />
    </div>
  )
}

function RuleForm({ item, categories, done }: { item: Rule | null; categories: Category[]; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [pattern, setPattern] = useState(item?.pattern ?? '')
  const [matchType, setMatchType] = useState<MatchType>(item?.match_type ?? 'contains')
  const [matchField, setMatchField] = useState<MatchField>(item?.match_field ?? 'any')
  const [caseSensitive, setCaseSensitive] = useState(item?.case_sensitive ?? false)
  const [priority, setPriority] = useState(String(item?.priority ?? 100))
  const [categoryId, setCategoryId] = useState(item ? String(item.target_category_id) : '')
  const [active, setActive] = useState(item?.active ?? true)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [sampleText, setSampleText] = useState('')
  const [sampleParty, setSampleParty] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const body = () => ({
    name: name.trim() || null,
    pattern: pattern.trim(),
    match_type: matchType,
    match_field: matchField,
    case_sensitive: caseSensitive,
    priority: Number(priority),
    target_category_id: Number(categoryId),
    active,
  })
  const save = useApiMutation(
    () => (item ? api.patch(`/mapping-rules/${item.id}`, body()) : api.post('/mapping-rules', body())),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/mapping-rules/${item!.id}`), [...AREAS])
  const test = useApiMutation(
    () => api.post<Preview>('/mapping-rules/preview', { description: sampleText || null, counterparty: sampleParty || null }),
    [],
  )

  const catOptions = categories
    .filter((c) => c.system_key === null && (c.active || String(c.id) === categoryId))
    .map((c) => ({ value: String(c.id), label: `${c.name} (${c.type === 'income' ? 'Einnahme' : 'Ausgabe'})` }))

  function submit() {
    const prio = Number(priority)
    const ok = form.check({
      pattern: pattern.trim().length < 2 && 'Mindestens 2 Zeichen',
      priority: (!Number.isInteger(prio) || prio < 0 || prio > 10000 || priority.trim() === '') && 'Zahl von 0 bis 10000',
      target_category_id: !categoryId && 'Bitte eine Kategorie wählen',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Regel gespeichert' : 'Regel angelegt'); done() },
      onError: form.fail,
    })
  }

  function runTest() {
    setPreviewError(null)
    if (!sampleText.trim() && !sampleParty.trim()) { setPreviewError('Bitte einen Beispieltext eingeben'); return }
    test.mutate(undefined, {
      onSuccess: (r) => setPreview(r as Preview),
      onError: (e) => { setPreview(null); setPreviewError((e as Error).message) },
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name (optional)" value={name} onChange={setName} error={form.errors.name} maxLength={100} placeholder="z. B. Supermarkt" autoFocus={!item} />
      <TextField label="Muster" value={pattern} onChange={setPattern} error={form.errors.pattern} maxLength={200}
        placeholder={matchType === 'regex' ? 'z. B. ^REWE|EDEKA' : 'z. B. Rewe'} />
      <div className="form-grid">
        <SelectField label="Suchart" value={matchType} onChange={(v) => setMatchType(v as MatchType)}
          options={(Object.keys(MATCH_TYPE_LABELS) as MatchType[]).map((k) => ({ value: k, label: MATCH_TYPE_LABELS[k] }))} />
        <SelectField label="Suchen in" value={matchField} onChange={(v) => setMatchField(v as MatchField)}
          options={(Object.keys(MATCH_FIELD_LABELS) as MatchField[]).map((k) => ({ value: k, label: MATCH_FIELD_LABELS[k] }))} />
      </div>
      <SelectField label="Kategorie" value={categoryId} onChange={setCategoryId} placeholder="Bitte wählen"
        options={catOptions} error={form.errors.target_category_id} />
      <div className="form-grid">
        <TextField label="Priorität" type="number" min={0} max={10000} value={priority} onChange={setPriority} error={form.errors.priority}
          hint="Kleinere Zahl gewinnt. Bei Gleichstand die ältere Regel." />
        <div className="settings-checks">
          <Checkbox label="Groß-/Kleinschreibung beachten" checked={caseSensitive} onChange={setCaseSensitive} />
          <Checkbox label="aktiv" checked={active} onChange={setActive} />
        </div>
      </div>

      <fieldset className="settings-test">
        <legend>Testen</legend>
        <TextField label="Beispieltext" value={sampleText} onChange={setSampleText} maxLength={1000}
          placeholder="z. B. REWE SAGT DANKE 1234" />
        <TextField label="Beispiel-Empfänger (optional)" value={sampleParty} onChange={setSampleParty} maxLength={200} />
        <div>
          <Button variant="secondary" icon="search" busy={test.isPending} onClick={runTest}>Regeln prüfen</Button>
        </div>
        {previewError && <p className="field-error" role="alert">{previewError}</p>}
        {preview && (
          <p className="settings-test-result" role="status">
            <Icon name={preview.winner ? 'check' : 'info'} size={20} />
            {preview.winner
              ? <span>Es gewinnt: <strong>{label(preview.winner)}</strong> → {categories.find((c) => c.id === preview.winner!.target_category_id)?.name ?? '–'}{preview.matching.length > 1 && ` (${preview.matching.length} Regeln passen)`}</span>
              : <span>keine Regel greift</span>}
          </p>
        )}
        <p className="muted">Geprüft werden die gespeicherten Regeln, nicht die Änderungen im Formular.</p>
      </fieldset>

      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined} saveLabel={item ? 'Speichern' : 'Anlegen'} />
      {item && (
        <Confirm
          open={confirmDelete}
          title="Regel löschen?"
          text={`„${label(item)}“ wird gelöscht. Bereits kategorisierte Buchungen bleiben unverändert.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Regel gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </form>
  )
}
