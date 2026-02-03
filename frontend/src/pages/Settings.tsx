import { useState, useEffect } from 'react'
import {
  adminCreateRequisitionApprover,
  adminCreateRubrique,
  adminCreateUser,
  adminDeleteRequisitionApprover,
  adminDeleteUser,
  adminGetPrintSettings,
  adminGetUserMenuPermissions,
  adminListRequisitionApprovers,
  adminListRubriques,
  adminListUsers,
  adminResetUserPassword,
  adminSavePrintSettings,
  adminSetUserMenuPermissions,
  adminSetUserPassword,
  adminToggleUserStatus,
  adminUpdateRequisitionApprover,
  adminUpdateRubrique,
  adminUpdateUser,
} from '../api/admin'
import type { RequisitionApprover } from '../api/admin'
import { useAuth } from '../contexts/AuthContext'
import { useNotification } from '../contexts/NotificationContext'
import { User, Rubrique } from '../types'
import styles from './Settings.module.css'
import UserRoleManager from '../components/UserRoleManager'
import UserPermissionsManager from '../components/UserPermissionsManager'
import ConfirmModal from '../components/ConfirmModal'

interface PrintSettings {
  id?: string
  organization_name: string
  organization_subtitle: string
  header_text: string
  address: string
  phone: string
  email: string
  website: string
  bank_name: string
  bank_account: string
  mobile_money_name: string
  mobile_money_number: string
  footer_text: string
  show_header_logo: boolean
  show_footer_signature: boolean
  logo_url: string
  stamp_url: string
  signature_name: string
  signature_title: string
  paper_format: string
  compact_header: boolean
}

