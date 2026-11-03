import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useReview } from '../api/hooks'
import { Icon, type IconName } from '../ui/Icon'
import { AddEntryProvider, useAddEntry } from './AddEntry'
import { useProfile } from './ProfileContext'

interface NavItem {
  to: string
  label: string
  icon: IconName
  end?: boolean
  mobile?: boolean
}

const NAV: NavItem[] = [
  { to: '/', label: 'Übersicht', icon: 'home', end: true, mobile: true },
  { to: '/buchungen', label: 'Buchungen', icon: 'list', mobile: true },
  { to: '/import', label: 'Import', icon: 'import' },
  { to: '/pruefen', label: 'Prüfen', icon: 'check', mobile: true },
  { to: '/kredite', label: 'Kredite', icon: 'coins', mobile: true },
  { to: '/berichte', label: 'Berichte', icon: 'chart' },
  { to: '/einstellungen', label: 'Einstellungen', icon: 'gear' },
]

function initials(name: string): string {
  return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
}

/** Anzahl offener Prüfungen als Zahl an „Prüfen“. */
function useReviewCount(): number {
  const review = useReview({ status: 'needs_review', limit: 1 })
  return review.data?.total ?? 0
}

function Shell() {
  const { profile } = useProfile()
  const addEntry = useAddEntry()
  const reviewCount = useReviewCount()
  const badge = (item: NavItem) =>
    item.to === '/pruefen' && reviewCount > 0 ? <span className="nav-badge">{reviewCount > 99 ? '99+' : reviewCount}</span> : null

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Navigation">
        <nav>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">
              <Icon name={item.icon} />
              {item.label}
              {badge(item)}
            </NavLink>
          ))}
        </nav>
        <Link to="/profil" className="sidebar-profile">
          <span className="avatar" aria-hidden="true">{initials(profile!.name)}</span>
          <span>
            <strong>{profile!.name}</strong>
            <small>Profil wechseln</small>
          </span>
        </Link>
      </aside>

      <main className="main">
        <Outlet />
      </main>

      <button type="button" className="fab" onClick={() => addEntry.open()} aria-label="Ausgabe hinzufügen">
        <Icon name="plus" size={30} />
      </button>
      <nav className="bottom-nav" aria-label="Navigation">
        {NAV.filter((item) => item.mobile).map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            <Icon name={item.icon} />
            {item.label}
            {badge(item)}
          </NavLink>
        ))}
        <NavLink to="/mehr">
          <Icon name="more" />
          Mehr
        </NavLink>
      </nav>
    </div>
  )
}

/** Rahmen der persönlichen Ansicht; ohne gewähltes Profil geht es zur Profilwahl. */
export function AppShell() {
  const { profile } = useProfile()
  const location = useLocation()
  if (!profile) return <Navigate to="/profil" replace state={{ from: location.pathname }} />
  return (
    <AddEntryProvider>
      <Shell />
    </AddEntryProvider>
  )
}

/** „Mehr“ auf dem Handy: die Bereiche, die nicht in die Daumen-Navigation passen. */
export function MorePage() {
  const { profile } = useProfile()
  return (
    <div className="page">
      <header className="page-header"><div className="page-title"><h1>Mehr</h1></div></header>
      <ul className="rows">
        {NAV.filter((item) => !item.mobile).map((item) => (
          <li key={item.to}>
            <Link to={item.to} className="row-card more-link">
              <span className="row-icon"><Icon name={item.icon} /></span>
              <span className="row-main"><strong>{item.label}</strong></span>
              <Icon name="chevronRight" />
            </Link>
          </li>
        ))}
        <li>
          <Link to="/profil" className="row-card more-link">
            <span className="avatar" aria-hidden="true">{initials(profile?.name ?? '?')}</span>
            <span className="row-main"><strong>{profile?.name}</strong><span>Profil wechseln</span></span>
            <Icon name="chevronRight" />
          </Link>
        </li>
      </ul>
    </div>
  )
}
