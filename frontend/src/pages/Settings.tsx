import { useState, useEffect } from 'react'
import {
  adminCreateRequisitionApprover,
  adminCreateRubrique,
  adminCreateUser,
  adminDeleteRequisitionApprover,
  adminDeleteUser,
  adminGetNotificationSettings,
  adminGetPrintSettings,
  adminGetRoleMenuPermissions,
  adminListRoleMenuPermissionsRoles,
  adminListRequisitionApprovers,
  adminListRubriques,
  adminListUsers,
  adminSaveNotificationSettings,
  adminUploadAsset,
  adminResetUserPassword,
  adminSavePrintSettings,
  adminTestEmailConnection,
  adminSetRoleMenuPermissions,
  adminSetUserPassword,
  adminToggleUserStatus,
  adminUpdateRequisitionApprover,
  adminUpdateRubrique,
  adminUpdateUser,
} from '../api/admin'
import type { NotificationSettings } from '../api/admin'
import type { PrintSettings } from '../api/admin'
import type { RequisitionApprover } from '../api/admin'
import { useAuth } from '../contexts/AuthContext'
import { useNotification } from '../contexts/NotificationContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { apiRequest } from '../lib/apiClient'
import { User, Rubrique } from '../types'
import styles from './Settings.module.css'
import UserRoleManager from '../components/UserRoleManager'
import ConfirmModal from '../components/ConfirmModal'
import Budget from './Budget'
import { getBudgetExercises } from '../api/budget'

