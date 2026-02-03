import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import styles from './Login.module.css'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { signIn, user } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      await signIn(email, password)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erreur de connexion'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.loginBox}>
        <div className={styles.header}>
          <img src="/imge_onec.png" alt="ONEC Logo" className={styles.headerLogo} />
          <div className={styles.provincialTitle}>Conseil Provincial de Kinshasa</div>
          <p>Connexion</p>
        </div>

        {!user && (
          <form onSubmit={handleSubmit} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}

            <div className={styles.field}>
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="votre@email.com"
                autoComplete="username"
              />
            </div>

            <div className={styles.field}>
              <label>Mot de passe</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>

            <button type="submit" disabled={loading} className={styles.submitBtn}>
              {loading ? 'Connexion...' : 'Se connecter'}
            </button>
          </form>
        )}

      </div>
    </div>
  )
}
