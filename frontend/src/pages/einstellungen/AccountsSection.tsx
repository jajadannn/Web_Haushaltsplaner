import { useState } from 'react'
import { api } from '../../api/client'
import { useAccounts, useApiMutation, useInstitutions, type Account, type Institution } from '../../api/hooks'
import { todayISO } from '../../lib/dates'
import { formatEuro } from '../../lib/money'
import { Checkbox, MoneyField, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon, type IconName } from '../../ui/Icon'
import { Button } from '../../ui/controls'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail } from './MasterDetail'
import { ACCOUNT_TYPE_LABELS, EDITABLE_ACCOUNT_TYPES, type AccountType } from './labels'

const AREAS = ['accounts', 'transactions', 'budget', 'reports'] as const

const TYPE_ICONS: Record<AccountType, IconName> = {
  checking: 'bank', savings: 'coins', cash: 'wallet', credit_card: 'card', loan: 'car',
}

export function AccountsSection() {
  const [showArchived, setShowArchived] = useState(false)
  const list = useAccounts({ include_archived: showArchived })
  const institutions = useInstitutions()
  const bankName = (id: number | null) => institutions.data?.find((i) => i.id === id)?.name

  return (
    <MasterDetail<Account>
      title="Konten"
      hint={
        <>
          Girokonto, Tagesgeld, Bargeld und Kreditkarte. Kreditkonten legst du auf der Seite „Kredite“ an.
          <Checkbox label="Archivierte Konten anzeigen" checked={showArchived} onChange={setShowArchived} />
        </>
      }
      createLabel="Konto anlegen"
      items={list.data}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'wallet', title: 'Noch kein Konto', text: 'Lege dein erstes Konto mit Anfangssaldo an – danach kannst du Buchungen erfassen oder importieren.' }}
      formTitle={(item) => item?.name ?? 'Neues Konto'}
      renderRow={(item) => (
        <>
          <span className="row-icon"><Icon name={TYPE_ICONS[item.type]} size={26} /></span>
          <span className="row-main">
            <strong>{item.name}</strong>
            <span>{[ACCOUNT_TYPE_LABELS[item.type], bankName(item.institution_id)].filter(Boolean).join(' · ')}</span>
          </span>
          {item.archived_at && <span className="settings-state">archiviert</span>}
          <span className="settings-value money">{item.balance != null ? formatEuro(item.balance) : '–'}</span>
        </>
      )}
      renderForm={(item, done) => (
        <AccountForm key={item?.id ?? 'neu'} item={item} institutions={institutions.data ?? []} done={done} />
      )}
    />
  )
}

function AccountForm({ item, institutions, done }: { item: Account | null; institutions: Institution[]; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [type, setType] = useState<AccountType>(item?.type ?? 'checking')
  const [institutionId, setInstitutionId] = useState(item?.institution_id ? String(item.institution_id) : '')
  const [iban, setIban] = useState(item?.iban ?? '')
  const [opening, setOpening] = useState<string | null>(item?.opening_balance ?? '0.00')
  const [openingDate, setOpeningDate] = useState(item?.opening_balance_date ?? todayISO())
  const [ref, setRef] = useState(item?.bank_account_ref ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const archived = item?.archived_at != null
  const body = () => ({
    name: name.trim(),
    type,
    institution_id: institutionId ? Number(institutionId) : null,
    iban: iban.trim() || null,
    opening_balance: opening,
    opening_balance_date: openingDate,
    bank_account_ref: ref.trim() || null,
  })
  const save = useApiMutation(
    () => (item ? api.patch(`/accounts/${item.id}`, body()) : api.post('/accounts', body())),
    [...AREAS],
  )
  const archive = useApiMutation(
    () => api.post(`/accounts/${item!.id}/${archived ? 'unarchive' : 'archive'}`),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/accounts/${item!.id}`), [...AREAS])

  if (item?.type === 'loan') {
    return (
      <div className="settings-form-body">
        <p>
          Dieses Kreditkonto wird auf der Seite „Kredite“ verwaltet. Restschuld, Stichtag und Ratenplan
          gehören dort zusammen.
        </p>
        <p className="muted">
          {ACCOUNT_TYPE_LABELS.loan}{item.balance != null && <> · Saldo {formatEuro(item.balance)}</>}
        </p>
      </div>
    )
  }

  function submit() {
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      opening_balance: opening === null && 'Bitte einen Betrag eingeben',
      opening_balance_date: !openingDate && 'Bitte einen Stichtag angeben',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Konto gespeichert' : 'Konto angelegt'); done() },
      onError: form.fail,
    })
  }

  function toggleArchive() {
    archive.mutate(undefined, {
      onSuccess: () => { toast.ok(archived ? 'Konto wieder aktiv' : 'Konto archiviert'); done() },
      onError: form.fail,
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} />
      <div className="form-grid">
        <SelectField label="Art" value={type} onChange={(v) => setType(v as AccountType)}
          options={EDITABLE_ACCOUNT_TYPES.map((t) => ({ value: t, label: ACCOUNT_TYPE_LABELS[t] }))}
          error={form.errors.type} />
        <SelectField label="Bank (optional)" value={institutionId} onChange={setInstitutionId} placeholder="ohne Bank"
          options={institutions.map((i) => ({ value: String(i.id), label: i.name }))} error={form.errors.institution_id} />
      </div>
      <TextField label="IBAN (optional)" value={iban} onChange={setIban} error={form.errors.iban} maxLength={42}
        hint="Damit ordnet der Import Kontoauszüge dem richtigen Konto zu." />
      <div className="form-grid">
        <MoneyField label="Anfangssaldo" value={opening} onChange={setOpening} allowNegative error={form.errors.opening_balance} />
        <TextField label="Stichtag" type="date" value={openingDate} onChange={setOpeningDate} error={form.errors.opening_balance_date}
          hint="Der Saldo gilt zu Beginn dieses Tages." />
      </div>
      <TextField label="Kontonummer bei der Bank (optional)" value={ref} onChange={setRef} error={form.errors.bank_account_ref} maxLength={64}
        hint="Nur nötig, wenn Auszüge keine IBAN enthalten." />
      {item && <p className="muted">Saldo heute: {item.balance != null ? formatEuro(item.balance) : '–'}{archived && <> · archiviert</>}</p>}
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions
        busy={save.isPending}
        onDelete={item ? () => setConfirmDelete(true) : undefined}
        saveLabel={item ? 'Speichern' : 'Anlegen'}
        extra={item && (
          <Button variant="secondary" busy={archive.isPending} onClick={toggleArchive}>
            {archived ? 'Wieder aktivieren' : 'Archivieren'}
          </Button>
        )}
      />
      {item && (
        <Confirm
          open={confirmDelete}
          title="Konto löschen?"
          text={`„${item.name}“ wird gelöscht. Das geht nur ohne Buchungen – sonst bitte archivieren. Archivierte Konten bleiben in Auswertungen erhalten.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Konto gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </form>
  )
}
