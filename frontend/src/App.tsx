import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell, MorePage } from './app/AppShell'
import { ProfileProvider } from './app/ProfileContext'
import { ProfilePage } from './pages/profil/ProfilePage'
import { Placeholder } from './pages/Placeholder'
import { Loading } from './ui/blocks'
import { ToastProvider } from './ui/overlay'
import './styles/app.css'

// Das Wanddisplay hat eigene Styles und lädt getrennt von der persönlichen Ansicht
const WallPage = lazy(() => import('./wall/WallPage').then((m) => ({ default: m.WallPage })))
const TransactionsPage = lazy(() => import('./pages/buchungen/TransactionsPage').then((m) => ({ default: m.TransactionsPage })))
const SettingsPage = lazy(() => import('./pages/einstellungen/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const LoansPage = lazy(() => import('./pages/kredite/LoansPage').then((m) => ({ default: m.LoansPage })))
const ImportPage = lazy(() => import('./pages/import/ImportPage').then((m) => ({ default: m.ImportPage })))
const ReviewPage = lazy(() => import('./pages/pruefen/ReviewPage').then((m) => ({ default: m.ReviewPage })))
const ReportsPage = lazy(() => import('./pages/berichte/ReportsPage').then((m) => ({ default: m.ReportsPage })))
const StartPage = lazy(() => import('./pages/start/StartPage').then((m) => ({ default: m.StartPage })))

export function App() {
  return (
    <BrowserRouter>
      <ProfileProvider>
        <ToastProvider>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/wand" element={<WallPage />} />
              <Route path="/profil" element={<ProfilePage />} />
              <Route element={<AppShell />}>
                <Route index element={<StartPage />} />
                <Route path="/buchungen" element={<TransactionsPage />} />
                <Route path="/import" element={<ImportPage />} />
                <Route path="/pruefen" element={<ReviewPage />} />
                <Route path="/kredite" element={<LoansPage />} />
                <Route path="/kredite/:id" element={<LoansPage />} />
                <Route path="/berichte" element={<ReportsPage />} />
                <Route path="/einstellungen" element={<SettingsPage />} />
                <Route path="/einstellungen/:bereich" element={<SettingsPage />} />
                <Route path="/mehr" element={<MorePage />} />
                <Route path="*" element={<Placeholder title="Nicht gefunden" paket={0} />} />
              </Route>
            </Routes>
          </Suspense>
        </ToastProvider>
      </ProfileProvider>
    </BrowserRouter>
  )
}
