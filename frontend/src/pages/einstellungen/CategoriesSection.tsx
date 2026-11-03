import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useApiMutation, useCategories, type Category } from '../../api/hooks'
import { Button, Checkbox, Segmented, SelectField, TextField } from '../../ui/controls'
import { Confirm, Dialog, useToast } from '../../ui/overlay'
import { Icon } from '../../ui/Icon'
import { useFormErrors } from '../../ui/useFormErrors'
import { FormActions, MasterDetail, Switch } from './MasterDetail'

const AREAS = ['categories', 'transactions', 'budget', 'reports', 'fixed-costs', 'rules'] as const

type CategoryType = Category['type']
const TYPE_OPTIONS: { value: CategoryType; label: string }[] = [
  { value: 'expense', label: 'Ausgaben' },
  { value: 'income', label: 'Einnahmen' },
]

/** Eltern direkt gefolgt von ihren Unterkategorien (alphabetisch, wie vom Backend geliefert). */
function ordered(all: Category[], type: CategoryType): Category[] {
  const ofType = all.filter((c) => c.type === type)
  const ids = new Set(ofType.map((c) => c.id))
  const roots = ofType.filter((c) => c.parent_id === null || !ids.has(c.parent_id))
  return roots.flatMap((r) => [r, ...ofType.filter((c) => c.parent_id === r.id)])
}

export function CategoriesSection() {
  const list = useCategories()
  const toast = useToast()
  const [type, setType] = useState<CategoryType>('expense')
  const all = list.data ?? []
  const items = useMemo(() => (list.data ? ordered(list.data, type) : undefined), [list.data, type])
  const toggle = useApiMutation(
    (item: Category) => api.patch(`/categories/${item.id}`, { active: !item.active }),
    [...AREAS],
  )

  return (
    <MasterDetail<Category>
      title="Kategorien"
      hint={
        <>
          Kategorien sortieren Buchungen und bilden die Auswertungen. Systemkategorien sind fest vorgegeben.
          <span className="settings-filter">
            <Segmented label="Art der Kategorie" value={type} onChange={setType} options={TYPE_OPTIONS} />
          </span>
        </>
      }
      createLabel="Kategorie anlegen"
      items={items}
      isLoading={list.isLoading}
      error={list.error}
      onRetry={() => list.refetch()}
      empty={{ icon: 'list', title: type === 'expense' ? 'Keine Ausgabenkategorien' : 'Keine Einnahmenkategorien', text: 'Lege eine Kategorie an, um Buchungen zu sortieren.' }}
      formTitle={(item) => item?.name ?? 'Neue Kategorie'}
      renderRow={(item) => (
        <>
          <span className={`row-main${item.parent_id ? ' settings-child' : ''}`}>
            <strong>{item.name}</strong>
            <span>
              {item.system_key ? 'Systemkategorie' : item.parent_id ? `unter ${all.find((c) => c.id === item.parent_id)?.name ?? '…'}` : 'Hauptkategorie'}
            </span>
          </span>
          {item.system_key && <span className="row-icon" title="Fest vorgegeben"><Icon name="check" size={22} /></span>}
          <span className={`settings-state${item.active ? ' is-on' : ''}`}>{item.active ? 'aktiv' : 'inaktiv'}</span>
          <Switch
            checked={item.active}
            label={`${item.name} ${item.active ? 'deaktivieren' : 'aktivieren'}`}
            disabled={toggle.isPending || item.system_key !== null}
            onChange={() => toggle.mutate(item, { onError: toast.error })}
          />
        </>
      )}
      renderForm={(item, done) => (
        <CategoryForm key={item?.id ?? `neu-${type}`} item={item} all={all} defaultType={type} done={done} />
      )}
    />
  )
}

