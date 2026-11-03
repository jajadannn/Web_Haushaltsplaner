import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useApiMutation, type User } from '../../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { useProfile } from '../../app/ProfileContext'
import { Button, TextField } from '../../ui/controls'
import { useToast } from '../../ui/overlay'
import { useFormErrors } from '../../ui/useFormErrors'

/** Profil: Name ändern. Profile haben kein Passwort (Heimnetz). */
export function ProfileSection() {
  const { profile, choose } = useProfile()
  const toast = useToast()
  const client = useQueryClient()
  const form = useFormErrors()
  const [name, setName] = useState(profile?.name ?? '')

  const save = useApiMutation(
    () => api.patch<User>(`/users/${profile!.id}`, { name: name.trim() }),
    [],
  )

  if (!profile) return null

  function submit() {
    if (!form.check({ name: !name.trim() && 'Bitte einen Namen eingeben' })) return
    save.mutate(undefined, {
      onSuccess: (user) => {
        choose({ id: (user as User).id, name: (user as User).name })
        void client.invalidateQueries({ queryKey: ['users'] })
        toast.ok('Profil gespeichert')
      },
      onError: form.fail,
    })
  }

  return (
    <div className="settings-section">
      <header className="settings-head">
        <div>
          <h2>Profil</h2>
          <p className="muted">Jedes Profil hat eigene Konten, Buchungen und Einstellungen.</p>
        </div>
      </header>
      <section className="tile settings-profile">
        <form className="settings-form-body" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <TextField label="Name des Profils" value={name} onChange={setName} error={form.errors.name} maxLength={100} />
          {form.formError && <p className="field-error" role="alert">{form.formError}</p>}
          <div className="form-actions">
            <Button variant="primary" type="submit" busy={save.isPending}>Speichern</Button>
          </div>
        </form>
        <p className="muted settings-note">
          Profile haben kein Passwort. Der Finanzplaner ist nur im Heimnetz erreichbar.{' '}
          <Link to="/profil">Profil wechseln</Link>
        </p>
      </section>
    </div>
  )
}
