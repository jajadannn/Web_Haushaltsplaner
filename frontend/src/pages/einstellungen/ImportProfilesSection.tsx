import { useState } from 'react'
import { api } from '../../api/client'
import {
  useAccounts, useApiMutation, useImportProfiles, useInstitutions, useWatchFolders,
  type ImportProfile, type WatchFolder,
} from '../../api/hooks'
import { Button, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { EmptyState, ErrorBox, Loading } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail } from './MasterDetail'
import { ProfileDraftWizard } from './ProfileDraftWizard'

const AREAS = ['import-profiles', 'watch-folders'] as const

type Format = ImportProfile['format']
type SignMode = ImportProfile['sign_mode']

const FORMAT_LABELS: Record<Format, string> = { csv: 'CSV', ofx: 'OFX', mt940: 'MT940' }
const SIGN_LABELS: Record<SignMode, string> = {
  signed: 'Eine Betragsspalte mit Vorzeichen',
  debit_credit_columns: 'Getrennte Spalten für Soll und Haben',
  indicator_column: 'Betrag mit Kennzeichen (z. B. S/H)',
}

/** Spalten, die je nach Vorzeichen-Modus Pflicht sind. */
const MAIN_KEYS: Record<SignMode, [string, string][]> = {
  signed: [['amount', 'Spalte Betrag']],
  debit_credit_columns: [['debit', 'Spalte Soll (Ausgaben)'], ['credit', 'Spalte Haben (Einnahmen)']],
  indicator_column: [['amount', 'Spalte Betrag'], ['indicator', 'Spalte Soll/Haben-Kennzeichen']],
}
const COMMON_KEYS: [string, string][] = [
  ['description', 'Spalte Verwendungszweck'],
  ['counterparty', 'Spalte Empfänger / Auftraggeber'],
]
const ADVANCED_KEYS: [string, string][] = [
  ['value_date', 'Spalte Wertstellung'],
  ['counterparty_iban', 'Spalte IBAN der Gegenseite'],
  ['external_id', 'Spalte Bank-Referenz'],
  ['own_account', 'Spalte eigene IBAN'],
  ['currency', 'Spalte Währung'],
  ['status', 'Spalte Status (vorgemerkt / gebucht)'],
]

export function ImportProfilesSection() {
  const list = useImportProfiles()
  const institutions = useInstitutions()
  const bank = (id: number) => institutions.data?.find((i) => i.id === id)?.name ?? '–'

  return (
    <>
      <MasterDetail<ImportProfile>
        title="Importprofile"
        hint="Ein Profil beschreibt, wie die Dateien einer Bank gelesen werden (Spalten, Zahlen- und Datumsformat)."
        createLabel="Profil anlegen"
        items={list.data}
        isLoading={list.isLoading}
        error={list.error}
        onRetry={() => list.refetch()}
        empty={{ icon: 'import', title: 'Noch kein Importprofil', text: 'Lege für jede Bank ein Profil an, damit sich Kontoauszüge als Datei einlesen lassen.' }}
        formTitle={(item) => item?.name ?? 'Neues Importprofil'}
        renderRow={(item) => (
          <>
            <span className="row-icon"><Icon name="import" size={26} /></span>
            <span className="row-main">
              <strong>{item.name}</strong>
              <span>{bank(item.institution_id)} · {FORMAT_LABELS[item.format]}</span>
            </span>
          </>
        )}
        renderForm={(item, done) => <ProfileForm key={item?.id ?? 'neu'} item={item} done={done} />}
      />
      <ProfileDraftWizard />
      <WatchFolders profiles={list.data ?? []} />
    </>
  )
}

// --- Profil-Formular --------------------------------------------------------------

function specToText(spec: unknown): string {
  if (typeof spec === 'string') return spec
  if (Array.isArray(spec)) return spec.join(' + ')
  return ''
}

