import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import { GuestOnly, RequireAuth } from './auth/guards'
import { CallbackPage } from './pages/auth/CallbackPage'
import { LoginPage } from './pages/auth/LoginPage'
import { ResetPage } from './pages/auth/ResetPage'
import { HomePage } from './pages/HomePage'
import { LegalPage } from './pages/legal/LegalPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { RequestAccessPage } from './pages/RequestAccessPage'
import { AppShell } from './shell/AppShell'

const ChatPage = lazy(() => import('./pages/ChatPage').then((m) => ({ default: m.ChatPage })))
const SettingsLayout = lazy(() => import('./pages/settings/SettingsLayout').then((m) => ({ default: m.SettingsLayout })))

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
      {/* one "Log in or sign up" dialog now: the old pages land on it */}
      <Route path="/signup" element={<ToLogin />} />
      <Route path="/forgot-password" element={<ToLogin />} />
      <Route path="/request-access" element={<RequestAccessPage />} />
      <Route path="/legal/:doc" element={<LegalPage />} />
      <Route path="/reset-password" element={<ResetPage />} />
      <Route path="/auth/callback" element={<CallbackPage />} />
      <Route path="/welcome" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
      <Route path="/settings/:section?" element={<RequireAuth><Suspense fallback={<div className="h-full bg-bg" />}><SettingsLayout /></Suspense></RequireAuth>} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<HomePage />} />
        <Route path="/c/:id" element={<Suspense fallback={null}><ChatPage /></Suspense>} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

function ToLogin() {
  const { search } = useLocation()
  return <Navigate to={`/login${search}`} replace />
}
