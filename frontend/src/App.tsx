import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { OrganisationSettingsProvider } from './contexts/OrganisationSettingsContext'
import { NotificationProvider, useNotification } from './contexts/NotificationContext'
import { ConfirmProvider } from './contexts/ConfirmContext'
import { usePermissions } from './hooks/usePermissions'
import { isAdminHost } from './utils/tenant'
import NotificationContainer from './components/NotificationContainer'
import Layout from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'
import AccessDeniedState from './components/AccessDeniedState'

const Login = lazy(() => import('./pages/Login'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ChangePassword = lazy(() => import('./pages/ChangePassword'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Encaissements = lazy(() => import('./pages/Encaissements'))
const Requisitions = lazy(() => import('./pages/Requisitions'))
const ExamenDossier = lazy(() => import('./pages/ExamenDossier'))
const DossiersExamen = lazy(() => import('./pages/DossiersExamen'))
const RemboursementTransport = lazy(() => import('./pages/RemboursementTransport'))
const Validation = lazy(() => import('./pages/Validation'))
const SortiesFonds = lazy(() => import('./pages/SortiesFonds'))
const Rapports = lazy(() => import('./pages/Rapports'))
const RequisitionPdfSmart = lazy(() => import('./pages/RequisitionPdfSmart'))
const AuditLogs = lazy(() => import('./pages/AuditLogs'))
const ClotureCaisse = lazy(() => import('./pages/ClotureCaisse'))
const Denominations = lazy(() => import('./pages/Denominations'))
const Budget = lazy(() => import('./pages/Budget'))
const ServiceDashboard = lazy(() => import('./pages/ServiceDashboard'))
const ServicePortal = lazy(() => import('./pages/ServicePortal'))
const ExpertsComptables = lazy(() => import('./pages/ExpertsComptables'))
const Settings = lazy(() => import('./pages/Settings'))
const ImportHistory = lazy(() => import('./pages/ImportHistory'))
const AuditSortie = lazy(() => import('./pages/AuditSortie'))
const OrganisationSettings = lazy(() => import('./pages/OrganisationSettings'))
const SuperAdmin = lazy(() => import('./pages/SuperAdmin'))
const AdminAccessDenied = lazy(() => import('./pages/AdminAccessDenied'))
const GlobalMonitoring = lazy(() => import('./pages/GlobalMonitoring'))
const Signup = lazy(() => import('./pages/Signup'))
const Checkout = lazy(() => import('./pages/Checkout'))

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

function AdminBlocked() {
  const { signOut } = useAuth()

  useEffect(() => {
    void signOut()
  }, [signOut])

  return <Navigate to="/admin-access-denied" replace />
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  if (isAdminHost() && (user.role || '').toLowerCase() !== 'super_admin') {
    return <AdminBlocked />
  }

  // Vérifier si l'utilisateur doit changer son mot de passe
  if (user.must_change_password && window.location.pathname !== '/change-password') {
    return <Navigate to="/change-password" />
  }

  return <>{children}</>
}

function ProtectedRoute({ children, permission }: { children: React.ReactNode; permission: string | string[] }) {
  const { user, loading: authLoading } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()

  if (authLoading || permissionsLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  if (isAdminHost() && (user.role || '').toLowerCase() !== 'super_admin') {
    return <AdminBlocked />
  }

  const permissions = Array.isArray(permission) ? permission : [permission]
  const authorized = permissions.some(p => hasPermission(p))

  if (!authorized) {
    return <AccessDeniedState message="Vous n'avez pas les permissions nécessaires pour accéder à cette page." />
  }

  return <>{children}</>
}

function SuperAdminRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  if (!user) {
    return <Navigate to="/login" />
  }

  if (isAdminHost() && (user.role || '').toLowerCase() !== 'super_admin') {
    return <AdminBlocked />
  }

  if ((user.role || '').toLowerCase() !== 'super_admin') {
    return <AccessDeniedState message="Cette section est réservée au Super Admin." />
  }

  return <>{children}</>
}

function ServiceAwareDashboard() {
  const { user, loading } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()

  if (loading || permissionsLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Chargement...</div>
  }

  const serviceIds =
    user?.service_ids && user.service_ids.length > 0
      ? user.service_ids
      : user?.service_id
        ? [user.service_id]
        : []

  if (hasPermission('dashboard')) {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <Dashboard />
      </Suspense>
    )
  }

  if (serviceIds.length === 1) {
    return <Navigate to={`/services/mon-espace/${serviceIds[0]}`} replace />
  }
  if (serviceIds.length > 1) {
    return <Navigate to="/services" replace />
  }

  return (
    <AccessDeniedState message="Vous n'avez pas les permissions nécessaires pour accéder au tableau de bord." />
  )
}

function SessionExpiryHandler() {
  const navigate = useNavigate()
  const { clearSession } = useAuth()
  const { showWarning } = useNotification()

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ title?: string; message?: string }>).detail || {}
      clearSession()
      showWarning(
        detail.title || 'Session expirée',
        detail.message || 'Votre session a expiré. Veuillez vous reconnecter.'
      )
      navigate('/login', { replace: true, state: { sessionExpired: true } })
    }

    window.addEventListener('session-expired', handler as EventListener)
    return () => {
      window.removeEventListener('session-expired', handler as EventListener)
    }
  }, [clearSession, navigate, showWarning])

  return null
}