export default function Settings() {
  const confirm = useConfirm()
  const { user } = useAuth()
  const { showSuccess, showError, showWarning } = useNotification()
  const [users, setUsers] = useState<User[]>([])
  const [rubriques, setRubriques] = useState<Rubrique[]>([])
  const [printSettings, setPrintSettings] = useState<PrintSettings | null>(null)
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [showUserForm, setShowUserForm] = useState(false)
  const [showRubriqueForm, setShowRubriqueForm] = useState(false)
  const [savingPrintSettings, setSavingPrintSettings] = useState(false)
  const [savingNotificationSettings, setSavingNotificationSettings] = useState(false)
  const [testingNotificationSettings, setTestingNotificationSettings] = useState(false)
  const [approvers, setApprovers] = useState<RequisitionApprover[]>([])
  const [showApproverForm, setShowApproverForm] = useState(false)
  const [selectedApproverId, setSelectedApproverId] = useState('')
  const [expandedSection, setExpandedSection] = useState<string>('users')
  const [activeTab, setActiveTab] = useState<'organisation' | 'budget' | 'security' | 'system'>('organisation')
  const [printTab, setPrintTab] = useState<'recus' | 'requisitions' | 'transport' | 'general'>('recus')
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

  const [rolePermissions, setRolePermissions] = useState<Record<string, boolean>>({})
  const [rolePermissionName, setRolePermissionName] = useState('')
  const [rolePermissionLoading, setRolePermissionLoading] = useState(false)
  const [budgetLogs, setBudgetLogs] = useState<any[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [uploadingAsset, setUploadingAsset] = useState<'logo' | 'stamp' | null>(null)
  const [budgetExercises, setBudgetExercises] = useState<{ annee: number; statut?: string | null }[]>([])

  const systemRoles = Array.from(
    new Set(
      ['admin', 'tresorerie', 'comptable', 'agent', 'reception', ...users.map((u) => u.role)].filter(Boolean)
    )
  )

  const handleUploadAsset = async (kind: 'logo' | 'stamp', file: File) => {
    if (!printSettings) return
    try {
      setUploadingAsset(kind)
      const res = await adminUploadAsset(kind, file)
      const next = {
        ...printSettings,
        logo_url: kind === 'logo' ? res.url : printSettings.logo_url,
        stamp_url: kind === 'stamp' ? res.url : printSettings.stamp_url,
      }
      setPrintSettings(next)
      await saveSettingsSection('Identité', {
        logo_url: next.logo_url,
        stamp_url: next.stamp_url,
      })
    } catch (error: any) {
      console.error('Erreur upload:', error)
      showError('Upload impossible', error.message || 'Impossible de charger le fichier.')
    } finally {
      setUploadingAsset(null)
    }
  }

  const [rubriqueForm, setRubriqueForm] = useState({
    code: '',
    libelle: '',
    description: '',
  })

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    if (activeTab === 'security') setExpandedSection('users')
    if (activeTab === 'system') setExpandedSection('config')
    if (activeTab === 'organisation') setExpandedSection('printing')
  }, [activeTab])

  useEffect(() => {
    if (activeTab !== 'system') return
    const loadLogs = async () => {
      try {
        setLogsLoading(true)
        const params: any = {}
        if (printSettings?.fiscal_year) params.annee = printSettings.fiscal_year
        const res = await apiRequest<any>('GET', '/budget/audit-logs', { params })
        setBudgetLogs(Array.isArray(res) ? res : [])
      } catch (error) {
        console.error('Erreur chargement logs budget:', error)
        setBudgetLogs([])
      } finally {
        setLogsLoading(false)
      }
    }
    loadLogs()
  }, [activeTab, printSettings?.fiscal_year])

  const loadData = async () => {
    try {
      setLoading(true)

      const usersData = await adminListUsers()
      const rubriquesData = await adminListRubriques()
      const printSettingsRes = await adminGetPrintSettings()
      const notificationSettingsRes = await adminGetNotificationSettings()
      const approversData = await adminListRequisitionApprovers()
      const exercisesRes = await getBudgetExercises()

      setUsers(usersData)
      setRubriques(rubriquesData)
      setPrintSettings(printSettingsRes.data)
      setNotificationSettings(notificationSettingsRes.data)
      setApprovers(approversData)
      setBudgetExercises(exercisesRes.exercices || [])
      await loadRolePermissionsList()
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

  const MENU_OPTIONS = [
    { id: 'dashboard', label: 'Tableau de bord' },
    { id: 'encaissements', label: 'Encaissements' },
    { id: 'requisitions', label: 'Réquisitions' },
    { id: 'validation', label: 'Validation' },
    { id: 'sorties_fonds', label: 'Sorties de fonds' },
    { id: 'budget', label: 'Budget' },
    { id: 'rapports', label: 'Rapports' },
    { id: 'experts_comptables', label: 'Experts-comptables' },
    { id: 'settings', label: 'Paramètres' },
  ]

  const [availableRoles, setAvailableRoles] = useState<string[]>([])

  const loadRolePermissionsList = async () => {
    try {
      const res = await adminListRoleMenuPermissionsRoles()
      setAvailableRoles(res.roles || [])
    } catch (error) {
      console.error('Error loading role list:', error)
      setAvailableRoles([])
    }
  }

  const handleLoadRolePermissions = async () => {
    if (!rolePermissionName) {
      showWarning('Nom requis', 'Veuillez saisir un nom de privilège.')
      return
    }
    setRolePermissionLoading(true)
    try {
      const res = await adminGetRoleMenuPermissions(rolePermissionName)
      const permissions: Record<string, boolean> = {}
      res.menus?.forEach((m) => {
        permissions[m] = true
      })
      setRolePermissions(permissions)
    } catch (error: any) {
      console.error('Error loading role permissions:', error)
      showError('Erreur', 'Impossible de charger les permissions du privilège.')
    } finally {
      setRolePermissionLoading(false)
    }
  }

  const handleSaveRolePermissions = async () => {
    if (!rolePermissionName) {
      showWarning('Nom requis', 'Veuillez saisir un nom de privilège.')
      return
    }
    const menus = Object.entries(rolePermissions)
      .filter(([_, canAccess]) => canAccess)
      .map(([menuName]) => menuName)
    try {
      await adminSetRoleMenuPermissions(rolePermissionName, menus)
      setAvailableRoles((prev) => {
        if (prev.includes(rolePermissionName)) return prev
        return [...prev, rolePermissionName].sort()
      })
      await loadRolePermissionsList()
      showSuccess('Privilège enregistré', `Les droits du privilège "${rolePermissionName}" ont été sauvegardés.`)
    } catch (error: any) {
      console.error('Error saving role permissions:', error)
      showError('Erreur', 'Impossible d’enregistrer les permissions.')
    }
  }

  const toggleRolePermission = (menuName: string) => {
    setRolePermissions(prev => ({
      ...prev,
      [menuName]: !prev[menuName]
    }))
  }

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
    const confirmed = await confirm({
      title: 'Retirer cet approbateur ?',
      description: "Il ne pourra plus approuver de réquisitions.",
      confirmText: 'Retirer',
      variant: 'danger',
    })
    if (!confirmed) return

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

    const confirmed = await confirm({
      title: currentStatus ? 'Désactiver le compte ?' : 'Réactiver le compte ?',
      description: confirmMessage,
      confirmText: currentStatus ? 'Désactiver' : 'Réactiver',
      variant: currentStatus ? 'danger' : 'default',
    })
    if (!confirmed) return

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

    const confirmed = await confirm({
      title: 'Supprimer définitivement ?',
      description: confirmMessage,
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return

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

  const saveSettingsSection = async (section: string, payload: Partial<PrintSettings>) => {
    if (!printSettings) return
    setSavingPrintSettings(true)
    try {
      await adminSavePrintSettings(payload)
      showSuccess('Paramètres sauvegardés', `La section "${section}" a été mise à jour.`)
      loadData()
    } catch (error: any) {
      console.error('Error saving settings section:', error)
      showError('Erreur de sauvegarde', error.message || 'Impossible de sauvegarder la configuration.')
    } finally {
      setSavingPrintSettings(false)
    }
  }

  const countCcEmails = (value: string) => {
    return value
      .split(/[,\n;]+/)
      .map((email) => email.trim())
      .filter((email) => email.length > 0).length
  }

  const handleSaveNotificationSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!notificationSettings) return

    setSavingNotificationSettings(true)
    try {
      const { id, updated_by, updated_at, ...payload } = notificationSettings
      await adminSaveNotificationSettings(payload)
      showSuccess('Paramètres sauvegardés', 'La configuration email a été mise à jour.')
      loadData()
    } catch (error: any) {
      console.error('Error saving notification settings:', error)
      showError('Erreur de sauvegarde', error.message || 'Impossible de sauvegarder la configuration email.')
    } finally {
      setSavingNotificationSettings(false)
    }
  }

  const handleTestNotificationSettings = async () => {
    if (!notificationSettings) return
    setTestingNotificationSettings(true)
    try {
      const { id, updated_by, updated_at, ...payload } = notificationSettings
      const res = await adminTestEmailConnection(payload)
      showSuccess('Connexion réussie', res.message || 'Vérifiez votre boîte mail.')
    } catch (error: any) {
      console.error('Error testing notification settings:', error)
      const rawMessage = String(error?.message || error?.detail || '')
      if (rawMessage.includes('5.7.8') || rawMessage.toLowerCase().includes('username and password not accepted')) {
        showError(
          'Identifiants SMTP refusés',
          "Google refuse les identifiants (erreur 535 « Username and Password not accepted »). " +
            "C'est le cas attendu quand la validation en 2 étapes est requise. " +
            "Activez la validation en 2 étapes, générez un mot de passe d'application (16 caractères), " +
            "collez-le dans « Mot de passe SMTP (Gmail) », puis relancez le test."
        )
      } else {
        showError('Test échoué', rawMessage || 'Impossible de tester la connexion SMTP.')
      }
    } finally {
      setTestingNotificationSettings(false)
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <datalist id="role-options">
        {availableRoles.map(role => (
          <option key={role} value={role} />
        ))}
      </datalist>
      <div className={styles.settingsLayout}>
        <aside className={styles.settingsSidebar}>
          <div className={styles.settingsTitle}>Paramètres</div>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'organisation' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('organisation')}
          >
            🏢 Organisation
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'budget' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('budget')}
          >
            📊 Gestion Budgétaire
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'security' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('security')}
          >
            🔐 Sécurité & Utilisateurs
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'system' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('system')}
          >
            ⚙️ Système
          </button>
        </aside>

        <div className={styles.settingsContent}>
          {activeTab === 'budget' ? (
            <Budget />
          ) : (
            <div className={styles.accordion}>
              {activeTab === 'security' && (
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
                  <input
                    list="role-options"
                    value={editUserForm.role}
                    onChange={(e) => setEditUserForm({ ...editUserForm, role: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => {
                  setShowEditForm(false)
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
                  <input
                    list="role-options"
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.infoBox} style={{marginBottom: '16px', padding: '12px', background: '#fef3c7', border: '1px solid #fbbf24', borderRadius: '8px'}}>
                <p style={{margin: 0, fontSize: '13px', color: '#78350f'}}>
                  <strong>Mot de passe par défaut :</strong> ONECCPK - L'utilisateur devra le changer à la première connexion.
                </p>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => {
                  setShowUserForm(false)
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

        <div className={styles.section} style={{ marginTop: '24px' }}>
          <div className={styles.sectionHeader}>
            <h2>Privilèges & accès</h2>
          </div>
          <div className={styles.formCard}>
            <div className={styles.fieldRow}>
              <div className={styles.field}>
                <label>Nom du privilège</label>
                <input
                  type="text"
                  value={rolePermissionName}
                  onChange={(e) => setRolePermissionName(e.target.value)}
                  placeholder="ex: administrateur, caisse, lecture"
                />
              </div>
              <div className={styles.field}>
                <label>Privilèges existants</label>
                <select
                  value={rolePermissionName}
                  onChange={(e) => setRolePermissionName(e.target.value)}
                >
                  <option value="">Sélectionner…</option>
                  {availableRoles.map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className={styles.formActions} style={{ justifyContent: 'flex-start', gap: '12px' }}>
              <button type="button" className={styles.secondaryBtn} onClick={handleLoadRolePermissions} disabled={rolePermissionLoading}>
                {rolePermissionLoading ? 'Chargement...' : 'Charger'}
              </button>
              <button type="button" className={styles.primaryBtn} onClick={handleSaveRolePermissions}>
                Enregistrer & ajouter
              </button>
            </div>

            <div className={styles.field} style={{ marginTop: '12px' }}>
              <label>Pages autorisées</label>
              <div className={styles.permissionsList}>
                {MENU_OPTIONS.map(menu => (
                  <label key={menu.id} className={styles.permissionItem}>
                    <input
                      type="checkbox"
                      checked={rolePermissions[menu.id] || false}
                      onChange={() => toggleRolePermission(menu.id)}
                    />
                    <span>{menu.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
        <UserRoleManager />
      </div>
            </div>
          )}
        </div>
      )}
      {activeTab === 'system' && (
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
              {printSettings && (
                <div className={styles.section}>
                  <div className={styles.sectionHeader}>
                    <h2>Workflow budgétaire</h2>
                  </div>
                  <div className={styles.formCard}>
                    <form onSubmit={handleSavePrintSettings} className={styles.form}>
                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>Seuil d’alerte (%)</label>
                          <input
                            type="range"
                            min={0}
                            max={100}
                            value={printSettings.budget_alert_threshold || 80}
                            onChange={(e) =>
                              setPrintSettings({ ...printSettings, budget_alert_threshold: Number(e.target.value) })
                            }
                          />
                          <div className={styles.rangeValue}>{printSettings.budget_alert_threshold || 80}%</div>
                        </div>
                      </div>
                      <div className={styles.field}>
                        <label>Rôles autorisés à forcer</label>
                        <div className={styles.rolesGrid}>
                          {systemRoles.map((role) => {
                            const rolesSet = new Set(
                              (printSettings.budget_force_roles || '')
                                .split(',')
                                .map((r) => r.trim())
                                .filter(Boolean)
                            )
                            const checked = rolesSet.has(role)
                            return (
                              <label key={role} className={styles.permissionItem}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => {
                                    const next = new Set(rolesSet)
                                    if (checked) next.delete(role)
                                    else next.add(role)
                                    setPrintSettings({
                                      ...printSettings,
                                      budget_force_roles: Array.from(next).join(', '),
                                    })
                                  }}
                                />
                                <span>{role}</span>
                              </label>
                            )
                          })}
                        </div>
                      </div>
                      <div className={styles.checkboxField}>
                        <label>
                          <input
                            type="checkbox"
                            checked={printSettings.budget_block_overrun}
                            onChange={(e) =>
                              setPrintSettings({ ...printSettings, budget_block_overrun: e.target.checked })
                            }
                          />
                          Bloquer toute dépense au-delà du budget
                        </label>
                      </div>
                      <div className={styles.formActions}>
                        <button type="submit" className={styles.primaryBtn} disabled={savingPrintSettings}>
                          {savingPrintSettings ? 'Sauvegarde...' : 'Enregistrer le workflow'}
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}

              {notificationSettings && (
                <div className={styles.section}>
                  <div className={styles.sectionHeader}>
                    <h2>Notifications email</h2>
                  </div>
                  <div className={styles.formCard}>
                    <form onSubmit={handleSaveNotificationSettings} className={styles.form}>
                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>Email expéditeur</label>
                          <input
                            type="email"
                            value={notificationSettings.email_expediteur || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, email_expediteur: e.target.value })
                            }
                            placeholder="expediteur@gmail.com"
                          />
                        </div>
                        <div className={styles.field}>
                          <label>Email du président</label>
                          <input
                            type="email"
                            value={notificationSettings.email_president || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, email_president: e.target.value })
                            }
                            placeholder="president@cpk.org"
                          />
                        </div>
                      </div>

                      <div className={styles.field}>
                        <label>Mot de passe SMTP (Gmail)</label>
                        <input
                          type="password"
                          value={notificationSettings.smtp_password || ''}
                          onChange={(e) =>
                            setNotificationSettings({ ...notificationSettings, smtp_password: e.target.value })
                          }
                          placeholder="Saisissez votre mot de passe ici"
                        />
                        <div className={styles.mutedText}>
                          Si l’envoi échoue, activez la validation en deux étapes et utilisez le code à 16 caractères.
                        </div>
                      </div>

                      <div className={styles.field}>
                        <label>Emails du bureau (CC)</label>
                        <textarea
                          rows={3}
                          value={notificationSettings.emails_bureau_cc || ''}
                          onChange={(e) =>
                            setNotificationSettings({ ...notificationSettings, emails_bureau_cc: e.target.value })
                          }
                          placeholder="membre1@cpk.org, membre2@cpk.org, ..."
                        />
                        <div className={styles.mutedText}>
                          {countCcEmails(notificationSettings.emails_bureau_cc || '')} adresse(s) détectée(s)
                        </div>
                      </div>

                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>SMTP host</label>
                          <input
                            type="text"
                            value={notificationSettings.smtp_host || 'smtp.gmail.com'}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, smtp_host: e.target.value })
                            }
                          />
                        </div>
                        <div className={styles.field}>
                          <label>SMTP port</label>
                          <input
                            type="number"
                            value={notificationSettings.smtp_port || 465}
                            onChange={(e) =>
                              setNotificationSettings({
                                ...notificationSettings,
                                smtp_port: Number(e.target.value),
                              })
                            }
                          />
                        </div>
                      </div>

                      <div className={styles.formActions}>
                        <button type="button" className={styles.secondaryBtn} onClick={handleTestNotificationSettings} disabled={testingNotificationSettings}>
                          {testingNotificationSettings ? 'Test...' : 'Tester la connexion'}
                        </button>
                        <button type="submit" className={styles.primaryBtn} disabled={savingNotificationSettings}>
                          {savingNotificationSettings ? 'Sauvegarde...' : 'Enregistrer'}
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}

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

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Historique des modifications budgétaires</h2>
        </div>
        {logsLoading ? (
          <div className={styles.loading}>Chargement des logs...</div>
        ) : budgetLogs.length === 0 ? (
          <div className={styles.emptyState}>Aucune modification récente.</div>
        ) : (
          <div className={styles.tableContainer}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Action</th>
                  <th>Champ</th>
                  <th>Ancien</th>
                  <th>Nouveau</th>
                  <th>Utilisateur</th>
                </tr>
              </thead>
              <tbody>
                {budgetLogs.slice(0, 50).map((log: any) => (
                  <tr key={log.id}>
                    <td>{log.created_at ? new Date(log.created_at).toLocaleString('fr-FR') : '-'}</td>
                    <td>{log.action}</td>
                    <td>{log.field_name}</td>
                    <td>{log.old_value ?? '-'}</td>
                    <td>{log.new_value ?? '-'}</td>
                    <td>{log.user_name ? `${log.user_name} (${log.user_role || '-'})` : log.user_id ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
            </div>
          )}
        </div>
      )}
      {activeTab === 'organisation' && (
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
              {printSettings && (
                <div className={styles.settingsGrid}>
                  <div className={styles.settingsCard}>
                    <div className={styles.cardHeader}>
                      <h2>Identité visuelle</h2>
                      <span className={styles.mutedText}>Nom officiel + logo</span>
                    </div>
                    <div className={styles.formGrid}>
                      <div className={styles.field}>
                        <label>Nom de l'organisation</label>
                        <input
                          type="text"
                          value={printSettings.organization_name}
                          onChange={(e) => setPrintSettings({ ...printSettings, organization_name: e.target.value })}
                        />
                      </div>
                      <div className={styles.field}>
                        <label>Sous-titre</label>
                        <input
                          type="text"
                          value={printSettings.organization_subtitle}
                          onChange={(e) => setPrintSettings({ ...printSettings, organization_subtitle: e.target.value })}
                        />
                      </div>
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
                        <label>Upload logo</label>
                        <label className={styles.uploadBox}>
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            onChange={(e) => {
                              const file = e.target.files?.[0]
                              if (file) handleUploadAsset('logo', file)
                            }}
                            disabled={uploadingAsset === 'logo'}
                          />
                          <span>{uploadingAsset === 'logo' ? 'Envoi...' : 'Glisser-déposer ou choisir un fichier'}</span>
                        </label>
                      </div>
                      <div className={styles.field}>
                        <label>Afficher le logo</label>
                        <label className={styles.checkboxField}>
                          <input
                            type="checkbox"
                            checked={printSettings.show_header_logo}
                            onChange={(e) => setPrintSettings({ ...printSettings, show_header_logo: e.target.checked })}
                          />
                          Activer
                        </label>
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
                      <div className={styles.field}>
                        <label>Upload cachet</label>
                        <label className={styles.uploadBox}>
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            onChange={(e) => {
                              const file = e.target.files?.[0]
                              if (file) handleUploadAsset('stamp', file)
                            }}
                            disabled={uploadingAsset === 'stamp'}
                          />
                          <span>{uploadingAsset === 'stamp' ? 'Envoi...' : 'Glisser-déposer ou choisir un fichier'}</span>
                        </label>
                      </div>
                    </div>
                    <div className={styles.formActions}>
                      <button
                        type="button"
                        className={styles.primaryBtn}
                        disabled={savingPrintSettings}
                        onClick={() =>
                          saveSettingsSection('Identité', {
                            organization_name: printSettings.organization_name,
                            organization_subtitle: printSettings.organization_subtitle,
                            logo_url: printSettings.logo_url,
                            show_header_logo: printSettings.show_header_logo,
                          })
                        }
                      >
                        {savingPrintSettings ? 'Sauvegarde...' : 'Enregistrer'}
                      </button>
                    </div>
                  </div>

                  <div className={styles.settingsCard}>
                    <div className={styles.cardHeader}>
                      <h2>Régie financière</h2>
                      <span className={styles.mutedText}>
                        Mise à jour: {printSettings.updated_at ? new Date(printSettings.updated_at).toLocaleString('fr-FR') : '-'}
                      </span>
                    </div>
                    <div className={styles.formGrid}>
                      <div className={styles.field}>
                        <label>Devise pivot</label>
                        <select
                          value={printSettings.default_currency || 'USD'}
                          onChange={(e) => setPrintSettings({ ...printSettings, default_currency: e.target.value })}
                        >
                          <option value="USD">USD</option>
                          <option value="CDF">CDF</option>
                        </select>
                      </div>
                      <div className={styles.field}>
                        <label>Devise secondaire</label>
                        <select
                          value={printSettings.secondary_currency || 'CDF'}
                          onChange={(e) => setPrintSettings({ ...printSettings, secondary_currency: e.target.value })}
                        >
                          <option value="CDF">CDF</option>
                          <option value="USD">USD</option>
                        </select>
                      </div>
                      <div className={styles.field}>
                        <label>Taux de change (1 USD = X CDF)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={printSettings.exchange_rate || 0}
                          onChange={(e) => setPrintSettings({ ...printSettings, exchange_rate: Number(e.target.value) })}
                        />
                      </div>
                      <div className={styles.field}>
                        <label>Exercice actif</label>
                        <select
                          value={printSettings.fiscal_year || 2026}
                          onChange={(e) => setPrintSettings({ ...printSettings, fiscal_year: Number(e.target.value) })}
                        >
                          {budgetExercises.length === 0 && <option value={printSettings.fiscal_year || 2026}>Aucun exercice</option>}
                          {budgetExercises.map((ex) => (
                            <option key={ex.annee} value={ex.annee}>
                              {ex.annee} {ex.statut ? `· ${ex.statut}` : ''}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className={styles.formActions}>
                      <button
                        type="button"
                        className={styles.primaryBtn}
                        disabled={savingPrintSettings}
                        onClick={() =>
                          saveSettingsSection('Régie financière', {
                            default_currency: printSettings.default_currency,
                            secondary_currency: printSettings.secondary_currency,
                            exchange_rate: printSettings.exchange_rate,
                            fiscal_year: printSettings.fiscal_year,
                          })
                        }
                      >
                        {savingPrintSettings ? 'Sauvegarde...' : 'Enregistrer'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2>Centre de paramétrage d'impression</h2>
                </div>

                {printSettings && (
                  <div className={styles.formCard}>
                    <div className={styles.printTabs}>
                      <button
                        type="button"
                        className={`${styles.printTab} ${printTab === 'recus' ? styles.printTabActive : ''}`}
                        onClick={() => setPrintTab('recus')}
                      >
                        Reçus
                      </button>
                      <button
                        type="button"
                        className={`${styles.printTab} ${printTab === 'requisitions' ? styles.printTabActive : ''}`}
                        onClick={() => setPrintTab('requisitions')}
                      >
                        Réquisitions
                      </button>
                      <button
                        type="button"
                        className={`${styles.printTab} ${printTab === 'transport' ? styles.printTabActive : ''}`}
                        onClick={() => setPrintTab('transport')}
                      >
                        Transport
                      </button>
                      <button
                        type="button"
                        className={`${styles.printTab} ${printTab === 'general' ? styles.printTabActive : ''}`}
                        onClick={() => setPrintTab('general')}
                      >
                        Général
                      </button>
                    </div>

                    <form onSubmit={handleSavePrintSettings} className={styles.form}>
                      {printTab === 'recus' && (
                        <div className={styles.tabPanel}>
                          <h3>Paramètres des reçus</h3>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé signature</label>
                              <input
                                type="text"
                                value={printSettings.recu_label_signature || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, recu_label_signature: e.target.value })
                                }
                                placeholder="Ex: Cachet & Signature"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom du signataire</label>
                              <input
                                type="text"
                                value={printSettings.recu_nom_signataire || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, recu_nom_signataire: e.target.value })
                                }
                                placeholder="Ex: Esther BIMPE"
                              />
                            </div>
                          </div>
                          <div className={styles.checkboxField}>
                            <label>
                              <input
                                type="checkbox"
                                checked={printSettings.show_footer_signature}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, show_footer_signature: e.target.checked })
                                }
                              />
                              Afficher la zone de cachet
                            </label>
                          </div>
                          <div className={styles.sectionDivider} />
                          <h4>Sorties de caisse</h4>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé signature (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_label_signature || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_label_signature: e.target.value })
                                }
                                placeholder="Ex: Cachet & signature"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom du signataire (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_nom_signataire || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_nom_signataire: e.target.value })
                                }
                                placeholder="Ex: Esther BIMPE"
                              />
                            </div>
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>URL de validation QR (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_qr_base_url || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_qr_base_url: e.target.value })
                                }
                                placeholder="Ex: https://audit.onec-cpk.cd/verify?ref="
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Texte filigrane (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_watermark_text || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_watermark_text: e.target.value })
                                }
                                placeholder="Ex: PAYÉ"
                              />
                            </div>
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Opacité filigrane (0 à 1)</label>
                              <input
                                type="number"
                                min="0"
                                max="1"
                                step="0.05"
                                value={printSettings.sortie_watermark_opacity ?? 0.15}
                                onChange={(e) =>
                                  setPrintSettings({
                                    ...printSettings,
                                    sortie_watermark_opacity: Number(e.target.value)
                                  })
                                }
                              />
                            </div>
                            <div className={styles.field} />
                          </div>
                          <div className={styles.checkboxField}>
                            <label>
                              <input
                                type="checkbox"
                                checked={printSettings.show_sortie_qr}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, show_sortie_qr: e.target.checked })
                                }
                              />
                              Afficher le QR Code de validation
                            </label>
                          </div>
                          <div className={styles.checkboxField}>
                            <label>
                              <input
                                type="checkbox"
                                checked={printSettings.show_sortie_watermark}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, show_sortie_watermark: e.target.checked })
                                }
                              />
                              Afficher le filigrane de sécurité
                            </label>
                          </div>
                        </div>
                      )}

                      {printTab === 'requisitions' && (
                        <div className={styles.tabPanel}>
                          <h3>Paramètres des réquisitions</h3>
                          <div className={styles.field}>
                            <label>Titre officiel</label>
                            <input
                              type="text"
                              value={printSettings.req_titre_officiel || ''}
                              onChange={(e) =>
                                setPrintSettings({ ...printSettings, req_titre_officiel: e.target.value })
                              }
                              placeholder="Ex: RÉQUISITION DE FONDS"
                            />
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé gauche</label>
                              <input
                                type="text"
                                value={printSettings.req_label_gauche || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, req_label_gauche: e.target.value })
                                }
                                placeholder="Ex: Établi par"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom gauche</label>
                              <input
                                type="text"
                                value={printSettings.req_nom_gauche || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, req_nom_gauche: e.target.value })
                                }
                                placeholder="Nom / Fonction"
                              />
                            </div>
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé droite</label>
                              <input
                                type="text"
                                value={printSettings.req_label_droite || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, req_label_droite: e.target.value })
                                }
                                placeholder="Ex: Approuvé par"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom droite</label>
                              <input
                                type="text"
                                value={printSettings.req_nom_droite || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, req_nom_droite: e.target.value })
                                }
                                placeholder="Nom / Fonction"
                              />
                            </div>
                          </div>
                        </div>
                      )}

                      {printTab === 'transport' && (
                        <div className={styles.tabPanel}>
                          <h3>Paramètres des transports</h3>
                          <div className={styles.field}>
                            <label>Titre officiel</label>
                            <input
                              type="text"
                              value={printSettings.trans_titre_officiel || ''}
                              onChange={(e) =>
                                setPrintSettings({ ...printSettings, trans_titre_officiel: e.target.value })
                              }
                              placeholder="Ex: ÉTAT DE FRAIS DE DÉPLACEMENT"
                            />
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé gauche</label>
                              <input
                                type="text"
                                value={printSettings.trans_label_gauche || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, trans_label_gauche: e.target.value })
                                }
                                placeholder="Ex: Vu par la Trésorière"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom gauche</label>
                              <input
                                type="text"
                                value={printSettings.trans_nom_gauche || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, trans_nom_gauche: e.target.value })
                                }
                                placeholder="Ex: Esther BIMPE"
                              />
                            </div>
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Libellé droite</label>
                              <input
                                type="text"
                                value={printSettings.trans_label_droite || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, trans_label_droite: e.target.value })
                                }
                                placeholder="Ex: Approuvé par"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Nom droite</label>
                              <input
                                type="text"
                                value={printSettings.trans_nom_droite || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, trans_nom_droite: e.target.value })
                                }
                                placeholder="Nom / Fonction"
                              />
                            </div>
                          </div>
                        </div>
                      )}

                      {printTab === 'general' && (
                        <div className={styles.tabPanel}>
                          <h3>Paramètres généraux</h3>
                          <div className={styles.field}>
                            <label>Pied de page légal</label>
                            <textarea
                              value={printSettings.pied_de_page_legal || ''}
                              onChange={(e) =>
                                setPrintSettings({ ...printSettings, pied_de_page_legal: e.target.value })
                              }
                              rows={2}
                            />
                          </div>
                          <div className={styles.checkboxField}>
                            <label>
                              <input
                                type="checkbox"
                                checked={printSettings.afficher_qr_code}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, afficher_qr_code: e.target.checked })
                                }
                              />
                              Afficher le QR code sur les documents
                            </label>
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
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, mobile_money_name: e.target.value })
                                }
                                placeholder="Ex: M-PESA, Orange Money, Airtel Money"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Numéro Mobile Money</label>
                              <input
                                type="text"
                                value={printSettings.mobile_money_number || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, mobile_money_number: e.target.value })
                                }
                                placeholder="+243 XX XXX XXXX"
                              />
                            </div>
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
                                  onChange={(e) =>
                                    setPrintSettings({ ...printSettings, compact_header: e.target.checked })
                                  }
                                />
                                En-tête compact (meilleur pour A5)
                              </label>
                            </div>
                          </div>
                        </div>
                      )}

                      <div className={styles.formActions}>
                        <button type="submit" className={styles.primaryBtn} disabled={savingPrintSettings}>
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
      )}
    </div>
  )}
        </div>
      </div>

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
