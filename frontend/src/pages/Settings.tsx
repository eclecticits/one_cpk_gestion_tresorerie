import { useState, useEffect } from 'react'
import { Settings as SettingsIcon, Users, Building2, Database, ChevronRight, ArrowUp, ArrowDown } from 'lucide-react'
import {
  adminCreateRequisitionApprover,
  adminCreateRole,
  adminCreateUser,
  adminDeleteRequisitionApprover,
  adminDeleteRole,
  adminDeleteUser,
  adminGetPermissions,
  adminGetRoles,
  adminGetNotificationSettings,
  adminGetPrintSettings,
  adminListRequisitionApprovers,
  adminListUsers,
  adminListUsersAll,
  adminSaveNotificationSettings,
  adminUploadAsset,
  adminResetUserPassword,
  adminUpdateRolePermissions,
  adminUpdateRole,
  adminSavePrintSettings,
  adminTestEmailConnection,
  adminGetWeeklyReportStatus,
  adminRunWeeklyReport,
  adminSetUserPassword,
  adminToggleUserStatus,
  adminUpdateRequisitionApprover,
  adminUpdateUser,
} from '../api/admin'
import type { NotificationSettings, PermissionInfo, RoleInfo, WeeklyReportStatus } from '../api/admin'
import type { PrintSettings } from '../api/admin'
import type { RequisitionApprover } from '../api/admin'
import BankSettings from '../components/settings/BankSettings'
import { useAuth } from '../contexts/AuthContext'
import { useNotification } from '../contexts/NotificationContext'
import { useConfirm, useConfirmWithInput } from '../contexts/ConfirmContext'
import { apiRequest } from '../lib/apiClient'
import { User, Service } from '../types'
import styles from './Settings.module.css'
import UserRoleManager from '../components/UserRoleManager'
import ConfirmModal from '../components/ConfirmModal'
import PermissionsMatrix from '../components/admin/PermissionsMatrix'
import ServiceAdminPanel from '../components/ServiceAdminPanel'
import { getBudgetExercises } from '../api/budget'
import { getServices, assignServiceResponsable } from '../api/services'
import BudgetTab from '../components/settings/BudgetTab'
import ServicesTab from '../components/settings/ServicesTab'
import ServiceMembersManager from '../components/settings/ServiceMembersManager'
// Billing moved to Organisation Settings.

