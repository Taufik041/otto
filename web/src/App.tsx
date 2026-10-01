import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { GuestOnly, RequireAuth } from './auth/guards'
import { CallbackPage } from './pages/auth/CallbackPage'
import { ForgotPage } from './pages/auth/ForgotPage'
import { LoginPage } from './pages/auth/LoginPage'
import { ResetPage } from './pages/auth/ResetPage'
import { SignupPage } from './pages/auth/SignupPage'
import { ChatPage } from './pages/ChatPage'
import { HomePage } from './pages/HomePage'
import { OnboardingPage } from './pages/OnboardingPage'
import { AppShell } from './shell/AppShell'

const SettingsLayout = lazy(() => import('./pages/settings/SettingsLayout').then((m) => ({ default: m.SettingsLayout })))

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
      <Route path="/signup" element={<GuestOnly><SignupPage /></GuestOnly>} />
      <Route path="/forgot-password" element={<GuestOnly><ForgotPage /></GuestOnly>} />
      <Route path="/reset-password" element={<ResetPage />} />
      <Route path="/auth/callback" element={<CallbackPage />} />
      <Route path="/welcome" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
      <Route path="/settings/:section?" element={<RequireAuth><Suspense fallback={<div className="h-full bg-bg" />}><SettingsLayout /></Suspense></RequireAuth>} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<HomePage />} />
        <Route path="/c/:id" element={<ChatPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
