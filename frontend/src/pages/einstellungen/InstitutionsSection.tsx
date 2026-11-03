import { useState } from 'react'
import { api } from '../../api/client'
import { useAccounts, useApiMutation, useInstitutions, type Institution } from '../../api/hooks'
import { TextField } from '../../ui/controls'
import { Confirm, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail } from './MasterDetail'

const AREAS = ['institutions', 'accounts', 'import-profiles'] as const

export function InstitutionsSection() {
  const list = useInstitutions()
  const accounts = useAccounts({ include_archived: true })
  const count = (id: number) => (accounts.data ?? []).filter((a) => a.institution_id === id).length

  return (
    <MasterDetail<Institution>
      title="Banken"
      hint="Banken ordnen Konten und Importprofile zu."
      createLabel="Bank anlegen"
      items={list.data}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'wallet', title: 'Noch keine Bank', text: 'Lege die Bank an, bei der deine Konten liegen. Sie wird für den Import von Kontoauszügen gebraucht.' }}
      formTitle={(item) => item?.name ?? 'Neue Bank'}
      renderRow={(item) => {
        const n = count(item.id)
        return (
          <>
            <span className="row-icon"><Icon name="wallet" size={26} /></span>
            <span className="row-main">
              <strong>{item.name}</strong>
              <span>{item.bic ?? 'ohne BIC'}</span>
            </span>
            <span className="settings-state is-on">{n === 1 ? '1 Konto' : `${n} Konten`}</span>
          </>
        )
      }}
      renderForm={(item, done) => <InstitutionForm key={item?.id ?? 'neu'} item={item} done={done} />}
    />
  )
}

function InstitutionForm({ item, done }: { item: Institution | null; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [bic, setBic] = useState(item?.bic ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const body = () => ({ name: name.trim(), bic: bic.replace(/\s/g, '').toUpperCase() || null })
  const save = useApiMutation(
    () => (item ? api.patch(`/institutions/${item.id}`, body()) : api.post('/institutions', body())),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/institutions/${item!.id}`), [...AREAS])

  function submit() {
    const cleaned = bic.replace(/\s/g, '').toUpperCase()
    const ok = form.check({
      name: !name.trim() && 'Bitte einen Namen eingeben',
      bic: cleaned && !/^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$/.test(cleaned) && 'BIC hat 8 oder 11 Zeichen, z. B. GENODEF1XYZ',
    })
    if (!ok) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Bank gespeichert' : 'Bank angelegt'); done() },
      onError: form.fail,
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} />
      <TextField label="BIC (optional)" value={bic} onChange={setBic} error={form.errors.bic} maxLength={11}
        hint="Steht auf dem Kontoauszug neben der IBAN." />
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions busy={save.isPending} onDelete={item ? () => setConfirmDelete(true) : undefined} saveLabel={item ? 'Speichern' : 'Anlegen'} />
      {item && (
        <Confirm
          open={confirmDelete}
          title="Bank löschen?"
          text={`„${item.name}“ wird entfernt. Das geht nur, wenn ihr kein Konto mehr zugeordnet ist.`}
          confirmLabel="Löschen"
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => remove.mutate(undefined, {
            onSuccess: () => { toast.ok('Bank gelöscht'); setConfirmDelete(false); done() },
            onError: (e) => { setConfirmDelete(false); form.fail(e) },
          })}
        />
      )}
    </form>
  )
}