function NumberInputWheelGuard() {
  useEffect(() => {
    const handler = (event: WheelEvent) => {
      const activeElement = document.activeElement

      if (!(activeElement instanceof HTMLInputElement) || activeElement.type !== 'number') {
        return
      }

      if (event.target instanceof Node && activeElement.contains(event.target)) {
        event.preventDefault()
        activeElement.blur()
      }
    }

    document.addEventListener('wheel', handler, { passive: false, capture: true })

    return () => {
      document.removeEventListener('wheel', handler, { capture: true })
    }
  }, [])

  return null
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/checkout/:sessionId" element={<Suspense fallback={<LoadingFallback />}><Checkout /></Suspense>} />
      <Route path="/login" element={<Suspense fallback={<LoadingFallback />}><Login /></Suspense>} />
      <Route path="/signup" element={<Suspense fallback={<LoadingFallback />}><Signup /></Suspense>} />
      <Route path="/admin-access-denied" element={<Suspense fallback={<LoadingFallback />}><AdminAccessDenied /></Suspense>} />
      <Route path="/forgot-password" element={<Suspense fallback={<LoadingFallback />}><ForgotPassword /></Suspense>} />
      <Route path="/audit/sortie" element={<Suspense fallback={<LoadingFallback />}><AuditSortie /></Suspense>} />
      <Route path="/change-password" element={<PrivateRoute><Suspense fallback={<LoadingFallback />}><ChangePassword required={true} /></Suspense></PrivateRoute>} />
      <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route index element={<ServiceAwareDashboard />} />
        <Route path="dashboard" element={<ServiceAwareDashboard />} />
        <Route path="services/mon-espace" element={<ProtectedRoute permission="services"><Suspense fallback={<LoadingFallback />}><ServicePortal /></Suspense></ProtectedRoute>} />
        <Route path="services/mon-espace/:serviceId" element={<ProtectedRoute permission="services"><Suspense fallback={<LoadingFallback />}><ServicePortal /></Suspense></ProtectedRoute>} />
        <Route path="encaissements" element={<ProtectedRoute permission="encaissements"><Suspense fallback={<LoadingFallback />}><Encaissements /></Suspense></ProtectedRoute>} />
        <Route path="requisitions" element={<ProtectedRoute permission={['requisitions', 'services']}><Suspense fallback={<LoadingFallback />}><Requisitions /></Suspense></ProtectedRoute>} />
        <Route path="requisitions/examen/:dossierId" element={<ProtectedRoute permission="validation_examens"><Suspense fallback={<LoadingFallback />}><ExamenDossier /></Suspense></ProtectedRoute>} />
        <Route path="validation/examens" element={<ProtectedRoute permission="validation_examens"><Suspense fallback={<LoadingFallback />}><DossiersExamen /></Suspense></ProtectedRoute>} />
        <Route path="remboursement-transport" element={<ProtectedRoute permission={['remboursement_transport', 'services']}><Suspense fallback={<LoadingFallback />}><RemboursementTransport /></Suspense></ProtectedRoute>} />
        <Route path="validation" element={<ProtectedRoute permission="validation"><Suspense fallback={<LoadingFallback />}><Validation /></Suspense></ProtectedRoute>} />
        <Route path="sorties-fonds" element={<ProtectedRoute permission="sorties_fonds"><Suspense fallback={<LoadingFallback />}><SortiesFonds /></Suspense></ProtectedRoute>} />
        <Route path="rapports" element={<ProtectedRoute permission="rapports"><Suspense fallback={<LoadingFallback />}><Rapports /></Suspense></ProtectedRoute>} />
        <Route path="requisitions-ocr" element={<ProtectedRoute permission="requisitions_ocr"><Suspense fallback={<LoadingFallback />}><RequisitionPdfSmart /></Suspense></ProtectedRoute>} />
        <Route path="audit-logs" element={<ProtectedRoute permission="audit_logs"><Suspense fallback={<LoadingFallback />}><AuditLogs /></Suspense></ProtectedRoute>} />
        <Route path="cloture-caisse" element={<ProtectedRoute permission="cloture_caisse"><Suspense fallback={<LoadingFallback />}><ClotureCaisse /></Suspense></ProtectedRoute>} />
        <Route path="budget" element={<ProtectedRoute permission="budget"><Suspense fallback={<LoadingFallback />}><Budget /></Suspense></ProtectedRoute>} />
        <Route path="services" element={<ProtectedRoute permission="services"><Suspense fallback={<LoadingFallback />}><ServiceDashboard /></Suspense></ProtectedRoute>} />
        <Route path="experts-comptables" element={<ProtectedRoute permission="experts_comptables"><Suspense fallback={<LoadingFallback />}><ExpertsComptables /></Suspense></ProtectedRoute>} />
        <Route path="settings" element={<ProtectedRoute permission="settings"><Suspense fallback={<LoadingFallback />}><Settings /></Suspense></ProtectedRoute>} />
        <Route path="historique-imports" element={<ProtectedRoute permission="historique_imports"><Suspense fallback={<LoadingFallback />}><ImportHistory /></Suspense></ProtectedRoute>} />
        <Route path="organisation-settings" element={<ProtectedRoute permission="organisation_settings"><Suspense fallback={<LoadingFallback />}><OrganisationSettings /></Suspense></ProtectedRoute>} />
        <Route path="super-admin" element={<SuperAdminRoute><Suspense fallback={<LoadingFallback />}><SuperAdmin /></Suspense></SuperAdminRoute>} />
        <Route path="global-monitoring" element={<SuperAdminRoute><Suspense fallback={<LoadingFallback />}><GlobalMonitoring /></Suspense></SuperAdminRoute>} />
        <Route path="denominations" element={<ProtectedRoute permission="denominations"><Suspense fallback={<LoadingFallback />}><Denominations /></Suspense></ProtectedRoute>} />
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
              <NumberInputWheelGuard />
              <SessionExpiryHandler />
              <NotificationContainer />
              <OrganisationSettingsProvider>
                <AppRoutes />
              </OrganisationSettingsProvider>
            </ConfirmProvider>
          </NotificationProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