function ProfileForm({ item, done }: { item: ImportProfile | null; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const institutions = useInstitutions()
  const [name, setName] = useState(item?.name ?? '')
  const [institutionId, setInstitutionId] = useState(item ? String(item.institution_id) : '')
  const [format, setFormat] = useState<Format>(item?.format ?? 'csv')
  const [signMode, setSignMode] = useState<SignMode>(item?.sign_mode ?? 'signed')
  const [delimiter, setDelimiter] = useState(item?.delimiter ?? ';')
  const [encoding, setEncoding] = useState(item?.encoding ?? 'utf-8')
  const [skipRows, setSkipRows] = useState(String(item?.skip_rows ?? 0))
  const [dateFormat, setDateFormat] = useState(item?.date_format ?? '%d.%m.%Y')
  const [decimalSep, setDecimalSep] = useState(item?.decimal_sep ?? ',')
  const [thousandsSep, setThousandsSep] = useState(item?.thousands_sep ?? '.')
  const [debitIndicators, setDebitIndicators] = useState((item?.debit_indicators ?? ['S']).join(', '))
  const [pendingValues, setPendingValues] = useState((item?.pending_values ?? []).join(', '))
  const map = (item?.column_map ?? {}) as Record<string, unknown>
  const [columns, setColumns] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = { booking_date: '', description: '', counterparty: '' }
    for (const [key, spec] of Object.entries(map)) init[key] = specToText(spec)
    return init
  })
  const [confirmDelete, setConfirmDelete] = useState(false)

  const isCsv = format === 'csv'
  const list = (text: string) => text.split(',').map((s) => s.trim()).filter(Boolean)
  const setColumn = (key: string) => (value: string) => setColumns((c) => ({ ...c, [key]: value }))

  function columnMap(): Record<string, unknown> {
    const out: Record<string, unknown> = {}
    // Sonderformen (z. B. {debit, credit} beim Empfänger) bleiben unverändert erhalten
    for (const [key, spec] of Object.entries(map)) {
      if (spec && typeof spec === 'object' && !Array.isArray(spec)) out[key] = spec
    }
    const needed = ['booking_date', ...MAIN_KEYS[signMode].map(([k]) => k), ...COMMON_KEYS.map(([k]) => k), ...ADVANCED_KEYS.map(([k]) => k)]
    for (const key of needed) {
      if (key in out) continue
      const parts = (columns[key] ?? '').split('+').map((s) => s.trim()).filter(Boolean)
      if (parts.length === 1) out[key] = parts[0]
      else if (parts.length > 1) out[key] = parts
    }
    return out
  }

  const csvBody = () => ({
    delimiter, encoding: encoding.trim(), skip_rows: Number(skipRows), column_map: columnMap(),
    date_format: dateFormat, decimal_sep: decimalSep, thousands_sep: thousandsSep, sign_mode: signMode,
    debit_indicators: signMode === 'indicator_column' ? list(debitIndicators) : [],
    pending_values: list(pendingValues),
  })
  const save = useApiMutation(
    () => {
      if (item) return api.patch(`/import-profiles/${item.id}`, { name: name.trim(), ...(isCsv ? csvBody() : {}) })
      return api.post('/import-profiles', { name: name.trim(), institution_id: Number(institutionId), format, ...(isCsv ? csvBody() : {}) })
    },
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/import-profiles/${item!.id}`), [...AREAS])

  function submit() {
    const skip = Number(skipRows)
    const cmap = columnMap()
    const missing = (key: string) => isCsv && !(key in cmap) && 'Bitte den Spaltennamen aus der Datei eintragen'
    const problems: Record<string, string | false> = {
      name: !name.trim() && 'Bitte einen Namen eingeben',
      institution_id: !item && !institutionId && 'Bitte eine Bank wählen',
      booking_date: missing('booking_date'),
      skip_rows: isCsv && (!Number.isInteger(skip) || skip < 0 || skip > 50) && 'Zahl von 0 bis 50',
      thousands_sep: isCsv && decimalSep === thousandsSep && 'Dezimal- und Tausendertrenner müssen sich unterscheiden',
      debit_indicators: isCsv && signMode === 'indicator_column' && list(debitIndicators).length === 0 && 'Mindestens ein Kennzeichen angeben, z. B. S',
    }
    for (const [key] of MAIN_KEYS[signMode]) problems[key] = missing(key)
    if (!form.check(problems)) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Profil gespeichert' : 'Profil angelegt'); done() },
      onError: form.fail,
    })
  }

  const columnField = ([key, text]: [string, string], required = false) => {
    const special = map[key] && typeof map[key] === 'object' && !Array.isArray(map[key])
    return (
      <TextField key={key} label={required ? text : `${text} (optional)`} value={special ? 'je nach Richtung (unverändert)' : columns[key] ?? ''}
        onChange={setColumn(key)} disabled={Boolean(special)} error={form.errors[key]} maxLength={100}
        hint={key === 'description' ? 'Mehrere Spalten mit + verbinden, z. B. Verwendungszweck + Buchungstext' : undefined} />
    )
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item}
        placeholder="z. B. Sparkasse Girokonto" />
      <div className="form-grid">
        <SelectField label="Bank" value={institutionId} onChange={setInstitutionId} placeholder="Bitte wählen" disabled={Boolean(item)}
          options={(institutions.data ?? []).map((i) => ({ value: String(i.id), label: i.name }))} error={form.errors.institution_id}
          hint={item ? 'Nach dem Anlegen fest.' : undefined} />
        <SelectField label="Dateiformat" value={format} onChange={(v) => setFormat(v as Format)} disabled={Boolean(item)}
          options={(Object.keys(FORMAT_LABELS) as Format[]).map((f) => ({ value: f, label: FORMAT_LABELS[f] }))}
          hint={item ? 'Nach dem Anlegen fest.' : undefined} />
      </div>

      {isCsv ? (
        <>
          <SelectField label="Betrag in der Datei" value={signMode} onChange={(v) => setSignMode(v as SignMode)}
            options={(Object.keys(SIGN_LABELS) as SignMode[]).map((m) => ({ value: m, label: SIGN_LABELS[m] }))} />
          <p className="muted">Trage ein, wie die Spalten in der Kopfzeile der Datei heißen.</p>
          {columnField(['booking_date', 'Spalte Buchungsdatum'], true)}
          {MAIN_KEYS[signMode].map((k) => columnField(k, true))}
          {COMMON_KEYS.map((k) => columnField(k))}
          {signMode === 'indicator_column' && (
            <TextField label="Kennzeichen für Ausgaben" value={debitIndicators} onChange={setDebitIndicators}
              error={form.errors.debit_indicators} hint="Mehrere mit Komma trennen, z. B. S, Soll" />
          )}

          <details className="settings-advanced">
            <summary>Erweitert</summary>
            <div className="settings-form-body">
              <div className="form-grid">
                <TextField label="Trennzeichen" value={delimiter} onChange={setDelimiter} maxLength={1} hint="Meist ; oder ," />
                <TextField label="Zeichenkodierung" value={encoding} onChange={setEncoding} maxLength={20} hint="utf-8, cp1252 oder iso-8859-1" error={form.errors.encoding} />
              </div>
              <div className="form-grid">
                <TextField label="Zeilen überspringen" type="number" min={0} max={50} value={skipRows} onChange={setSkipRows} error={form.errors.skip_rows}
                  hint="Vorspann vor der Kopfzeile" />
                <TextField label="Datumsformat" value={dateFormat} onChange={setDateFormat} maxLength={20} error={form.errors.date_format}
                  hint="%d.%m.%Y = 31.01.2026, %Y-%m-%d = 2026-01-31" />
              </div>
              <div className="form-grid">
                <TextField label="Dezimaltrenner" value={decimalSep} onChange={setDecimalSep} maxLength={1} error={form.errors.decimal_sep} />
                <TextField label="Tausendertrenner" value={thousandsSep} onChange={setThousandsSep} maxLength={1} error={form.errors.thousands_sep}
                  hint="Leer lassen, wenn es keinen gibt" />
              </div>
              {ADVANCED_KEYS.map((k) => columnField(k))}
              <TextField label="Status-Werte, die übersprungen werden" value={pendingValues} onChange={setPendingValues}
                hint="Zeilen mit diesen Werten in der Statusspalte gelten als vorgemerkt, z. B. Vorgemerkt" />
            </div>
          </details>
        </>
      ) : (
        <p className="muted">Dateien im Format {FORMAT_LABELS[format]} brauchen keine weiteren Einstellungen.</p>
      )}

      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined} saveLabel={item ? 'Speichern' : 'Anlegen'} />
      {item && (
        <Confirm
          open={confirmDelete}
          title="Importprofil löschen?"
          text={`„${item.name}“ wird gelöscht. Das geht nur, wenn damit noch nichts importiert wurde und kein Watch-Ordner darauf verweist.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Profil gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </form>
  )
}