export default function Settings() {
  const confirm = useConfirm()
  const confirmWithInput = useConfirmWithInput()
  const { user } = useAuth()
  const { showSuccess, showError, showWarning } = useNotification()
  const [users, setUsers] = useState<User[]>([])
  const [serviceUsers, setServiceUsers] = useState<User[]>([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [usersLoading, setUsersLoading] = useState(false)
  const [userSearch, setUserSearch] = useState('')
  const [userPage, setUserPage] = useState(1)
  const [usersPerPage, setUsersPerPage] = useState(25)
  const [services, setServices] = useState<Service[]>([])
  const [activeServiceId, setActiveServiceId] = useState<number | null>(null)
  const [printSettings, setPrintSettings] = useState<PrintSettings | null>(null)
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [showUserForm, setShowUserForm] = useState(false)
  const [savingPrintSettings, setSavingPrintSettings] = useState(false)
  const [savingNotificationSettings, setSavingNotificationSettings] = useState(false)
  const [testingNotificationSettings, setTestingNotificationSettings] = useState(false)
  const [weeklyStatus, setWeeklyStatus] = useState<WeeklyReportStatus | null>(null)
  const [weeklyStatusLoading, setWeeklyStatusLoading] = useState(false)
  const [weeklyReportRunning, setWeeklyReportRunning] = useState(false)
  const [approvers, setApprovers] = useState<RequisitionApprover[]>([])
  const [showApproverForm, setShowApproverForm] = useState(false)
  const [selectedApproverId, setSelectedApproverId] = useState('')
  const [activeTab, setActiveTab] = useState<'general' | 'permissions' | 'services' | 'budget'>('general')
  const [generalSubTab, setGeneralSubTab] = useState<'impression' | 'workflow' | 'notifications' | 'approbateurs' | 'rubriques' | 'logs' | 'encaissements' | 'devise' | 'banques'>('impression')
  const [servicesSubTab, setServicesSubTab] = useState<'commissions' | 'membres' | 'admin'>('commissions')
  const [permissionsSubTab, setPermissionsSubTab] = useState<'users' | 'permissions' | 'roles'>('users')
  const [budgetSubTab, setBudgetSubTab] = useState<'structure'>('structure')
  const [printTab, setPrintTab] = useState<'recus' | 'sorties' | 'requisitions' | 'transport' | 'general'>('recus')
  const [showEditForm, setShowEditForm] = useState(false)
  const [confirmResetPassword, setConfirmResetPassword] = useState<{ show: boolean; user: User | null }>({ show: false, user: null })

  const [userForm, setUserForm] = useState({
    email: '',
    nom: '',
    prenom: '',
    role: 'reception',
    service_ids: [] as number[],
  })

  const [editUserForm, setEditUserForm] = useState({
    id: '',
    email: '',
    password: '',
    nom: '',
    prenom: '',
    role: 'reception',
    service_ids: [] as number[],
  })

  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [permissions, setPermissions] = useState<PermissionInfo[]>([])
  const [permissionsMatrix, setPermissionsMatrix] = useState<Record<string, Record<string, boolean>>>({})
  const [savingMatrix, setSavingMatrix] = useState(false)
  const [dirtyMatrix, setDirtyMatrix] = useState(false)
  const [roleLabels, setRoleLabels] = useState<Record<number, string>>({})
  const [budgetLogs, setBudgetLogs] = useState<any[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [uploadingAsset, setUploadingAsset] = useState<'logo' | 'stamp' | null>(null)
  const [budgetExercises, setBudgetExercises] = useState<{ annee: number; statut?: string | null }[]>([])
  // Billing moved to Organisation Settings.
  const [encaissementLibelles, setEncaissementLibelles] = useState<string[]>([])

  const systemRoles = Array.from(
    new Set(
      ['admin', 'tresorerie', 'comptable', 'agent', 'reception', ...roles.map((r) => r.code), ...users.map((u) => u.role)]
        .filter(Boolean)
    )
  )

  useEffect(() => {
    if (!printSettings) return
    const raw = String(printSettings.encaissement_libelle_presets || '')
    const parsed = raw
      .split(/\r?\n+/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
    setEncaissementLibelles(parsed.length ? parsed : [''])
  }, [printSettings?.encaissement_libelle_presets])

  const totalUserPages = Math.max(1, Math.ceil(usersTotal / usersPerPage))
  const safeUserPage = Math.min(userPage, totalUserPages)
  const userStartIndex = usersTotal === 0 ? 0 : (safeUserPage - 1) * usersPerPage

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

  const handleTogglePermission = (roleId: number, permissionCode: string) => {
    setPermissionsMatrix((prev) => ({
      ...prev,
      [String(roleId)]: {
        ...(prev[String(roleId)] || {}),
        [permissionCode]: !prev[String(roleId)]?.[permissionCode],
      },
    }))
    setDirtyMatrix(true)
  }

  const handleSavePermissionsMatrix = async () => {
    try {
      setSavingMatrix(true)
      const roleUpdates = roles.map((role) => ({
        role_id: role.id,
        permission_codes: Object.entries(permissionsMatrix[String(role.id)] || {})
          .filter(([, enabled]) => enabled)
          .map(([code]) => code),
      }))
      await adminUpdateRolePermissions({ roles: roleUpdates })
      const labelUpdates = roles
        .filter((role) => (roleLabels[role.id] ?? '') !== (role.label || ''))
        .map((role) => adminUpdateRole(role.id, { label: roleLabels[role.id] }))
      if (labelUpdates.length > 0) {
        await Promise.all(labelUpdates)
      }
      showSuccess('Permissions mises à jour', 'La matrice de permissions a été enregistrée.')
      const rolesRes = await adminGetRoles()
      setRoles(rolesRes)
      setDirtyMatrix(false)
    } catch (error: any) {
      console.error('Error saving permissions matrix:', error)
      showError('Erreur', error.message || "Impossible d'enregistrer la matrice.")
    } finally {
      setSavingMatrix(false)
    }
  }

  const handleUpdateRoleLabel = (roleId: number, label: string) => {
    setRoleLabels((prev) => ({ ...prev, [roleId]: label }))
    setDirtyMatrix(true)
  }

  const slugifyRole = (value: string) =>
    value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')

  const toggleServiceId = (current: number[], serviceId: number) =>
    current.includes(serviceId) ? current.filter((id) => id !== serviceId) : [...current, serviceId]

  const handleAddRole = async () => {
    const promptRes = await confirmWithInput({
      title: 'Nouveau rôle',
      description: 'Saisissez le nom du nouveau rôle.',
      confirmText: 'Créer',
      cancelText: 'Annuler',
      inputLabel: 'Nom du rôle',
      inputPlaceholder: 'Ex: Comptable',
      inputRequired: true,
      inputMultiline: false,
    })
    if (!promptRes.confirmed) return
    const trimmedLabel = promptRes.value.trim()
    if (!trimmedLabel) {
      showWarning('Nom requis', 'Veuillez saisir un nom de rôle.')
      return
    }
    const code = slugifyRole(trimmedLabel)
    if (!code) {
      showWarning('Nom invalide', 'Utilisez des lettres ou chiffres (ex: Comptable).')
      return
    }
    try {
      const created = await adminCreateRole({ code, label: trimmedLabel })
      const rolesRes = await adminGetRoles()
      const permissionsRes = await adminGetPermissions()
      setRoles(rolesRes)
      setPermissions(permissionsRes)
      const nextMatrix: Record<string, Record<string, boolean>> = {}
      rolesRes.forEach((role) => {
        nextMatrix[String(role.id)] = {}
        permissionsRes.forEach((perm) => {
          nextMatrix[String(role.id)][perm.code] = !!role.permissions?.includes(perm.code)
        })
      })
      setPermissionsMatrix(nextMatrix)
      setRoleLabels((prev) => ({ ...prev, [created.id]: created.label || trimmedLabel }))
      showSuccess('Rôle ajouté', `Le rôle "${trimmedLabel}" a été créé.`)
    } catch (error: any) {
      const detail = error?.payload?.detail || error?.message
      showError('Erreur', detail || 'Impossible de créer le rôle.')
    }
  }

  const handleDeleteRole = async (roleId: number) => {
    const role = roles.find((r) => r.id === roleId)
    if (!role) return
    const ok = await confirm({
      title: 'Supprimer le rôle',
      description: 'Supprimer ce rôle ? Cette action est irréversible.',
      confirmText: 'Supprimer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await adminDeleteRole(roleId)
      const rolesRes = await adminGetRoles()
      const permissionsRes = await adminGetPermissions()
      setRoles(rolesRes)
      setPermissions(permissionsRes)
      const nextMatrix: Record<string, Record<string, boolean>> = {}
      rolesRes.forEach((r) => {
        nextMatrix[String(r.id)] = {}
        permissionsRes.forEach((perm) => {
          nextMatrix[String(r.id)][perm.code] = !!r.permissions?.includes(perm.code)
        })
      })
      setPermissionsMatrix(nextMatrix)
      showSuccess('Rôle supprimé', `Le rôle "${role.label || role.code}" a été supprimé.`)
    } catch (error: any) {
      showError('Erreur', error.message || 'Impossible de supprimer le rôle.')
    }
  }

  const roleLabelMap = roles.reduce<Record<string, string>>((acc, role) => {
    acc[role.code] = role.label || role.code
    return acc
  }, {})
  const serviceMap = services.reduce<Record<number, string>>((acc, service) => {
    acc[service.id] = `${service.code} - ${service.libelle}`
    return acc
  }, {})
  const rolesForMatrix = roles.map((role) => ({
    ...role,
    label: roleLabels[role.id] ?? role.label ?? '',
  }))



  useEffect(() => {
    loadData()
  }, [])


  useEffect(() => {
    if (activeTab !== 'services') return
    const loadServiceUsers = async () => {
      try {
        const allUsers = await adminListUsersAll()
        setServiceUsers(allUsers)
      } catch (error) {
        console.error('Erreur chargement utilisateurs services:', error)
        setServiceUsers(users)
      }
    }
    loadServiceUsers()
  }, [activeTab, users])

  useEffect(() => {
    if (roles.length === 0) return
    if (!roles.find((r) => r.code === userForm.role)) {
      setUserForm((prev) => ({ ...prev, role: roles[0].code }))
    }
  }, [roles])

  useEffect(() => {
    if (activeTab === 'general') setGeneralSubTab('impression')
    if (activeTab === 'services') setServicesSubTab('commissions')
    if (activeTab === 'permissions') setPermissionsSubTab('users')
    if (activeTab === 'budget') setBudgetSubTab('structure')
  }, [activeTab])


  useEffect(() => {
    if (activeTab !== 'general') return
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

  const loadUsers = async (options?: { page?: number; pageSize?: number; search?: string }) => {
    const nextPage = options?.page ?? userPage
    const nextPageSize = options?.pageSize ?? usersPerPage
    const nextSearch = (options?.search ?? userSearch).trim()

    try {
      setUsersLoading(true)
      const params: any = {
        page: nextPage,
        page_size: nextPageSize,
      }
      if (nextSearch) params.search = nextSearch
      const res = await adminListUsers(params)
      setUsers(res.items)
      setUsersTotal(res.total)
      setUserPage(res.page)
      setUsersPerPage(res.page_size)

      const totalPages = Math.max(1, Math.ceil(res.total / res.page_size))
      if (res.total > 0 && res.items.length === 0 && nextPage > totalPages) {
        await loadUsers({ page: totalPages, pageSize: nextPageSize, search: nextSearch })
      }
    } catch (error: any) {
      console.error('Erreur chargement utilisateurs:', error)
      setUsers([])
      setUsersTotal(0)
    } finally {
      setUsersLoading(false)
    }
  }

  const loadData = async () => {
    try {
      setLoading(true)

      const printSettingsRes = await adminGetPrintSettings()
      const notificationSettingsRes = await adminGetNotificationSettings()
      let weeklyStatusRes: WeeklyReportStatus | null = null
      try {
        weeklyStatusRes = await adminGetWeeklyReportStatus()
      } catch (err) {
        weeklyStatusRes = null
      }
      const rolesRes = await adminGetRoles()
      const permissionsRes = await adminGetPermissions()
      const approversData = await adminListRequisitionApprovers()
      const exercisesRes = await getBudgetExercises()
      const servicesRes = await getServices()

      setPrintSettings(printSettingsRes.data)
      setNotificationSettings(notificationSettingsRes.data)
      setWeeklyStatus(weeklyStatusRes)
      setRoles(rolesRes)
      const labelsMap: Record<number, string> = {}
      rolesRes.forEach((role) => {
        labelsMap[role.id] = role.label || ''
      })
      setRoleLabels(labelsMap)
      setPermissions(permissionsRes)
      const nextMatrix: Record<string, Record<string, boolean>> = {}
      rolesRes.forEach((role) => {
        nextMatrix[String(role.id)] = {}
        permissionsRes.forEach((perm) => {
          nextMatrix[String(role.id)][perm.code] = !!role.permissions?.includes(perm.code)
        })
      })
      setPermissionsMatrix(nextMatrix)
      setDirtyMatrix(false)
      setApprovers(approversData)
      setBudgetExercises(exercisesRes.exercices || [])
      const nextServices = Array.isArray(servicesRes) ? servicesRes : []
      setServices(nextServices)
      setActiveServiceId((prev) => (prev == null && nextServices.length > 0 ? nextServices[0].id : prev))
      await loadUsers()
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadWeeklyStatus = async () => {
    try {
      setWeeklyStatusLoading(true)
      const res = await adminGetWeeklyReportStatus()
      setWeeklyStatus(res)
    } catch (error: any) {
      setWeeklyStatus(null)
      showError('Rapport hebdo', error?.message || 'Impossible de charger le statut.')
    } finally {
      setWeeklyStatusLoading(false)
    }
  }

  const handleRunWeeklyReportNow = async () => {
    try {
      setWeeklyReportRunning(true)
      await adminRunWeeklyReport()
      showSuccess('Rapport hebdo', 'Rapport envoyé.')
      await loadWeeklyStatus()
    } catch (error: any) {
      showError('Rapport hebdo', error?.message || 'Impossible d’envoyer le rapport.')
    } finally {
      setWeeklyReportRunning(false)
    }
  }

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      await adminCreateUser({
        email: userForm.email,
        nom: userForm.nom,
        prenom: userForm.prenom,
        role: userForm.role,
        service_ids: userForm.service_ids,
      })

      showSuccess(
        'Utilisateur créé avec succès',
        `${userForm.prenom} ${userForm.nom} a été ajouté au système. Mot de passe temporaire défini côté serveur (à changer à la première connexion).`
      )

      setShowUserForm(false)
      setUserForm({
        email: '',
        nom: '',
        prenom: '',
        role: 'reception',
        service_ids: [],
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
      service_ids: userToEdit.service_ids && userToEdit.service_ids.length > 0
        ? userToEdit.service_ids
        : userToEdit.service_id
          ? [userToEdit.service_id]
          : [],
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
        `Un code OTP a été envoyé à ${targetUser.email}. Le compte est réinitialisé et l'utilisateur devra définir un nouveau mot de passe.`
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
        service_ids: editUserForm.service_ids,
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
        service_ids: [],
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

  const normalizeEmailList = (value: string) => {
    const seen = new Set<string>()
    return value
      .split(/[,\n;]+/)
      .map((email) => email.trim())
      .filter((email) => email.length > 0)
      .filter((email) => {
        const key = email.toLowerCase()
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      .join(', ')
  }

  const normalizeEmail = (value: string) => value.trim()
  const normalizePhoneList = (value: string) => {
    const seen = new Set<string>()
    return value
      .split(/[,\n;]+/)
      .map((phone) => phone.trim().replace(/\s+/g, ''))
      .map((phone) => (phone.startsWith('+') ? `+${phone.replace(/\D/g, '')}` : phone.replace(/\D/g, '')))
      .filter((phone) => phone.length > 0)
      .filter((phone) => {
        if (seen.has(phone)) return false
        seen.add(phone)
        return true
      })
      .join(', ')
  }

  const handleSaveNotificationSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!notificationSettings) return

    setSavingNotificationSettings(true)
    try {
      const { id, updated_by, updated_at, ...payload } = notificationSettings
      const normalizedPayload = {
        ...payload,
        email_expediteur: normalizeEmail(payload.email_expediteur || ''),
        email_president: normalizeEmail(payload.email_president || ''),
        email_tresorier: normalizeEmail(payload.email_tresorier || ''),
        email_validation_1: normalizeEmail(payload.email_validation_1 || ''),
        email_validation_final: normalizeEmail(payload.email_validation_final || ''),
        emails_bureau_cc: normalizeEmailList(payload.emails_bureau_cc || ''),
        emails_bureau_sortie_cc: normalizeEmailList(payload.emails_bureau_sortie_cc || ''),
        whatsapp_api_url: (payload.whatsapp_api_url || '').trim(),
        whatsapp_api_key: (payload.whatsapp_api_key || '').trim(),
        whatsapp_agents: normalizePhoneList(payload.whatsapp_agents || ''),
      }
      await adminSaveNotificationSettings(normalizedPayload)
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
      <div className={styles.settingsLayout}>
        <aside className={styles.settingsSidebar}>
          <div className={styles.settingsTitle}>Paramètres</div>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'general' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('general')}
          >
            <span>
              <SettingsIcon size={16} /> Général
            </span>
            {activeTab === 'general' && <ChevronRight size={16} />}
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'permissions' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('permissions')}
          >
            <span>
              <Users size={16} /> Rôles & Accès
            </span>
            {activeTab === 'permissions' && <ChevronRight size={16} />}
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'services' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('services')}
          >
            <span>
              <Building2 size={16} /> Services & Commissions
            </span>
            {activeTab === 'services' && <ChevronRight size={16} />}
          </button>
          <button
            className={`${styles.settingsNavButton} ${activeTab === 'budget' ? styles.settingsNavActive : ''}`}
            onClick={() => setActiveTab('budget')}
          >
            <span>
              <Database size={16} /> Structure budgétaire
            </span>
            {activeTab === 'budget' && <ChevronRight size={16} />}
          </button>
        </aside>

        <div className={styles.settingsContent}>
          {activeTab === 'budget' && (
            <div>
              <div className={styles.subNav}>
                <button
                  className={`${styles.subNavButton} ${budgetSubTab === 'structure' ? styles.subNavActive : ''}`}
                  onClick={() => setBudgetSubTab('structure')}
                >
                  Structure budgétaire
                </button>
              </div>
              {budgetSubTab === 'structure' && (
                <BudgetTab
                  services={services}
                  activeServiceId={activeServiceId}
                  setActiveServiceId={(id) => setActiveServiceId(id)}
                />
              )}
            </div>
          )}
          {activeTab === 'services' && (
            <div className={styles.servicesLayout}>
              <div className={styles.subNav}>
                <button
                  className={`${styles.subNavButton} ${servicesSubTab === 'commissions' ? styles.subNavActive : ''}`}
                  onClick={() => setServicesSubTab('commissions')}
                >
                  Responsables
                </button>
                <button
                  className={`${styles.subNavButton} ${servicesSubTab === 'membres' ? styles.subNavActive : ''}`}
                  onClick={() => setServicesSubTab('membres')}
                >
                  Membres
                </button>
                <button
                  className={`${styles.subNavButton} ${servicesSubTab === 'admin' ? styles.subNavActive : ''}`}
                  onClick={() => setServicesSubTab('admin')}
                >
                  Administration
                </button>
              </div>
              {servicesSubTab === 'commissions' && (
                <ServicesTab
                  services={services}
                  users={serviceUsers.length ? serviceUsers : users}
                  onAssign={async (serviceId, userId) => {
                    try {
                      await assignServiceResponsable(serviceId, userId)
                      await loadData()
                      showSuccess('Responsable mis à jour', 'Le responsable de la commission a été mis à jour.')
                    } catch (error: any) {
                      console.error('Erreur assignation responsable:', error)
                      showError('Erreur', error?.message || 'Impossible d’assigner le responsable.')
                    }
                  }}
                  onOpenService={(serviceId) => {
                    setActiveServiceId(serviceId)
                    setServicesSubTab('membres')
                  }}
                />
              )}
              {servicesSubTab === 'membres' && (
                <ServiceMembersManager
                  services={services}
                  users={serviceUsers.length ? serviceUsers : users}
                  activeServiceId={activeServiceId}
                />
              )}
              {servicesSubTab === 'admin' && <ServiceAdminPanel onUpdated={loadData} />}
            </div>
          )}
          {activeTab === 'permissions' && (
            <div className={styles.accordion}>
              <div className={styles.accordionItem}>
                <div className={styles.subNav}>
                  <button
                    className={`${styles.subNavButton} ${permissionsSubTab === 'users' ? styles.subNavActive : ''}`}
                    onClick={() => setPermissionsSubTab('users')}
                  >
                    Utilisateurs
                  </button>
                  <button
                    className={`${styles.subNavButton} ${permissionsSubTab === 'permissions' ? styles.subNavActive : ''}`}
                    onClick={() => setPermissionsSubTab('permissions')}
                  >
                    Permissions
                  </button>
                  <button
                    className={`${styles.subNavButton} ${permissionsSubTab === 'roles' ? styles.subNavActive : ''}`}
                    onClick={() => setPermissionsSubTab('roles')}
                  >
                    Rôles
                  </button>
                </div>
                {permissionsSubTab === 'users' && (
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
                    {roles.length === 0 && <option value="reception">reception</option>}
                    {roles.map((role) => (
                      <option key={role.code} value={role.code}>
                        {role.label || role.code}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className={styles.field}>
                <label>Services (optionnel)</label>
                <div className={styles.serviceActions}>
                  <button
                    type="button"
                    className={styles.serviceActionBtn}
                    onClick={() =>
                      setEditUserForm({
                        ...editUserForm,
                        service_ids: services.map((service) => service.id),
                      })
                    }
                  >
                    Tout sélectionner
                  </button>
                  <button
                    type="button"
                    className={styles.serviceActionBtn}
                    onClick={() =>
                      setEditUserForm({
                        ...editUserForm,
                        service_ids: [],
                      })
                    }
                  >
                    Tout retirer
                  </button>
                </div>
                <div className={styles.serviceGrid}>
                  {services.map((service) => (
                    <label key={service.id} className={styles.serviceOption}>
                      <input
                        type="checkbox"
                        className={styles.serviceCheckbox}
                        checked={editUserForm.service_ids.includes(service.id)}
                        onChange={() =>
                          setEditUserForm({
                            ...editUserForm,
                            service_ids: toggleServiceId(editUserForm.service_ids, service.id),
                          })
                        }
                      />
                      <span>{service.code} - {service.libelle}</span>
                    </label>
                  ))}
                  {services.length === 0 && (
                    <div className={styles.serviceEmpty}>Aucun service disponible.</div>
                  )}
                </div>
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Cochez un ou plusieurs services pour cet utilisateur.
                </small>
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
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                    required
                  >
                    {roles.length === 0 && <option value="reception">reception</option>}
                    {roles.map((role) => (
                      <option key={role.code} value={role.code}>
                        {role.label || role.code}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className={styles.field}>
                <label>Services (optionnel)</label>
                <div className={styles.serviceActions}>
                  <button
                    type="button"
                    className={styles.serviceActionBtn}
                    onClick={() =>
                      setUserForm({
                        ...userForm,
                        service_ids: services.map((service) => service.id),
                      })
                    }
                  >
                    Tout sélectionner
                  </button>
                  <button
                    type="button"
                    className={styles.serviceActionBtn}
                    onClick={() =>
                      setUserForm({
                        ...userForm,
                        service_ids: [],
                      })
                    }
                  >
                    Tout retirer
                  </button>
                </div>
                <div className={styles.serviceGrid}>
                  {services.map((service) => (
                    <label key={service.id} className={styles.serviceOption}>
                      <input
                        type="checkbox"
                        className={styles.serviceCheckbox}
                        checked={userForm.service_ids.includes(service.id)}
                        onChange={() =>
                          setUserForm({
                            ...userForm,
                            service_ids: toggleServiceId(userForm.service_ids, service.id),
                          })
                        }
                      />
                      <span>{service.code} - {service.libelle}</span>
                    </label>
                  ))}
                  {services.length === 0 && (
                    <div className={styles.serviceEmpty}>Aucun service disponible.</div>
                  )}
                </div>
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Cochez un ou plusieurs services pour cet utilisateur.
                </small>
              </div>

              <div className={styles.infoBox} style={{marginBottom: '16px', padding: '12px', background: '#fef3c7', border: '1px solid #fbbf24', borderRadius: '8px'}}>
                <p style={{margin: 0, fontSize: '13px', color: '#78350f'}}>
                  <strong>Mot de passe temporaire :</strong> défini côté serveur - L'utilisateur devra le changer à la première connexion.
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

        <div className={styles.tableToolbar}>
          <div className={styles.tableMeta}>
            {usersTotal === 0
              ? 'Aucun utilisateur'
              : `Affichage ${userStartIndex + 1}-${Math.min(userStartIndex + usersPerPage, usersTotal)} sur ${usersTotal}`}
          </div>
          <div className={styles.tableFilters}>
            <input
              type="search"
              className={styles.searchInput}
              placeholder="Rechercher un utilisateur..."
              value={userSearch}
              onChange={(e) => {
                const next = e.target.value
                setUserSearch(next)
                loadUsers({ page: 1, pageSize: usersPerPage, search: next })
              }}
            />
          </div>
          <div className={styles.paginationControls}>
            <span className={styles.pageSizeLabel}>
              Par page
              <select
                className={styles.pageSizeSelect}
                value={usersPerPage}
                onChange={(e) => {
                  const nextSize = Number(e.target.value)
                  loadUsers({ page: 1, pageSize: nextSize })
                }}
              >
                {[10, 25, 50, 100].map((size) => (
                  <option key={size} value={size}>{size}</option>
                ))}
              </select>
            </span>
            <button
              type="button"
              className={styles.paginationButton}
              onClick={() => loadUsers({ page: 1 })}
              disabled={safeUserPage === 1}
              aria-label="Première page"
            >
              «
            </button>
            <button
              type="button"
              className={styles.paginationButton}
              onClick={() => loadUsers({ page: Math.max(1, safeUserPage - 1) })}
              disabled={safeUserPage === 1}
              aria-label="Page précédente"
            >
              ‹
            </button>
            <span className={styles.paginationInfo}>
              Page {safeUserPage} / {totalUserPages}
            </span>
            <button
              type="button"
              className={styles.paginationButton}
              onClick={() => loadUsers({ page: Math.min(totalUserPages, safeUserPage + 1) })}
              disabled={safeUserPage === totalUserPages}
              aria-label="Page suivante"
            >
              ›
            </button>
            <button
              type="button"
              className={styles.paginationButton}
              onClick={() => loadUsers({ page: totalUserPages })}
              disabled={safeUserPage === totalUserPages}
              aria-label="Dernière page"
            >
              »
            </button>
          </div>
        </div>

        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Email</th>
                <th>Rôle</th>
                <th>Service</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {usersLoading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: '#64748b' }}>
                    Chargement...
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: '#64748b' }}>
                    Aucun utilisateur trouvé.
                  </td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id}>
                    <td><strong>{user.prenom} {user.nom}</strong></td>
                    <td>{user.email}</td>
                    <td><span className={styles.badge}>{roleLabelMap[user.role] || user.role}</span></td>
                    <td>
                      {user.service_ids && user.service_ids.length > 0
                        ? user.service_ids
                            .map((sid) => serviceMap[sid] || `#${sid}`)
                            .join(', ')
                        : user.service_id
                          ? serviceMap[user.service_id] || `#${user.service_id}`
                          : '—'}
                    </td>
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
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
                  )}
                  {permissionsSubTab === 'permissions' && (
                    <div className={styles.section} style={{ marginTop: '24px' }}>
                      <PermissionsMatrix
                        roles={rolesForMatrix}
                        permissions={permissions}
                        matrix={permissionsMatrix}
                        onToggle={handleTogglePermission}
                        onSave={handleSavePermissionsMatrix}
                        onAddRole={handleAddRole}
                        onDeleteRole={handleDeleteRole}
                        onUpdateRoleLabel={handleUpdateRoleLabel}
                        saving={savingMatrix}
                        dirty={dirtyMatrix}
                      />
                    </div>
                  )}
                  {permissionsSubTab === 'roles' && <UserRoleManager />}
                </div>
              </div>
          )}
      {activeTab === 'general' && (
        <div className={styles.subNav}>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'impression' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('impression')}
          >
            Impression
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'workflow' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('workflow')}
          >
            Workflow
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'notifications' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('notifications')}
          >
            Notifications
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'approbateurs' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('approbateurs')}
          >
            Approbateurs
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'devise' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('devise')}
          >
            Devise
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'encaissements' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('encaissements')}
          >
            Encaissements
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'banques' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('banques')}
          >
            Gestion bancaire
          </button>
          <button
            className={`${styles.subNavButton} ${generalSubTab === 'logs' ? styles.subNavActive : ''}`}
            onClick={() => setGeneralSubTab('logs')}
          >
            Historique
          </button>
        </div>
      )}
      {activeTab === 'general' && generalSubTab !== 'impression' && (
        <div className={styles.section}>
              {generalSubTab === 'workflow' && printSettings && (
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

              {generalSubTab === 'notifications' && notificationSettings && (
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

                      <div className={styles.sectionDivider} />
                      <h3 className={styles.subSectionTitle}>Workflow de validation</h3>

                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>Email rapporteur (validation 1)</label>
                          <input
                            type="email"
                            value={notificationSettings.email_validation_1 || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, email_validation_1: e.target.value })
                            }
                            placeholder="rapporteur@cpk.org"
                          />
                        </div>
                        <div className={styles.field}>
                          <label>Email président (validation finale)</label>
                          <input
                            type="email"
                            value={notificationSettings.email_validation_final || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, email_validation_final: e.target.value })
                            }
                            placeholder="president@cpk.org"
                          />
                        </div>
                      </div>

                      <div className={styles.sectionDivider} />
                      <h3 className={styles.subSectionTitle}>Notifications WhatsApp (validation 2/2)</h3>
                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>URL Evolution / Baileys</label>
                          <input
                            type="text"
                            value={notificationSettings.whatsapp_api_url || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, whatsapp_api_url: e.target.value })
                            }
                            placeholder="https://wa.example.com/message/sendText"
                          />
                        </div>
                        <div className={styles.field}>
                          <label>API Key</label>
                          <input
                            type="password"
                            value={notificationSettings.whatsapp_api_key || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, whatsapp_api_key: e.target.value })
                            }
                            placeholder="Saisissez la clé d'API"
                          />
                        </div>
                      </div>

                      <div className={styles.field}>
                        <label>Numéros des agents (format international)</label>
                        <textarea
                          rows={3}
                          value={notificationSettings.whatsapp_agents || ''}
                          onChange={(e) =>
                            setNotificationSettings({ ...notificationSettings, whatsapp_agents: e.target.value })
                          }
                          placeholder="243812345678, 243899988877"
                        />
                        <div className={styles.mutedText}>
                          Séparez les numéros par virgule, point-virgule ou retour à la ligne.
                        </div>
                      </div>

                      <div className={styles.field}>
                        <label>Plafond caisse (alerte)</label>
                        <input
                          type="number"
                          min="0"
                          value={notificationSettings.max_caisse_amount || 0}
                          onChange={(e) =>
                            setNotificationSettings({
                              ...notificationSettings,
                              max_caisse_amount: Number(e.target.value),
                            })
                          }
                          placeholder="0"
                        />
                        <div className={styles.mutedText}>
                          Une alerte sera affichée si le solde actuel dépasse ce montant.
                        </div>
                      </div>

                      <div className={styles.sectionDivider} />
                      <h3 className={styles.subSectionTitle}>Paramètres Sorties de Fonds</h3>

                      <div className={styles.fieldRow}>
                        <div className={styles.field}>
                          <label>Email du trésorier</label>
                          <input
                            type="email"
                            value={notificationSettings.email_tresorier || ''}
                            onChange={(e) =>
                              setNotificationSettings({ ...notificationSettings, email_tresorier: e.target.value })
                            }
                            placeholder="tresorier@cpk.org"
                          />
                        </div>
                      </div>

                      <div className={styles.field}>
                        <label>Emails du bureau (CC) pour les sorties</label>
                        <textarea
                          rows={3}
                          value={notificationSettings.emails_bureau_sortie_cc || ''}
                          onChange={(e) =>
                            setNotificationSettings({
                              ...notificationSettings,
                              emails_bureau_sortie_cc: e.target.value,
                            })
                          }
                          placeholder="membre1@cpk.org, membre2@cpk.org, ..."
                        />
                        <div className={styles.mutedText}>
                          {countCcEmails(notificationSettings.emails_bureau_sortie_cc || '')} adresse(s) détectée(s)
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

                      <div className={styles.sectionDivider} />
                      <h3 className={styles.subSectionTitle}>Rapport hebdomadaire (lundi matin)</h3>
                      <div className={styles.weeklyCard}>
                        <div className={styles.weeklyStatusRow}>
                          <div>
                            <div className={styles.weeklyLabel}>Statut du planificateur</div>
                            <div className={styles.weeklyMeta}>
                              {weeklyStatusLoading && 'Chargement...'}
                              {!weeklyStatusLoading && weeklyStatus && (
                                <>
                                  <span
                                    className={
                                      weeklyStatus.enabled && weeklyStatus.running
                                        ? styles.badgeActive
                                        : styles.badgeInactive
                                    }
                                  >
                                    {weeklyStatus.enabled && weeklyStatus.running ? 'Actif' : 'Inactif'}
                                  </span>
                                  <span>Fuseau : {weeklyStatus.timezone}</span>
                                  <span>
                                    Prochaine exécution :
                                    {weeklyStatus.next_run
                                      ? ` ${new Date(weeklyStatus.next_run).toLocaleString('fr-FR')}`
                                      : ' —'}
                                  </span>
                                  <span>
                                    Dernier envoi :
                                    {weeklyStatus.last_sent_at
                                      ? ` ${new Date(weeklyStatus.last_sent_at).toLocaleString('fr-FR')}`
                                      : ' —'}
                                  </span>
                                  <span>
                                    Dernier succès :
                                    {weeklyStatus.last_success_at
                                      ? ` ${new Date(weeklyStatus.last_success_at).toLocaleString('fr-FR')}`
                                      : ' —'}
                                  </span>
                                  <span>
                                    Dernier échec :
                                    {weeklyStatus.last_failure_at
                                      ? ` ${new Date(weeklyStatus.last_failure_at).toLocaleString('fr-FR')}`
                                      : ' —'}
                                  </span>
                                </>
                              )}
                              {!weeklyStatusLoading && !weeklyStatus && 'Statut indisponible.'}
                            </div>
                          </div>
                          <div className={styles.weeklyActions}>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={loadWeeklyStatus}
                              disabled={weeklyStatusLoading}
                            >
                              {weeklyStatusLoading ? 'Actualisation...' : 'Actualiser'}
                            </button>
                            <button
                              type="button"
                              className={styles.primaryBtn}
                              onClick={handleRunWeeklyReportNow}
                              disabled={weeklyReportRunning}
                            >
                              {weeklyReportRunning ? 'Envoi...' : 'Envoyer maintenant'}
                            </button>
                          </div>
                        </div>
                        {weeklyStatus && weeklyStatus.last_status === 'failed' && (
                          <div className={styles.weeklyWarning}>
                            Dernier envoi en échec. {weeklyStatus.last_error || 'Vérifiez la configuration SMTP.'}
                          </div>
                        )}
                        <div className={styles.weeklyHint}>
                          L’envoi utilise les paramètres SMTP ci-dessus et le destinataire configuré via
                          <code className={styles.inlineCode}>WEEKLY_REPORT_TO</code>.
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

      {generalSubTab === 'approbateurs' && (
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
      )}

      {generalSubTab === 'encaissements' && printSettings && (
        <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Encaissements</h2>
          <span className={styles.mutedText}>Pré‑liste des libellés</span>
        </div>
        <div className={styles.formCard}>
          <div className={styles.formGrid}>
            <div className={styles.field} style={{ gridColumn: '1 / -1' }}>
              <label>Libellés suggérés</label>
              <div className={styles.presetList}>
                {encaissementLibelles.map((value, index) => (
                  <div key={`libelle-${index}`} className={styles.presetRow}>
                    <div className={styles.presetIndex}>{index + 1}</div>
                    <input
                      type="text"
                      value={value}
                      onChange={(e) => {
                        const next = [...encaissementLibelles]
                        next[index] = e.target.value
                        setEncaissementLibelles(next)
                      }}
                      placeholder="Ex: Cotisation annuelle 2026"
                      maxLength={255}
                    />
                    <div className={styles.presetActions}>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => {
                          if (index === 0) return
                          setEncaissementLibelles((prev) => {
                            const next = [...prev]
                            const tmp = next[index - 1]
                            next[index - 1] = next[index]
                            next[index] = tmp
                            return next
                          })
                        }}
                        disabled={index === 0}
                        title="Monter"
                      >
                        <ArrowUp size={14} />
                      </button>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => {
                          if (index >= encaissementLibelles.length - 1) return
                          setEncaissementLibelles((prev) => {
                            const next = [...prev]
                            const tmp = next[index + 1]
                            next[index + 1] = next[index]
                            next[index] = tmp
                            return next
                          })
                        }}
                        disabled={index >= encaissementLibelles.length - 1}
                        title="Descendre"
                      >
                        <ArrowDown size={14} />
                      </button>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => {
                          setEncaissementLibelles((prev) => prev.filter((_, i) => i !== index))
                        }}
                        disabled={encaissementLibelles.length <= 1}
                      >
                        Retirer
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => setEncaissementLibelles((prev) => [...prev, ''])}
                style={{ marginTop: '10px', alignSelf: 'flex-start' }}
              >
                + Ajouter une ligne
              </button>
              <div className={styles.fieldHint}>
                Ces libellés apparaîtront en auto‑complétion dans le formulaire d'encaissement.
              </div>
            </div>
          </div>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={savingPrintSettings}
              onClick={() =>
                saveSettingsSection('Encaissements', {
                  encaissement_libelle_presets: encaissementLibelles
                    .map((item) => item.trim())
                    .filter((item) => item.length > 0)
                    .join('\n'),
                })
              }
            >
              {savingPrintSettings ? 'Sauvegarde...' : 'Enregistrer'}
            </button>
          </div>
        </div>
      </div>
      )}

      {generalSubTab === 'devise' && printSettings && (
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Devise</h2>
          <span className={styles.mutedText}>
            Mise à jour: {printSettings.updated_at ? new Date(printSettings.updated_at).toLocaleString('fr-FR') : '-'}
          </span>
        </div>
        <div className={styles.settingsCard}>
          <div className={styles.cardHeader}>
            <h2>Régie financière</h2>
            <span className={styles.mutedText}>
              Devise, taux et exercice actif
            </span>
          </div>
          <div className={styles.formGrid}>
            <div className={styles.field}>
              <label>Devise pivot</label>
              <select
                value={printSettings.default_currency || 'USD'}
                onChange={(e) => setPrintSettings({ ...printSettings, default_currency: e.target.value })}
              >
                <option value="USD">USD ($)</option>
                <option value="CDF">CDF (FC)</option>
                <option value="EUR">EUR (€)</option>
                <option value="XOF">XOF (CFA)</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>Devise secondaire</label>
              <select
                value={printSettings.secondary_currency || 'CDF'}
                onChange={(e) => setPrintSettings({ ...printSettings, secondary_currency: e.target.value })}
              >
                <option value="CDF">CDF (FC)</option>
                <option value="USD">USD ($)</option>
                <option value="EUR">EUR (€)</option>
                <option value="XOF">XOF (CFA)</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>Base USD (1 USD = X CDF)</label>
              <input
                type="number"
                step="0.01"
                value={printSettings.exchange_rate_cdf ?? printSettings.exchange_rate ?? 0}
                onChange={(e) =>
                  setPrintSettings({ ...printSettings, exchange_rate_cdf: Number(e.target.value) })
                }
              />
            </div>
            <div className={styles.field}>
              <label>Base USD (1 USD = X EUR)</label>
              <input
                type="number"
                step="0.0001"
                value={printSettings.exchange_rate_eur ?? 0}
                onChange={(e) =>
                  setPrintSettings({ ...printSettings, exchange_rate_eur: Number(e.target.value) })
                }
              />
            </div>
            <div className={styles.field}>
              <label>Base USD (1 USD = X CFA)</label>
              <input
                type="number"
                step="0.01"
                value={printSettings.exchange_rate_xof ?? 0}
                onChange={(e) =>
                  setPrintSettings({ ...printSettings, exchange_rate_xof: Number(e.target.value) })
                }
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
                  exchange_rate: printSettings.exchange_rate_cdf ?? printSettings.exchange_rate,
                  exchange_rate_cdf: printSettings.exchange_rate_cdf ?? printSettings.exchange_rate,
                  exchange_rate_eur: printSettings.exchange_rate_eur,
                  exchange_rate_xof: printSettings.exchange_rate_xof,
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

      {generalSubTab === 'logs' && (
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
      )}
        </div>
      )}
      {generalSubTab === 'banques' && (
        <div className={styles.section}>
          <BankSettings />
        </div>
      )}
      {activeTab === 'general' && generalSubTab === 'impression' && (
        <div className={styles.section}>
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
                        className={`${styles.printTab} ${printTab === 'sorties' ? styles.printTabActive : ''}`}
                        onClick={() => setPrintTab('sorties')}
                      >
                        Sorties de fonds
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
                        </div>
                      )}

                      {printTab === 'sorties' && (
                        <div className={styles.tabPanel}>
                          <h3>Paramètres des sorties de caisse</h3>
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
                              <label>Signature 1 (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_sig_label_1 || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_sig_label_1: e.target.value })
                                }
                                placeholder="Ex: CAISSIER"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Signature 2 (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_sig_label_2 || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_sig_label_2: e.target.value })
                                }
                                placeholder="Ex: COMPTABLE"
                              />
                            </div>
                          </div>
                          <div className={styles.fieldRow}>
                            <div className={styles.field}>
                              <label>Signature 3 (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_sig_label_3 || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_sig_label_3: e.target.value })
                                }
                                placeholder="Ex: AUTORITÉ (TRÉSORERIE)"
                              />
                            </div>
                            <div className={styles.field}>
                              <label>Texte sous signature (sorties)</label>
                              <input
                                type="text"
                                value={printSettings.sortie_sig_hint || ''}
                                onChange={(e) =>
                                  setPrintSettings({ ...printSettings, sortie_sig_hint: e.target.value })
                                }
                                placeholder="Ex: Signature & date"
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
      </div>
      <ConfirmModal
        isOpen={confirmResetPassword.show}
        onConfirm={executeResetPassword}
        onCancel={() => setConfirmResetPassword({ show: false, user: null })}
        title="Réinitialiser le mot de passe"
        message={`Êtes-vous sûr de vouloir réinitialiser le mot de passe de ${confirmResetPassword.user?.prenom} ${confirmResetPassword.user?.nom} ?\n\nLe mot de passe sera réinitialisé (défini côté serveur).\n\nL'utilisateur devra le changer à la prochaine connexion.`}
        confirmText="OK"
        cancelText="Annuler"
        type="warning"
      />
    </div>
  )
}
