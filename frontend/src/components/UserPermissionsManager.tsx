import { useState, useEffect } from 'react'
import { adminGetUserMenuPermissions, adminSetUserMenuPermissions } from '../api/admin'
import styles from './UserPermissionsManager.module.css'

interface User {
  id: string
  email: string
  nom: string
  prenom: string
  role: string
}


interface UserPermissionsManagerProps {
  user: User
  onClose: () => void
  onSuccess: () => void
}

const MENU_OPTIONS = [
  { id: 'dashboard', label: 'Tableau de bord', description: 'Voir les statistiques et graphiques' },
  { id: 'encaissements', label: 'Encaissements', description: 'Créer et gérer les encaissements' },
  { id: 'requisitions', label: 'Réquisitions', description: 'Créer et voir les réquisitions' },
  { id: 'validation', label: 'Validation', description: 'Valider et approuver les réquisitions' },
  { id: 'sorties_fonds', label: 'Sorties de fonds', description: 'Effectuer les paiements' },
  { id: 'rapports', label: 'Rapports', description: 'Consulter et exporter les rapports' },
  { id: 'experts_comptables', label: 'Experts-comptables', description: 'Gérer les experts-comptables' },
]

export default function UserPermissionsManager({ user, onClose, onSuccess }: UserPermissionsManagerProps) {
  const [menuPermissions, setMenuPermissions] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadPermissions()
  }, [user.id])

  const loadPermissions = async () => {
    try {
      setLoading(true)

      const res = await adminGetUserMenuPermissions(user.id)
      const permsMap: Record<string, boolean> = {}
      res.menus?.forEach((menu) => {
        permsMap[menu] = true
      })
      setMenuPermissions(permsMap)

    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleMenuPermission = (menuName: string) => {
    setMenuPermissions(prev => ({
      ...prev,
      [menuName]: !prev[menuName]
    }))
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError(null)

      const menus = Object.entries(menuPermissions)
        .filter(([_, canAccess]) => canAccess)
        .map(([menuName]) => menuName)

      await adminSetUserMenuPermissions(user.id, menus)

      onSuccess()
      onClose()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className={styles.overlay}>
        <div className={styles.modal}>
          <p>Chargement...</p>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2>Gestion des droits - {user.nom} {user.prenom}</h2>
          <button onClick={onClose} className={styles.closeBtn}>&times;</button>
        </div>

        <div className={styles.content}>
          {error && (
            <div className={styles.error}>
              {error}
            </div>
          )}

          <div className={styles.info} style={{marginBottom: '20px'}}>
            <strong>Privilèges avancés</strong><br/>
            Les approbateurs de réquisitions sont configurés séparément dans la section Configuration des Paramètres.
            Les administrateurs ont automatiquement accès à tous les menus.
          </div>

          <div className={styles.section}>
            <h3>Accès aux menus</h3>
            <p className={styles.helpText}>
              Cochez les menus auxquels cet utilisateur doit avoir accès. Chaque menu correspond à une section de l'application.
            </p>

            <div className={styles.permissionsTable}>
              <div className={styles.tableHeader}>
                <div className={styles.tableHeaderCell} style={{width: '60px'}}>Accès</div>
                <div className={styles.tableHeaderCell} style={{flex: 1}}>Menu</div>
                <div className={styles.tableHeaderCell} style={{flex: 1.5}}>Description</div>
              </div>
              {MENU_OPTIONS.map(menu => (
                <div key={menu.id} className={styles.tableRow}>
                  <div className={styles.tableCell} style={{width: '60px', justifyContent: 'center'}}>
                    <input
                      type="checkbox"
                      checked={menuPermissions[menu.id] || false}
                      onChange={() => toggleMenuPermission(menu.id)}
                      className={styles.checkbox}
                    />
                  </div>
                  <div className={styles.tableCell} style={{flex: 1}}>
                    <strong>{menu.label}</strong>
                  </div>
                  <div className={styles.tableCell} style={{flex: 1.5, color: '#64748b'}}>
                    {menu.description}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.footer}>
          <button
            onClick={onClose}
            className={styles.cancelBtn}
            disabled={saving}
          >
            Annuler
          </button>
          <button
            onClick={handleSave}
            className={styles.saveBtn}
            disabled={saving}
          >
            {saving ? 'Enregistrement...' : 'Enregistrer'}
          </button>
        </div>
      </div>
    </div>
  )
}