export default function Settings() {
  const { user } = useAuth()
  const { showSuccess, showError, showWarning } = useNotification()
  const [users, setUsers] = useState<User[]>([])
  const [rubriques, setRubriques] = useState<Rubrique[]>([])
  const [printSettings, setPrintSettings] = useState<PrintSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [showUserForm, setShowUserForm] = useState(false)
  const [showRubriqueForm, setShowRubriqueForm] = useState(false)
  const [savingPrintSettings, setSavingPrintSettings] = useState(false)
  const [selectedUserForPermissions, setSelectedUserForPermissions] = useState<User | null>(null)
  const [approvers, setApprovers] = useState<RequisitionApprover[]>([])
  const [showApproverForm, setShowApproverForm] = useState(false)
  const [selectedApproverId, setSelectedApproverId] = useState('')
  const [expandedSection, setExpandedSection] = useState<string>('users')
  const [showEditForm, setShowEditForm] = useState(false)
  const [confirmResetPassword, setConfirmResetPassword] = useState<{ show: boolean; user: User | null }>({ show: false, user: null })

  const [userForm, setUserForm] = useState({
    email: '',
    nom: '',
    prenom: '',
    role: 'reception',
  })

  const [editUserForm, setEditUserForm] = useState({
    id: '',
    email: '',
    password: '',
    nom: '',
    prenom: '',
    role: 'reception',
  })

  const [newUserPermissions, setNewUserPermissions] = useState<Record<string, boolean>>({
    dashboard: true,
  })

  const [editUserPermissions, setEditUserPermissions] = useState<Record<string, boolean>>({
    dashboard: true,
  })

  const [rubriqueForm, setRubriqueForm] = useState({
    code: '',
    libelle: '',
    description: '',
  })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)

      const usersData = await adminListUsers()
      const rubriquesData = await adminListRubriques()
      const printSettingsRes = await adminGetPrintSettings()
      const approversData = await adminListRequisitionApprovers()

      setUsers(usersData)
      setRubriques(rubriquesData)
      setPrintSettings(printSettingsRes.data)
      setApprovers(approversData)
    } catch (error) {
      console.error('Error loading data:', error)
      showError('Erreur de chargement', 'Impossible de charger les paramètres. Veuillez réessayer.')
    } finally {
      setLoading(false)
    }
  }

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      const created = await adminCreateUser({
        email: userForm.email,
        nom: userForm.nom,
        prenom: userForm.prenom,
        role: userForm.role,
      })

      const menus = Object.entries(newUserPermissions)
        .filter(([_, canAccess]) => canAccess)
        .map(([menuName]) => menuName)

      await adminSetUserMenuPermissions(created.id, menus)

      showSuccess(
        'Utilisateur créé avec succès',
        `${userForm.prenom} ${userForm.nom} a été ajouté au système. Mot de passe par défaut : ONECCPK (à changer à la première connexion).`
      )

      setShowUserForm(false)
      setUserForm({
        email: '',
        nom: '',
        prenom: '',
        role: 'reception',
      })
      setNewUserPermissions({ dashboard: true })
      loadData()
    } catch (error: any) {
      console.error('Error creating user:', error)

      if (error?.status === 409) {
        showError(
          'Compte déjà existant',
          `L'adresse email "${userForm.email}" est déjà utilisée dans le système. Veuillez utiliser une autre adresse email.`
        )
        return
      }

      showError(
        'Erreur de création',
        error.message || 'Une erreur est survenue lors de la création de l\'utilisateur. Veuillez réessayer.'
      )
    }
  }

  const toggleNewUserPermission = (menuName: string) => {
    setNewUserPermissions(prev => ({
      ...prev,
      [menuName]: !prev[menuName]
    }))
  }

  const toggleEditUserPermission = (menuName: string) => {
    setEditUserPermissions(prev => ({
      ...prev,
      [menuName]: !prev[menuName]
    }))
  }

  const MENU_OPTIONS = [
    { id: 'dashboard', label: 'Tableau de bord' },
    { id: 'encaissements', label: 'Encaissements' },
    { id: 'requisitions', label: 'Réquisitions' },
    { id: 'sorties_fonds', label: 'Sorties de fonds' },
    { id: 'rapports', label: 'Rapports' },
    { id: 'experts_comptables', label: 'Experts-comptables' },
  ]

  const handleCreateRubrique = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      await adminCreateRubrique({
        code: rubriqueForm.code,
        libelle: rubriqueForm.libelle,
        description: rubriqueForm.description || undefined,
      })

      showSuccess(
        'Rubrique créée avec succès',
        `La rubrique "${rubriqueForm.code}" a été ajoutée et sera disponible lors de la création de réquisitions.`
      )
      setShowRubriqueForm(false)
      setRubriqueForm({
        code: '',
        libelle: '',
        description: '',
      })
      loadData()
    } catch (error: any) {
      console.error('Error creating rubrique:', error)
      if (error?.status === 409) {
        showError(
          'Code existant',
          'Ce code de rubrique existe déjà. Veuillez utiliser un code différent.'
        )
        return
      }
      showError(
        'Erreur de création',
        error.message || 'Une erreur est survenue lors de la création de la rubrique.'
      )
    }
  }

  const toggleRubrique = async (id: string, active: boolean) => {
    try {
      await adminUpdateRubrique(id, { active: !active })

      showSuccess(
        'Statut modifié',
        `La rubrique a été ${!active ? 'activée' : 'désactivée'} avec succès.`
      )
      loadData()
    } catch (error: any) {
      console.error('Error toggling rubrique:', error)
      showError(
        'Erreur de mise à jour',
        error.message || 'Impossible de modifier le statut de la rubrique.'
      )
    }
  }

  const handleAddApprover = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedApproverId) {
      showWarning(
        'Utilisateur non sélectionné',
        'Veuillez sélectionner un utilisateur dans la liste.'
      )
      return
    }

    try {
      await adminCreateRequisitionApprover({
        user_id: selectedApproverId,
        active: true,
      })

      showSuccess(
        'Approbateur ajouté',
        'L\'utilisateur a été ajouté à la liste des approbateurs et pourra maintenant approuver les réquisitions.'
      )
      setShowApproverForm(false)
      setSelectedApproverId('')
      loadData()
    } catch (error: any) {
      console.error('Error adding approver:', error)
      if (error?.status === 409) {
        showWarning(
          'Déjà approbateur',
          'Cet utilisateur est déjà dans la liste des approbateurs.'
        )
        return
      }
      showError(
        'Erreur d\'ajout',
        error.message || 'Une erreur est survenue lors de l\'ajout de l\'approbateur.'
      )
    }
  }

  const toggleApprover = async (id: string, active: boolean) => {
    try {
      await adminUpdateRequisitionApprover(id, { active: !active })

      showSuccess(
        'Statut modifié',
        `L'approbateur a été ${!active ? 'activé' : 'désactivé'} avec succès.`
      )
      loadData()
    } catch (error: any) {
      console.error('Error toggling approver:', error)
      showError(
        'Erreur de mise à jour',
        error.message || 'Impossible de modifier le statut de l\'approbateur.'
      )
    }
  }

  const removeApprover = async (id: string) => {
    if (!confirm('Êtes-vous sûr de vouloir retirer cet approbateur de la liste ?\n\nIl ne pourra plus approuver de réquisitions.')) return

    try {
      await adminDeleteRequisitionApprover(id)

      showSuccess(
        'Approbateur retiré',
        'L\'utilisateur a été retiré de la liste des approbateurs.'
      )
      loadData()
    } catch (error: any) {
      console.error('Error removing approver:', error)
      showError(
        'Erreur de suppression',
        error.message || 'Impossible de retirer l\'approbateur.'
      )
    }
  }

  const availableUsersForApprover = users.filter(
    u => !approvers.some(a => a.user_id === u.id)
  )

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? '' : section)
  }

  const toggleUserStatus = async (userId: string, currentStatus: boolean) => {
    if (userId === user?.id) {
      showWarning(
        'Action non autorisée',
        'Vous ne pouvez pas désactiver votre propre compte.'
      )
      return
    }

    const targetUser = users.find(u => u.id === userId)
    const userName = targetUser ? `${targetUser.prenom} ${targetUser.nom}` : 'cet utilisateur'

    const confirmMessage = currentStatus
      ? `Êtes-vous sûr de vouloir désactiver le compte de ${userName} ?\n\nL'utilisateur ne pourra plus se connecter.`
      : `Êtes-vous sûr de vouloir réactiver le compte de ${userName} ?\n\nL'utilisateur pourra à nouveau se connecter et utiliser l'application.`

    if (!confirm(confirmMessage)) {
      return
    }

    try {
      await adminToggleUserStatus(userId, currentStatus)

      showSuccess(
        currentStatus ? 'Compte désactivé' : 'Compte activé',
        currentStatus
          ? `Le compte de ${userName} a été désactivé. L'utilisateur ne peut plus se connecter.`
          : `Le compte de ${userName} a été réactivé. L'utilisateur peut maintenant se connecter.`
      )
      loadData()
    } catch (error: any) {
      console.error('Error toggling user status:', error)
      showError(
        'Erreur de modification',
        error.message || 'Impossible de modifier le statut de l\'utilisateur. Veuillez réessayer.'
      )
    }
  }

  const handleDeleteUser = async (userId: string) => {
    if (userId === user?.id) {
      showWarning(
        'Action non autorisée',
        'Vous ne pouvez pas supprimer votre propre compte.'
      )
      return
    }

    const targetUser = users.find(u => u.id === userId)
    const userName = targetUser ? `${targetUser.prenom} ${targetUser.nom}` : 'cet utilisateur'

    const confirmMessage = `Êtes-vous sûr de vouloir supprimer définitivement le compte de ${userName} ?\n\nCette action est irréversible.`

    if (!confirm(confirmMessage)) {
      return
    }

    try {
      await adminDeleteUser(userId)

      showSuccess(
        'Utilisateur supprimé',
        `Le compte de ${userName} a été supprimé avec succès.`
      )
      loadData()
    } catch (error: any) {
      console.error('Error deleting user:', error)
      showError(
        'Erreur de suppression',
        error.message || 'Impossible de supprimer l\'utilisateur. Veuillez réessayer.'
      )
    }
  }

  const handleEditUser = async (userToEdit: User) => {
    setEditUserForm({
      id: userToEdit.id,
      email: userToEdit.email,
      password: '',
      nom: userToEdit.nom,
      prenom: userToEdit.prenom,
      role: userToEdit.role,
    })

    try {
      const res = await adminGetUserMenuPermissions(userToEdit.id)
      const permissions: Record<string, boolean> = { dashboard: false }
      res.menus?.forEach((m) => {
        permissions[m] = true
      })
      setEditUserPermissions(permissions)
    } catch (error: any) {
      console.error('Error loading user permissions:', error)
      setEditUserPermissions({ dashboard: false })
    }

    setShowEditForm(true)
  }

  const handleResetPassword = async (userId: string) => {
    const targetUser = users.find(u => u.id === userId)
    if (!targetUser) return

    if (userId === user?.id) {
      showWarning(
        'Action non autorisée',
        'Vous ne pouvez pas réinitialiser votre propre mot de passe. Utilisez la fonction "Changer mon mot de passe".'
      )
      return
    }

    setConfirmResetPassword({ show: true, user: targetUser })
  }

  const executeResetPassword = async () => {
    const targetUser = confirmResetPassword.user
    if (!targetUser) return

    setConfirmResetPassword({ show: false, user: null })

    try {
      await adminResetUserPassword(targetUser.id)

      showSuccess(
        'Mot de passe réinitialisé',
        `Le mot de passe de ${targetUser.prenom} ${targetUser.nom} a été réinitialisé à ONECCPK. L'utilisateur devra le changer à la prochaine connexion.`
      )
      loadData()
    } catch (error: any) {
      console.error('Reset password error:', error)
      showError(
        'Erreur de réinitialisation',
        error.message || 'Impossible de réinitialiser le mot de passe. Veuillez réessayer.'
      )
    }
  }

  const handleUpdateUser = async (e: React.FormEvent) => {
    e.preventDefault()

    if (editUserForm.id === user?.id && editUserForm.role !== user.role) {
      showWarning(
        'Action non autorisée',
        'Vous ne pouvez pas modifier votre propre rôle.'
      )
      return
    }

    try {
      await adminUpdateUser(editUserForm.id, {
        email: editUserForm.email,
        nom: editUserForm.nom,
        prenom: editUserForm.prenom,
        role: editUserForm.role,
      })

      if (editUserForm.password && editUserForm.password.length >= 6) {
        await adminSetUserPassword(editUserForm.id, editUserForm.password, false)
      }

      const menus = Object.entries(editUserPermissions)
        .filter(([_, canAccess]) => canAccess)
        .map(([menuName]) => menuName)

      await adminSetUserMenuPermissions(editUserForm.id, menus)

      showSuccess(
        'Utilisateur modifié',
        `Les informations de ${editUserForm.prenom} ${editUserForm.nom} ont été mises à jour avec succès.`
      )
      setShowEditForm(false)
      setEditUserForm({
        id: '',
        email: '',
        password: '',
        nom: '',
        prenom: '',
        role: 'reception',
      })
      setEditUserPermissions({ dashboard: true })
      loadData()
    } catch (error: any) {
      console.error('Error updating user:', error)
      showError(
        'Erreur de modification',
        error.message || 'Une erreur est survenue lors de la modification de l\'utilisateur. Veuillez réessayer.'
      )
    }
  }

  const handleSavePrintSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!printSettings) return

    setSavingPrintSettings(true)
    try {
      const { id, ...payload } = printSettings
      await adminSavePrintSettings(payload)

      showSuccess(
        'Paramètres sauvegardés',
        'Les paramètres d\'impression ont été enregistrés et seront appliqués lors de la prochaine impression.'
      )
      loadData()
    } catch (error: any) {
      console.error('Error saving print settings:', error)
      showError(
        'Erreur de sauvegarde',
        error.message || 'Impossible de sauvegarder les paramètres d\'impression. Veuillez réessayer.'
      )
    } finally {
      setSavingPrintSettings(false)
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <h1>Paramètres</h1>

      <div className={styles.accordion}>
        <div className={styles.accordionItem}>
          <button
            className={`${styles.accordionHeader} ${expandedSection === 'users' ? styles.active : ''}`}
            onClick={() => toggleSection('users')}
          >
            <span className={styles.accordionIcon}>{expandedSection === 'users' ? '▼' : '▶'}</span>
            <span className={styles.accordionTitle}>Sécurité & Utilisateurs</span>
            <span className={styles.accordionBadge}>{users.length} utilisateurs</span>
          </button>
          {expandedSection === 'users' && (
            <div className={styles.accordionContent}>
              <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Utilisateurs</h2>
          <button onClick={() => setShowUserForm(true)} className={styles.primaryBtn}>
            + Nouvel utilisateur
          </button>
        </div>

        {showEditForm && (
          <div className={styles.formCard}>
            <h3>Modifier l'utilisateur</h3>
            <form onSubmit={handleUpdateUser} className={styles.form}>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Prénom *</label>
                  <input
                    type="text"
                    value={editUserForm.prenom}
                    onChange={(e) => setEditUserForm({ ...editUserForm, prenom: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.field}>
                  <label>Nom *</label>
                  <input
                    type="text"
                    value={editUserForm.nom}
                    onChange={(e) => setEditUserForm({ ...editUserForm, nom: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.field}>
                <label>Email *</label>
                <input
                  type="email"
                  value={editUserForm.email}
                  onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                  required
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Nouveau mot de passe</label>
                  <input
                    type="password"
                    value={editUserForm.password}
                    onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                    minLength={6}
                    placeholder="Laisser vide pour ne pas modifier"
                  />
                  <small style={{color: '#6b7280', fontSize: '12px'}}>
                    Laisser vide si vous ne voulez pas changer le mot de passe
                  </small>
                </div>
                <div className={styles.field}>
                  <label>Rôle *</label>
                  <select
                    value={editUserForm.role}
                    onChange={(e) => setEditUserForm({ ...editUserForm, role: e.target.value })}
                    required
                  >
                    <option value="reception">Réception</option>
                    <option value="tresorerie">Trésorerie</option>
                    <option value="rapporteur">Rapporteur</option>
                    <option value="secretariat">Secrétariat</option>
                    <option value="comptabilite">Comptabilité</option>
                    <option value="admin">Administrateur</option>
                  </select>
                </div>
              </div>

              <div className={styles.field}>
                <label>Droits d'accès</label>
                <div className={styles.permissionsList}>
                  {MENU_OPTIONS.map(menu => (
                    <label key={menu.id} className={styles.permissionItem}>
                      <input
                        type="checkbox"
                        checked={editUserPermissions[menu.id] || false}
                        onChange={() => toggleEditUserPermission(menu.id)}
                      />
                      <span>{menu.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => {
                  setShowEditForm(false)
                  setEditUserPermissions({ dashboard: true })
                }} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Enregistrer les modifications
                </button>
              </div>
            </form>
          </div>
        )}

        {showUserForm && (
          <div className={styles.formCard}>
            <h3>Créer un utilisateur</h3>
            <form onSubmit={handleCreateUser} className={styles.form}>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Prénom *</label>
                  <input
                    type="text"
                    value={userForm.prenom}
                    onChange={(e) => setUserForm({ ...userForm, prenom: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.field}>
                  <label>Nom *</label>
                  <input
                    type="text"
                    value={userForm.nom}
                    onChange={(e) => setUserForm({ ...userForm, nom: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Email *</label>
                  <input
                    type="email"
                    value={userForm.email}
                    onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
                    required
                  />
                </div>
                <div className={styles.field}>
                  <label>Rôle *</label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                    required
                  >
                    <option value="reception">Réception</option>
                    <option value="tresorerie">Trésorerie</option>
                    <option value="rapporteur">Rapporteur</option>
                    <option value="secretariat">Secrétariat</option>
                    <option value="comptabilite">Comptabilité</option>
                    <option value="admin">Administrateur</option>
                  </select>
                </div>
              </div>

              <div className={styles.infoBox} style={{marginBottom: '16px', padding: '12px', background: '#fef3c7', border: '1px solid #fbbf24', borderRadius: '8px'}}>
                <p style={{margin: 0, fontSize: '13px', color: '#78350f'}}>
                  <strong>Mot de passe par défaut :</strong> ONECCPK - L'utilisateur devra le changer à la première connexion.
                </p>
              </div>

              <div className={styles.field}>
                <label>Droits d'accès</label>
                <div className={styles.permissionsList}>
                  {MENU_OPTIONS.map(menu => (
                    <label key={menu.id} className={styles.permissionItem}>
                      <input
                        type="checkbox"
                        checked={newUserPermissions[menu.id] || false}
                        onChange={() => toggleNewUserPermission(menu.id)}
                      />
                      <span>{menu.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => {
                  setShowUserForm(false)
                  setNewUserPermissions({ dashboard: true })
                }} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Créer
                </button>
              </div>
            </form>
          </div>
        )}

        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Email</th>
                <th>Rôle</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td><strong>{user.prenom} {user.nom}</strong></td>
                  <td>{user.email}</td>
                  <td><span className={styles.badge}>{user.role}</span></td>
                  <td>
                    <span className={user.active ? styles.activeStatus : styles.inactiveStatus}>
                      {user.active ? 'Actif' : 'Inactif'}
                    </span>
                  </td>
                  <td>
                    <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
                      <button
                        onClick={() => handleEditUser(user)}
                        className={styles.actionBtn}
                        style={{background: '#dbeafe', color: '#1e40af'}}
                        title="Modifier l'utilisateur"
                      >
                        Modifier
                      </button>
                      <button
                        onClick={() => handleResetPassword(user.id)}
                        className={styles.actionBtn}
                        style={{background: '#fef3c7', color: '#92400e'}}
                        title="Réinitialiser le mot de passe"
                      >
                        Réinitialiser MDP
                      </button>
                      <button
                        onClick={() => toggleUserStatus(user.id, user.active)}
                        className={styles.actionBtn}
                        style={{
                          background: user.active ? '#fee2e2' : '#d1fae5',
                          color: user.active ? '#dc2626' : '#059669'
                        }}
                        title={user.active ? 'Désactiver l\'utilisateur' : 'Activer l\'utilisateur'}
                      >
                        {user.active ? 'Désactiver' : 'Activer'}
                      </button>
                      <button
                        onClick={() => handleDeleteUser(user.id)}
                        className={styles.actionBtn}
                        style={{background: '#fee2e2', color: '#991b1b', fontWeight: '600'}}
                        title="Supprimer l'utilisateur définitivement"
                      >
                        Supprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

              {selectedUserForPermissions && (
                <UserPermissionsManager
                  user={selectedUserForPermissions}
                  onClose={() => setSelectedUserForPermissions(null)}
                  onSuccess={() => {
                    setSelectedUserForPermissions(null)
                    loadData()
                  }}
                />
              )}
            </div>
          )}
        </div>

        <div className={styles.accordionItem}>
          <button
            className={`${styles.accordionHeader} ${expandedSection === 'config' ? styles.active : ''}`}
            onClick={() => toggleSection('config')}
          >
            <span className={styles.accordionIcon}>{expandedSection === 'config' ? '▼' : '▶'}</span>
            <span className={styles.accordionTitle}>Configuration</span>
            <span className={styles.accordionBadge}>{approvers.length} approbateurs · {rubriques.length} rubriques</span>
          </button>
          {expandedSection === 'config' && (
            <div className={styles.accordionContent}>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Approbateurs de réquisitions</h2>
          <button onClick={() => setShowApproverForm(true)} className={styles.primaryBtn}>
            + Ajouter un approbateur
          </button>
        </div>

        <div className={styles.infoBox} style={{marginBottom: '20px', padding: '15px', background: '#eff6ff', borderLeft: '4px solid #3b82f6', borderRadius: '4px'}}>
          <p style={{margin: 0, fontSize: '14px', color: '#1e40af'}}>
            <strong>Important:</strong> Les approbateurs peuvent valider les réquisitions. Un utilisateur ne peut pas approuver sa propre réquisition.
          </p>
        </div>

        {showApproverForm && (
          <div className={styles.formCard}>
            <h3>Ajouter un approbateur</h3>
            <form onSubmit={handleAddApprover} className={styles.form}>
              <div className={styles.field}>
                <label>Sélectionner un utilisateur *</label>
                <select
                  value={selectedApproverId}
                  onChange={(e) => setSelectedApproverId(e.target.value)}
                  required
                >
                  <option value="">Choisir...</option>
                  {availableUsersForApprover.map(u => (
                    <option key={u.id} value={u.id}>
                      {u.prenom} {u.nom} ({u.email}) - {u.role}
                    </option>
                  ))}
                </select>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => {
                  setShowApproverForm(false)
                  setSelectedApproverId('')
                }} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Ajouter
                </button>
              </div>
            </form>
          </div>
        )}

        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Email</th>
                <th>Rôle</th>
                <th>Statut</th>
                <th>Ajouté le</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {approvers.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{textAlign: 'center', padding: '30px', color: '#9ca3af'}}>
                    Aucun approbateur configuré
                  </td>
                </tr>
              ) : (
                approvers.map((approver) => (
                  <tr key={approver.id}>
                    <td><strong>{approver.user?.prenom} {approver.user?.nom}</strong></td>
                    <td>{approver.user?.email}</td>
                    <td>
                      <span className={styles.badge}>
                        {users.find(u => u.id === approver.user_id)?.role}
                      </span>
                    </td>
                    <td>
                      <span className={approver.active ? styles.activeStatus : styles.inactiveStatus}>
                        {approver.active ? 'Actif' : 'Inactif'}
                      </span>
                    </td>
                    <td>{new Date(approver.added_at).toLocaleDateString('fr-FR')}</td>
                    <td>
                      <div style={{display: 'flex', gap: '8px'}}>
                        <button
                          onClick={() => toggleApprover(approver.id, approver.active)}
                          className={styles.actionBtn}
                        >
                          {approver.active ? 'Désactiver' : 'Activer'}
                        </button>
                        <button
                          onClick={() => removeApprover(approver.id)}
                          className={styles.actionBtn}
                          style={{background: '#fee2e2', color: '#dc2626'}}
                        >
                          Retirer
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Rubriques de dépenses</h2>
          <button onClick={() => setShowRubriqueForm(true)} className={styles.primaryBtn}>
            + Nouvelle rubrique
          </button>
        </div>

        {showRubriqueForm && (
          <div className={styles.formCard}>
            <h3>Créer une rubrique</h3>
            <form onSubmit={handleCreateRubrique} className={styles.form}>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Code *</label>
                  <input
                    type="text"
                    value={rubriqueForm.code}
                    onChange={(e) => setRubriqueForm({ ...rubriqueForm, code: e.target.value.toUpperCase() })}
                    required
                  />
                </div>
                <div className={styles.field}>
                  <label>Libellé *</label>
                  <input
                    type="text"
                    value={rubriqueForm.libelle}
                    onChange={(e) => setRubriqueForm({ ...rubriqueForm, libelle: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.field}>
                <label>Description</label>
                <textarea
                  value={rubriqueForm.description}
                  onChange={(e) => setRubriqueForm({ ...rubriqueForm, description: e.target.value })}
                  rows={2}
                />
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => setShowRubriqueForm(false)} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Créer
                </button>
              </div>
            </form>
          </div>
        )}

        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Code</th>
                <th>Libellé</th>
                <th>Description</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rubriques.map((rubrique) => (
                <tr key={rubrique.id}>
                  <td><strong>{rubrique.code}</strong></td>
                  <td>{rubrique.libelle}</td>
                  <td>{rubrique.description || '-'}</td>
                  <td>
                    <span className={rubrique.active ? styles.activeStatus : styles.inactiveStatus}>
                      {rubrique.active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <button
                      onClick={() => toggleRubrique(rubrique.id, rubrique.active)}
                      className={styles.actionBtn}
                    >
                      {rubrique.active ? 'Désactiver' : 'Activer'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
            </div>
          )}
        </div>

        <div className={styles.accordionItem}>
          <button
            className={`${styles.accordionHeader} ${expandedSection === 'printing' ? styles.active : ''}`}
            onClick={() => toggleSection('printing')}
          >
            <span className={styles.accordionIcon}>{expandedSection === 'printing' ? '▼' : '▶'}</span>
            <span className={styles.accordionTitle}>Documents & Impression</span>
          </button>
          {expandedSection === 'printing' && (
            <div className={styles.accordionContent}>
              <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Paramètres d'impression des reçus</h2>
        </div>

        {printSettings && (
          <div className={styles.formCard}>
            <form onSubmit={handleSavePrintSettings} className={styles.form}>
              <h3>En-tête du reçu</h3>

              <div className={styles.field}>
                <label>Nom de l'organisation *</label>
                <input
                  type="text"
                  value={printSettings.organization_name}
                  onChange={(e) => setPrintSettings({ ...printSettings, organization_name: e.target.value })}
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Sous-titre *</label>
                <input
                  type="text"
                  value={printSettings.organization_subtitle}
                  onChange={(e) => setPrintSettings({ ...printSettings, organization_subtitle: e.target.value })}
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Texte supplémentaire (optionnel)</label>
                <input
                  type="text"
                  value={printSettings.header_text || ''}
                  onChange={(e) => setPrintSettings({ ...printSettings, header_text: e.target.value })}
                  placeholder="Ex: Établissement d'utilité publique"
                />
              </div>

              <div className={styles.checkboxField}>
                <label>
                  <input
                    type="checkbox"
                    checked={printSettings.show_header_logo}
                    onChange={(e) => setPrintSettings({ ...printSettings, show_header_logo: e.target.checked })}
                  />
                  Afficher le logo dans l'en-tête
                </label>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Logo (URL)</label>
                  <input
                    type="text"
                    value={printSettings.logo_url || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, logo_url: e.target.value })}
                    placeholder="https://.../logo.png"
                  />
                </div>
                <div className={styles.field}>
                  <label>Cachet (URL)</label>
                  <input
                    type="text"
                    value={printSettings.stamp_url || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, stamp_url: e.target.value })}
                    placeholder="https://.../cachet.png"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Nom signataire</label>
                  <input
                    type="text"
                    value={printSettings.signature_name || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, signature_name: e.target.value })}
                    placeholder="Nom et prénom"
                  />
                </div>
                <div className={styles.field}>
                  <label>Titre signataire</label>
                  <input
                    type="text"
                    value={printSettings.signature_title || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, signature_title: e.target.value })}
                    placeholder="Ex: Trésorier / Président"
                  />
                </div>
              </div>

              <h3>Informations de contact</h3>

              <div className={styles.field}>
                <label>Adresse</label>
                <input
                  type="text"
                  value={printSettings.address || ''}
                  onChange={(e) => setPrintSettings({ ...printSettings, address: e.target.value })}
                  placeholder="Adresse complète"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Téléphone</label>
                  <input
                    type="text"
                    value={printSettings.phone || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, phone: e.target.value })}
                    placeholder="+243 XX XXX XXXX"
                  />
                </div>
                <div className={styles.field}>
                  <label>Email</label>
                  <input
                    type="email"
                    value={printSettings.email || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, email: e.target.value })}
                    placeholder="contact@example.com"
                  />
                </div>
              </div>

              <div className={styles.field}>
                <label>Site web</label>
                <input
                  type="text"
                  value={printSettings.website || ''}
                  onChange={(e) => setPrintSettings({ ...printSettings, website: e.target.value })}
                  placeholder="www.example.com"
                />
              </div>

              <h3>Informations de paiement</h3>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Nom de la banque</label>
                  <input
                    type="text"
                    value={printSettings.bank_name || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, bank_name: e.target.value })}
                    placeholder="Ex: BCDC, Rawbank, etc."
                  />
                </div>
                <div className={styles.field}>
                  <label>Numéro de compte bancaire</label>
                  <input
                    type="text"
                    value={printSettings.bank_account || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, bank_account: e.target.value })}
                    placeholder="Numéro de compte"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Service Mobile Money</label>
                  <input
                    type="text"
                    value={printSettings.mobile_money_name || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, mobile_money_name: e.target.value })}
                    placeholder="Ex: M-PESA, Orange Money, Airtel Money"
                  />
                </div>
                <div className={styles.field}>
                  <label>Numéro Mobile Money</label>
                  <input
                    type="text"
                    value={printSettings.mobile_money_number || ''}
                    onChange={(e) => setPrintSettings({ ...printSettings, mobile_money_number: e.target.value })}
                    placeholder="+243 XX XXX XXXX"
                  />
                </div>
              </div>

              <h3>Pied de page</h3>

              <div className={styles.field}>
                <label>Texte du pied de page *</label>
                <textarea
                  value={printSettings.footer_text}
                  onChange={(e) => setPrintSettings({ ...printSettings, footer_text: e.target.value })}
                  rows={2}
                  required
                />
              </div>

              <div className={styles.checkboxField}>
                <label>
                  <input
                    type="checkbox"
                    checked={printSettings.show_footer_signature}
                    onChange={(e) => setPrintSettings({ ...printSettings, show_footer_signature: e.target.checked })}
                  />
                  Afficher la zone de cachet
                </label>
              </div>

              <h3>Format d'impression</h3>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Format papier par défaut</label>
                  <select
                    value={printSettings.paper_format || 'A5'}
                    onChange={(e) => setPrintSettings({ ...printSettings, paper_format: e.target.value })}
                  >
                    <option value="A4">A4 (210 × 297 mm)</option>
                    <option value="A5">A5 (148 × 210 mm)</option>
                  </select>
                </div>
                <div className={styles.checkboxField}>
                  <label>
                    <input
                      type="checkbox"
                      checked={printSettings.compact_header}
                      onChange={(e) => setPrintSettings({ ...printSettings, compact_header: e.target.checked })}
                    />
                    En-tête compact (meilleur pour A5)
                  </label>
                </div>
              </div>

              <div className={styles.formActions}>
                <button
                  type="submit"
                  className={styles.primaryBtn}
                  disabled={savingPrintSettings}
                >
                  {savingPrintSettings ? 'Sauvegarde...' : 'Sauvegarder les paramètres'}
                </button>
              </div>
            </form>
          </div>
        )}
              </div>
            </div>
          )}
        </div>
      </div>

      <UserRoleManager />

      <ConfirmModal
        isOpen={confirmResetPassword.show}
        onConfirm={executeResetPassword}
        onCancel={() => setConfirmResetPassword({ show: false, user: null })}
        title="Réinitialiser le mot de passe"
        message={`Êtes-vous sûr de vouloir réinitialiser le mot de passe de ${confirmResetPassword.user?.prenom} ${confirmResetPassword.user?.nom} ?\n\nLe mot de passe sera réinitialisé à : ONECCPK\n\nL'utilisateur devra le changer à la prochaine connexion.`}
        confirmText="OK"
        cancelText="Annuler"
        type="warning"
      />
    </div>
  )
}
