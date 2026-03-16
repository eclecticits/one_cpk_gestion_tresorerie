import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { isAdminHost } from '../utils/tenant'

export default function AdminAccessDenied() {
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const onAdminHost = isAdminHost()

  useEffect(() => {
    if (!onAdminHost) {
      navigate('/login', { replace: true })
      return
    }
    void signOut()
  }, [navigate, onAdminHost, signOut])

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px' }}>
      <div style={{ maxWidth: '520px', textAlign: 'center' }}>
        <h2 style={{ color: '#dc2626', marginBottom: '12px' }}>Accès réservé au Super Admin</h2>
        <p style={{ color: '#64748b', marginBottom: '20px' }}>
          Ce domaine est réservé aux opérations de supervision globale. Merci d’utiliser un compte habilité.
        </p>
        <button
          type="button"
          onClick={() => navigate('/login')}
          style={{
            padding: '10px 16px',
            borderRadius: '10px',
            border: '1px solid #e2e8f0',
            background: '#ffffff',
            cursor: 'pointer',
          }}
        >
          Revenir à la connexion
        </button>
      </div>
    </div>
  )
}
