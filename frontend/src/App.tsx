import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { NotificationProvider } from './contexts/NotificationContext'
import { ConfirmProvider } from './contexts/ConfirmContext'
import { usePermissions } from './hooks/usePermissions'
import NotificationContainer from './components/NotificationContainer'
import Layout from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'

const Login = lazy(() => import('./pages/Login'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ChangePassword = lazy(() => import('./pages/ChangePassword'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Encaissements = lazy(() => import('./pages/Encaissements'))
const Requisitions = lazy(() => import('./pages/Requisitions'))
const RemboursementTransport = lazy(() => import('./pages/RemboursementTransport'))
const Validation = lazy(() => import('./pages/Validation'))
const SortiesFonds = lazy(() => import('./pages/SortiesFonds'))
const Rapports = lazy(() => import('./pages/Rapports'))
const RequisitionPdfSmart = lazy(() => import('./pages/RequisitionPdfSmart'))
const AuditLogs = lazy(() => import('./pages/AuditLogs'))
const ClotureCaisse = lazy(() => import('./pages/ClotureCaisse'))
const Denominations = lazy(() => import('./pages/Denominations'))
const Budget = lazy(() => import('./pages/Budget'))
const ExpertsComptables = lazy(() => import('./pages/ExpertsComptables'))
const ImportHistory = lazy(() => import('./pages/ImportHistory'))
const Settings = lazy(() => import('./pages/Settings'))
const AuditSortie = lazy(() => import('./pages/AuditSortie'))

function LoadingFallback() {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      fontSize: '16px',
      color: '#64748b'
    }}>
      Chargement...
    </div>
  )
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  // Vérifier si l'utilisateur doit changer son mot de passe
  if (user.must_change_password && window.location.pathname !== '/change-password') {
    return <Navigate to="/change-password" />
  }

  return <>{children}</>
}

function ProtectedRoute({ children, permission }: { children: React.ReactNode; permission: string }) {
  const { user, loading: authLoading } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()

  if (authLoading || permissionsLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  if (!hasPermission(permission)) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <h2 style={{ color: '#dc2626', marginBottom: '16px' }}>Accès refusé</h2>
        <p style={{ color: '#64748b', marginBottom: '24px' }}>
          Vous n'avez pas les permissions nécessaires pour accéder à cette page.
        </p>
        <a href="/" style={{ color: '#2563eb', textDecoration: 'underline' }}>
          Retour au tableau de bord
        </a>
      </div>
    )
  }

  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Suspense fallback={<LoadingFallback />}><Login /></Suspense>} />
      <Route path="/forgot-password" element={<Suspense fallback={<LoadingFallback />}><ForgotPassword /></Suspense>} />
      <Route path="/audit/sortie" element={<Suspense fallback={<LoadingFallback />}><AuditSortie /></Suspense>} />
      <Route path="/change-password" element={<PrivateRoute><Suspense fallback={<LoadingFallback />}><ChangePassword required={true} /></Suspense></PrivateRoute>} />
      <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route index element={<Suspense fallback={<LoadingFallback />}><Dashboard /></Suspense>} />
        <Route path="dashboard" element={<Suspense fallback={<LoadingFallback />}><Dashboard /></Suspense>} />
        <Route path="encaissements" element={<ProtectedRoute permission="encaissements"><Suspense fallback={<LoadingFallback />}><Encaissements /></Suspense></ProtectedRoute>} />
        <Route path="requisitions" element={<ProtectedRoute permission="requisitions"><Suspense fallback={<LoadingFallback />}><Requisitions /></Suspense></ProtectedRoute>} />
        <Route path="remboursement-transport" element={<ProtectedRoute permission="requisitions"><Suspense fallback={<LoadingFallback />}><RemboursementTransport /></Suspense></ProtectedRoute>} />
        <Route path="validation" element={<ProtectedRoute permission="validation"><Suspense fallback={<LoadingFallback />}><Validation /></Suspense></ProtectedRoute>} />
        <Route path="sorties-fonds" element={<ProtectedRoute permission="sorties_fonds"><Suspense fallback={<LoadingFallback />}><SortiesFonds /></Suspense></ProtectedRoute>} />
        <Route path="rapports" element={<ProtectedRoute permission="rapports"><Suspense fallback={<LoadingFallback />}><Rapports /></Suspense></ProtectedRoute>} />
        <Route path="requisitions-ocr" element={<ProtectedRoute permission="requisitions"><Suspense fallback={<LoadingFallback />}><RequisitionPdfSmart /></Suspense></ProtectedRoute>} />
        <Route path="audit-logs" element={<ProtectedRoute permission="rapports"><Suspense fallback={<LoadingFallback />}><AuditLogs /></Suspense></ProtectedRoute>} />
        <Route path="cloture-caisse" element={<ProtectedRoute permission="sorties_fonds"><Suspense fallback={<LoadingFallback />}><ClotureCaisse /></Suspense></ProtectedRoute>} />
        <Route path="budget" element={<ProtectedRoute permission="budget"><Suspense fallback={<LoadingFallback />}><Budget /></Suspense></ProtectedRoute>} />
        <Route path="experts-comptables" element={<ProtectedRoute permission="experts_comptables"><Suspense fallback={<LoadingFallback />}><ExpertsComptables /></Suspense></ProtectedRoute>} />
        <Route path="historique-imports" element={<ProtectedRoute permission="settings"><Suspense fallback={<LoadingFallback />}><ImportHistory /></Suspense></ProtectedRoute>} />
        <Route path="settings" element={<ProtectedRoute permission="settings"><Suspense fallback={<LoadingFallback />}><Settings /></Suspense></ProtectedRoute>} />
        <Route path="denominations" element={<ProtectedRoute permission="settings"><Suspense fallback={<LoadingFallback />}><Denominations /></Suspense></ProtectedRoute>} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <NotificationProvider>
            <ConfirmProvider>
              <NotificationContainer />
              <AppRoutes />
            </ConfirmProvider>
          </NotificationProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
