import { lazy, Suspense, type ComponentType } from 'react'
import { NavLink, Navigate, useParams } from 'react-router-dom'
import { Loading, PageHeader } from '../../ui/blocks'
import { FixedCostsSection } from './FixedCostsSection'
import './settings.css'

/** Einstellungen (Entwurf B): Bereiche als Reiter, darunter Liste + Formular rechts. */

const section = (load: () => Promise<Record<string, ComponentType>>, name: string) =>
  lazy(() => load().then((m) => ({ default: m[name] })))

const SECTIONS: { slug: string; label: string; Component: ComponentType }[] = [
  { slug: 'profil', label: 'Profil', Component: section(() => import('./ProfileSection'), 'ProfileSection') },
  { slug: 'banken', label: 'Banken', Component: section(() => import('./InstitutionsSection'), 'InstitutionsSection') },
  { slug: 'konten', label: 'Konten', Component: section(() => import('./AccountsSection'), 'AccountsSection') },
  { slug: 'kategorien', label: 'Kategorien', Component: section(() => import('./CategoriesSection'), 'CategoriesSection') },
  { slug: 'fixkosten', label: 'Fixkosten', Component: FixedCostsSection },
  { slug: 'einnahmen', label: 'Einnahmen', Component: section(() => import('./IncomesSection'), 'IncomesSection') },
  { slug: 'anbieter', label: 'Anbieter', Component: section(() => import('./MerchantsSection'), 'MerchantsSection') },
  { slug: 'regeln', label: 'Regeln', Component: section(() => import('./RulesSection'), 'RulesSection') },
  { slug: 'automatik', label: 'Automatik & KI', Component: section(() => import('./AutomationSection'), 'AutomationSection') },
  { slug: 'verlauf', label: 'Verlauf', Component: section(() => import('./HistorySection'), 'HistorySection') },
  { slug: 'importprofile', label: 'Importprofile', Component: section(() => import('./ImportProfilesSection'), 'ImportProfilesSection') },
]

export function SettingsPage() {
  const { bereich } = useParams()
  const current = SECTIONS.find((s) => s.slug === bereich)
  if (!current) return <Navigate to="/einstellungen/fixkosten" replace />
  const { Component } = current
  return (
    <div className="page settings-page">
      <PageHeader title="Einstellungen" />
      <nav className="settings-tabs" aria-label="Bereiche">
        {SECTIONS.map((s) => (
          <NavLink key={s.slug} to={`/einstellungen/${s.slug}`} className="settings-tab">{s.label}</NavLink>
        ))}
      </nav>
      <Suspense fallback={<Loading />}>
        <Component key={current.slug} />
      </Suspense>
    </div>
  )
}