// --- Watch-Ordner -------------------------------------------------------------------

function WatchFolders({ profiles }: { profiles: ImportProfile[] }) {
  const list = useWatchFolders()
  const accounts = useAccounts()
  const toast = useToast()
  const form = useFormErrors()
  const [subdir, setSubdir] = useState('')
  const [profileId, setProfileId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [toDelete, setToDelete] = useState<WatchFolder | null>(null)

  const create = useApiMutation(
    () => api.post('/watch-folders', {
      subdir: subdir.trim(), import_profile_id: Number(profileId), account_id: accountId ? Number(accountId) : null,
    }),
    [...AREAS],
  )
  const remove = useApiMutation((f: WatchFolder) => api.delete(`/watch-folders/${f.id}`), [...AREAS])
  const profileName = (id: number) => profiles.find((p) => p.id === id)?.name ?? '–'
  const accountName = (id: number | null) => (id === null ? 'Konto aus der Datei' : accounts.data?.find((a) => a.id === id)?.name ?? '–')

  function submit() {
    const ok = form.check({
      subdir: !/^[A-Za-z0-9_-]+$/.test(subdir.trim()) && 'Nur Buchstaben, Ziffern, - und _ (ohne Leerzeichen)',
      import_profile_id: !profileId && 'Bitte ein Profil wählen',
    })
    if (!ok) return
    create.mutate(undefined, {
      onSuccess: () => { toast.ok('Watch-Ordner angelegt'); setSubdir(''); setProfileId(''); setAccountId('') },
      onError: form.fail,
    })
  }

  return (
    <section className="tile settings-watch" aria-labelledby="watch-title">
      <h3 id="watch-title">Watch-Ordner</h3>
      <p className="muted">
        Dateien, die du in <code>imports/inbox/&lt;Ordner&gt;/</code> ablegst, werden automatisch mit dem gewählten Profil importiert.
      </p>
      {list.isLoading && <Loading />}
      {list.error != null && <ErrorBox error={list.error} onRetry={() => list.refetch()} />}
      {list.data && list.data.length === 0 && (
        <EmptyState icon="upload" title="Noch kein Watch-Ordner">Lege einen Ordner an, wenn du Dateien nicht jedes Mal von Hand hochladen willst.</EmptyState>
      )}
      {list.data && list.data.length > 0 && (
        <ul className="rows">
          {list.data.map((f) => (
            <li key={f.id} className="row-card">
              <span className="row-icon"><Icon name="upload" size={26} /></span>
              <span className="row-main">
                <strong>{f.subdir}</strong>
                <span>{profileName(f.import_profile_id)} · {accountName(f.account_id)}</span>
              </span>
              <button type="button" className="icon-btn" aria-label={`Watch-Ordner ${f.subdir} löschen`} onClick={() => setToDelete(f)}>
                <Icon name="trash" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="settings-watch-form" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <TextField label="Ordnername" value={subdir} onChange={setSubdir} error={form.errors.subdir} maxLength={64} placeholder="z. B. sparkasse" />
        <SelectField label="Importprofil" value={profileId} onChange={setProfileId} placeholder="Bitte wählen" error={form.errors.import_profile_id}
          options={profiles.map((p) => ({ value: String(p.id), label: p.name }))} />
        <SelectField label="Konto (optional)" value={accountId} onChange={setAccountId} placeholder="aus der Datei erkennen"
          options={(accounts.data ?? []).map((a) => ({ value: String(a.id), label: a.name }))} />
        <Button variant="primary" icon="plus" type="submit" busy={create.isPending}>Ordner anlegen</Button>
      </form>
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <Confirm
        open={toDelete !== null}
        title="Watch-Ordner löschen?"
        text={toDelete && `Dateien in „${toDelete.subdir}“ werden nicht mehr automatisch importiert. Der Ordner auf der Festplatte bleibt bestehen.`}
        confirmLabel="Löschen"
        busy={remove.isPending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete, {
          onSuccess: () => { toast.ok('Watch-Ordner gelöscht'); setToDelete(null) },
          onError: (e) => { setToDelete(null); toast.error(e) },
        })}
      />
    </section>
  )
}
