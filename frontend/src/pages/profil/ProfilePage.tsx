import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { useUsers, type User } from '../../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { useProfile } from '../../app/ProfileContext'
import { Button, TextField } from '../../ui/controls'
import { ErrorBox, Loading } from '../../ui/blocks'
import { Icon } from '../../ui/Icon'

/** Profil wählen – einmal pro Gerät, der Browser merkt sich die Wahl. */
export function ProfilePage() {
  const users = useUsers()
  const { profile, choose } = useProfile()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  function pick(user: User) {
    choose({ id: user.id, name: user.name })
    navigate(from === '/profil' ? '/' : from, { replace: true })
  }

  async function create() {
    if (!name.trim()) {
      setError('Bitte einen Namen eingeben')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const user = await api.anonymous.post<User>('/users', { name: name.trim() })
      await queryClient.invalidateQueries({ queryKey: ['users'] })
      pick(user)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Das hat nicht geklappt.')
    } finally {
      setBusy(false)
    }
  }

  const list = users.data ?? []
  const showForm = adding || (users.isSuccess && list.length === 0)

  return (
    <main className="profile-page">
      <div className="profile-panel">
        <h1>Wer bist du?</h1>
        <p className="muted">Wähle dein Profil. Dieses Gerät merkt sich die Wahl.</p>

        {users.isLoading && <Loading />}
        {users.isError && <ErrorBox error={users.error} onRetry={() => users.refetch()} />}

        {list.length > 0 && (
          <ul className="profile-grid">
            {list.map((user) => (
              <li key={user.id}>
                <button
                  type="button"
                  className={`profile-card${profile?.id === user.id ? ' is-current' : ''}`}
                  onClick={() => pick(user)}
                >
                  <span className="avatar is-large" aria-hidden="true">
                    {user.name.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase()}
                  </span>
                  <strong>{user.name}</strong>
                  {profile?.id === user.id && <small>aktuell</small>}
                </button>
              </li>
            ))}
            {!showForm && (
              <li>
                <button type="button" className="profile-card is-add" onClick={() => setAdding(true)}>
                  <span className="avatar is-large" aria-hidden="true"><Icon name="plus" size={28} /></span>
                  <strong>Neues Profil</strong>
                </button>
              </li>
            )}
          </ul>
        )}

        {showForm && (
          <form
            className="profile-form"
            onSubmit={(e) => {
              e.preventDefault()
              create()
            }}
          >
            <TextField label={list.length ? 'Name des neuen Profils' : 'Dein Name – das erste Profil'} value={name}
              onChange={setName} error={error} autoFocus maxLength={100} placeholder="z. B. Fabian" />
            <div className="profile-form-actions">
              {list.length > 0 && <Button variant="ghost" onClick={() => setAdding(false)}>Abbrechen</Button>}
              <Button variant="primary" type="submit" busy={busy} icon="check">Profil anlegen</Button>
            </div>
          </form>
        )}
      </div>
    </main>
  )
}
