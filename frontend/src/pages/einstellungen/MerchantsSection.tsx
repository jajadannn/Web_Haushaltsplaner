import { useState } from 'react'
import { api } from '../../api/client'
import type { Schemas } from '../../api/client'
import { useApiMutation, useProfileQuery } from '../../api/hooks'
import { Button, SelectField, TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail } from './MasterDetail'
import { ALIAS_TYPE_LABELS } from './merchants'

type Merchant = Schemas['MerchantRead']
type Alias = Schemas['AliasRead']
type Contract = Schemas['ContractRead']

/** Anbieter ändern Zuordnungen von Buchungen und Vorschläge. */
const AREAS = ['merchants', 'transactions', 'suggestions'] as const
const KIND_OPTIONS = [
  { value: 'merchant', label: 'Anbieter / Händler' },
  { value: 'payment_provider', label: 'Zahlungsdienstleister (z. B. PayPal)' },
]

export function MerchantsSection() {
  const list = useProfileQuery<Merchant[]>('merchants', '/merchants')
  return (
    <MasterDetail<Merchant>
      title="Anbieter"
      hint="Anbieter fassen Buchungen derselben Gegenpartei zusammen – über IBAN, Referenz oder Name. Das hilft der Erkennung von Fixkosten."
      createLabel="Anbieter anlegen"
      items={list.data}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'bank', title: 'Noch kein Anbieter', text: 'Lege Anbieter an oder merke sie dir direkt in einer Buchung.' }}
      formTitle={(item) => item?.name ?? 'Neuer Anbieter'}
      renderRow={(item) => (
        <>
          <span className="row-icon"><Icon name="bank" size={26} /></span>
          <span className="row-main">
            <strong>{item.name}</strong>
            <span>{item.kind === 'payment_provider' ? 'Zahlungsdienstleister' : 'Anbieter'}</span>
          </span>
        </>
      )}
      renderForm={(item, done) => <MerchantForm key={item?.id ?? 'neu'} item={item} done={done} />}
    />
  )
}

function MerchantForm({ item, done }: { item: Merchant | null; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [kind, setKind] = useState(item?.kind ?? 'merchant')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const save = useApiMutation(
    () => (item ? api.patch(`/merchants/${item.id}`, { name: name.trim(), kind }) : api.post('/merchants', { name: name.trim(), kind })),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/merchants/${item!.id}`), [...AREAS])

  function submit() {
    if (!form.check({ name: !name.trim() && 'Bitte einen Namen eingeben' })) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Anbieter gespeichert' : 'Anbieter angelegt'); if (!item) done() },
      onError: form.fail,
    })
  }

  return (
    <div className="settings-form-body">
      <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} />
        <SelectField label="Art" value={kind} onChange={setKind} options={KIND_OPTIONS} error={form.errors.kind}
          hint={kind === 'payment_provider' ? 'Nur Buchungen mit Vertragsreferenz werden zugeordnet.' : undefined} />
        {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
        <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined}
          saveLabel={item ? 'Speichern' : 'Anlegen'} />
      </form>
      {item && <AliasList merchant={item} />}
      {item && <ContractList merchant={item} />}
      {item && (
        <Confirm
          open={confirmDelete}
          title="Anbieter löschen?"
          text={`„${item.name}“ wird mit allen Merkmalen und Verträgen gelöscht. Buchungen bleiben erhalten.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Anbieter gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </div>
  )
}

function AliasList({ merchant }: { merchant: Merchant }) {
  const toast = useToast()
  const form = useFormErrors()
  const aliases = useProfileQuery<Alias[]>('merchants', `/merchants/${merchant.id}/aliases`)
  const [type, setType] = useState('name')
  const [value, setValue] = useState('')
  const add = useApiMutation(
    () => api.post(`/merchants/${merchant.id}/aliases`, { match_type: type, value: value.trim() }),
    [...AREAS],
  )
  const remove = useApiMutation((id: number) => api.delete(`/merchants/aliases/${id}`), [...AREAS])

  function submit() {
    if (!form.check({ value: !value.trim() && 'Bitte ein Merkmal eingeben' })) return
    add.mutate(undefined, { onSuccess: () => { setValue(''); toast.ok('Merkmal hinzugefügt') }, onError: form.fail })
  }

  return (
    <fieldset className="merchant-block">
      <legend>Merkmale</legend>
      <ul className="merchant-items">
        {(aliases.data ?? []).map((a) => (
          <li key={a.id}>
            <span><strong>{ALIAS_TYPE_LABELS[a.match_type] ?? a.match_type}</strong> {a.value}</span>
            <button type="button" className="icon-btn" aria-label={`Merkmal ${a.value} löschen`}
              onClick={() => remove.mutate(a.id, { onError: toast.error })}><Icon name="trash" size={20} /></button>
          </li>
        ))}
        {aliases.isSuccess && aliases.data.length === 0 && <li className="muted">Noch keine Merkmale.</li>}
      </ul>
      <div className="form-grid">
        <SelectField label="Art" value={type} onChange={setType}
          options={Object.entries(ALIAS_TYPE_LABELS).map(([v, l]) => ({ value: v, label: l }))} />
        <TextField label="Wert" value={value} onChange={setValue} error={form.errors.value} maxLength={200} />
      </div>
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <Button icon="plus" busy={add.isPending} onClick={submit}>Merkmal hinzufügen</Button>
    </fieldset>
  )
}

function ContractList({ merchant }: { merchant: Merchant }) {
  const toast = useToast()
  const form = useFormErrors()
  const contracts = useProfileQuery<Contract[]>('merchants', `/merchants/${merchant.id}/contracts`)
  const [label, setLabel] = useState('')
  const [reference, setReference] = useState('')
  const add = useApiMutation(
    () => api.post(`/merchants/${merchant.id}/contracts`, { label: label.trim(), reference: reference.trim() || null }),
    [...AREAS],
  )
  const remove = useApiMutation((id: number) => api.delete(`/merchants/contracts/${id}`), [...AREAS])

  function submit() {
    if (!form.check({ label: !label.trim() && 'Bitte eine Bezeichnung eingeben' })) return
    add.mutate(undefined, {
      onSuccess: () => { setLabel(''); setReference(''); toast.ok('Vertrag hinzugefügt') },
      onError: form.fail,
    })
  }

  return (
    <fieldset className="merchant-block">
      <legend>Verträge</legend>
      <ul className="merchant-items">
        {(contracts.data ?? []).map((c) => (
          <li key={c.id}>
            <span><strong>{c.label}</strong>{c.reference && <> · {c.reference}</>}</span>
            <button type="button" className="icon-btn" aria-label={`Vertrag ${c.label} löschen`}
              onClick={() => remove.mutate(c.id, { onError: toast.error })}><Icon name="trash" size={20} /></button>
          </li>
        ))}
        {contracts.isSuccess && contracts.data.length === 0 && <li className="muted">Noch keine Verträge.</li>}
      </ul>
      <div className="form-grid">
        <TextField label="Bezeichnung" value={label} onChange={setLabel} error={form.errors.label} maxLength={100} />
        <TextField label="Referenz (optional)" value={reference} onChange={setReference} maxLength={100} />
      </div>
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <Button icon="plus" busy={add.isPending} onClick={submit}>Vertrag hinzufügen</Button>
    </fieldset>
  )
}