function CategoryForm({ item, all, defaultType, done }: { item: Category | null; all: Category[]; defaultType: CategoryType; done: () => void }) {
  const toast = useToast()
  const form = useFormErrors()
  const [name, setName] = useState(item?.name ?? '')
  const [type, setType] = useState<CategoryType>(item?.type ?? defaultType)
  const [parentId, setParentId] = useState(item?.parent_id ? String(item.parent_id) : '')
  const [active, setActive] = useState(item?.active ?? true)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [targetId, setTargetId] = useState('')

  const system = item?.system_key != null
  const hasChildren = item ? all.some((c) => c.parent_id === item.id) : false
  const parents = all.filter((c) => c.type === type && c.parent_id === null && c.id !== item?.id && (c.active || String(c.id) === parentId))
  const targets = all.filter((c) => item && c.type === item.type && c.id !== item.id && c.active && c.system_key === null)

  const save = useApiMutation(
    () => item
      ? api.patch(`/categories/${item.id}`, { name: name.trim(), parent_id: parentId ? Number(parentId) : null, active })
      : api.post('/categories', { name: name.trim(), type, parent_id: parentId ? Number(parentId) : null }),
    [...AREAS],
  )
  const remove = useApiMutation(() => api.delete(`/categories/${item!.id}`), [...AREAS])
  const merge = useApiMutation(() => api.post(`/categories/${item!.id}/merge`, { target_id: Number(targetId) }), [...AREAS])

  if (system) {
    return (
      <div className="settings-form-body">
        <p>Das ist eine Systemkategorie. Der Finanzplaner braucht sie für Umbuchungen, Kreditraten und ungeklärte Buchungen – sie lässt sich nicht ändern, deaktivieren oder löschen.</p>
      </div>
    )
  }

  function submit() {
    if (!form.check({ name: !name.trim() && 'Bitte einen Namen eingeben' })) return
    save.mutate(undefined, {
      onSuccess: () => { toast.ok(item ? 'Kategorie gespeichert' : 'Kategorie angelegt'); done() },
      onError: form.fail,
    })
  }

  function doMerge() {
    if (!targetId) { form.check({ target: 'Bitte eine Zielkategorie wählen' }); return }
    merge.mutate(undefined, {
      onSuccess: () => { toast.ok('Kategorien zusammengeführt'); setMergeOpen(false); done() },
      onError: (e) => { setMergeOpen(false); form.fail(e) },
    })
  }

  return (
    <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <TextField label="Name" value={name} onChange={setName} error={form.errors.name} maxLength={100} autoFocus={!item} />
      {item ? (
        <p className="muted">Art: {item.type === 'expense' ? 'Ausgabe' : 'Einnahme'} (nach dem Anlegen nicht änderbar)</p>
      ) : (
        <Segmented label="Art" value={type} onChange={(v) => { setType(v); setParentId('') }} options={[
          { value: 'expense', label: 'Ausgabe' }, { value: 'income', label: 'Einnahme' },
        ]} />
      )}
      {!hasChildren && (
        <SelectField label="Gehört zu (optional)" value={parentId} onChange={setParentId} placeholder="Hauptkategorie"
          options={parents.map((c) => ({ value: String(c.id), label: c.name }))} error={form.errors.parent_id}
          hint="Unterkategorien erscheinen eingerückt unter ihrer Hauptkategorie." />
      )}
      {item && <Checkbox label="aktiv" checked={active} onChange={setActive} hint="Inaktive Kategorien lassen sich nicht mehr neu vergeben." />}
      {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
      <FormActions
        busy={save.isPending}
        onDelete={item ? () => setConfirmDelete(true) : undefined}
        saveLabel={item ? 'Speichern' : 'Anlegen'}
        extra={item && <Button variant="secondary" onClick={() => setMergeOpen(true)}>Zusammenführen</Button>}
      />
      {item && (
        <>
          <Confirm
            open={confirmDelete}
            title="Kategorie löschen?"
            text={`„${item.name}“ wird gelöscht. Wird sie noch verwendet, bietet der Finanzplaner stattdessen Deaktivieren oder Zusammenführen an.`}
            confirmLabel="Löschen"
            busy={remove.isPending}
            onCancel={() => setConfirmDelete(false)}
            onConfirm={() => remove.mutate(undefined, {
              onSuccess: () => { toast.ok('Kategorie gelöscht'); setConfirmDelete(false); done() },
              onError: (e) => { setConfirmDelete(false); form.fail(e) },
            })}
          />
          <Dialog
            open={mergeOpen}
            onClose={() => setMergeOpen(false)}
            title="In andere Kategorie zusammenführen"
            footer={
              <>
                <button type="button" className="btn btn-ghost" onClick={() => setMergeOpen(false)}>Abbrechen</button>
                <button type="button" className="btn btn-primary" disabled={merge.isPending} onClick={doMerge}>Zusammenführen</button>
              </>
            }
          >
            <div className="settings-form-body">
              <p className="dialog-text">
                Alle Buchungen, Regeln und Fixkosten von „{item.name}“ wandern in die Zielkategorie. „{item.name}“ wird danach gelöscht.
              </p>
              <SelectField label="Zielkategorie" value={targetId} onChange={setTargetId} placeholder="Bitte wählen"
                options={targets.map((c) => ({ value: String(c.id), label: c.name }))} error={form.errors.target} />
            </div>
          </Dialog>
        </>
      )}
    </form>
  )
}
