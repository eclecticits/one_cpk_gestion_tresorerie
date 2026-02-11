import { useState, useEffect } from 'react'
import { adminAssignUserRole, adminListUserRoles, adminListUsers, adminRemoveUserRole } from '../api/admin'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { User, UserRoleAssignment, SystemRole } from '../types'
import styles from './UserRoleManager.module.css'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../hooks/useToast'

export default function UserRoleManager() {
  const { user: currentUser } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const confirm = useConfirm()
  const { notifyError, notifySuccess, notifyWarning } = useToast()
  const [users, setUsers] = useState<User[]>([])
  const [roleAssignments, setRoleAssignments] = useState<UserRoleAssignment[]>([])
  const [loading, setLoading] = useState(true)
  const [isAdmin, setIsAdmin] = useState(false)
  const [selectedUser, setSelectedUser] = useState<string>('')
  const [selectedRole, setSelectedRole] = useState<SystemRole>('caissier')

  const availableRoles: SystemRole[] = ['admin', 'caissier', 'reporting_viewer']

  const roleLabels: Record<SystemRole, string> = {
    admin: 'Administrateur',
    caissier: 'Caissier',
    reporting_viewer: 'Visualiseur de Rapports'
  }

  useEffect(() => {
    setIsAdmin(hasPermission('settings'))
    loadData()
  }, [currentUser?.id, hasPermission])

  const loadData = async () => {
    try {
      const usersData = await adminListUsers()
      const rolesData = await adminListUserRoles()

      setUsers(usersData)
      setRoleAssignments(rolesData)
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleAssignRole = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedUser || !selectedRole) {
      notifyWarning('Sélection requise', 'Veuillez sélectionner un utilisateur et un rôle.')
      return
    }

    try {
      await adminAssignUserRole({ user_id: selectedUser, role: selectedRole })

      notifySuccess('Rôle attribué', 'Le rôle a été attribué avec succès.')
      setSelectedUser('')
      setSelectedRole('caissier')
      loadData()
    } catch (error: any) {
      console.error('Error assigning role:', error)
      if (error?.status === 409) {
        notifyWarning('Rôle existant', 'Cet utilisateur a déjà ce rôle.')
      } else {
        notifyError('Erreur', error.message || 'Erreur inconnue')
      }
    }
  }

  const handleRemoveRole = async (roleId: string) => {
    const confirmed = await confirm({
      title: 'Retirer ce rôle ?',
      description: 'L’utilisateur perdra les permissions associées.',
      confirmText: 'Retirer',
      variant: 'danger',
    })
    if (!confirmed) return

    try {
      await adminRemoveUserRole(roleId)
      notifySuccess('Rôle retiré', 'Le rôle a été retiré avec succès.')
      loadData()
    } catch (error: any) {
      console.error('Error removing role:', error)
      notifyError('Erreur', error.message || 'Erreur inconnue')
    }
  }

  const getRoleLabel = (role: SystemRole) => {
    return roleLabels[role] || role
  }

  const getRoleColor = (role: SystemRole) => {
    switch (role) {
      case 'admin':
        return '#dc2626'
      case 'caissier':
        return '#2563eb'
      case 'reporting_viewer':
        return '#16a34a'
      default:
        return '#6b7280'
    }
  }

  if (loading || permissionsLoading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  if (!isAdmin) {
    return (
      <div className={styles.accessDenied}>
        Accès restreint aux administrateurs
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.section}>
        <h3>Attribution de privilèges système</h3>
        <p className={styles.description}>
          Gérez les privilèges spéciaux comme l'accès aux rapports pour les autorités
        </p>

        <form onSubmit={handleAssignRole} className={styles.form}>
          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Utilisateur *</label>
              <select
                value={selectedUser}
                onChange={(e) => setSelectedUser(e.target.value)}
                required
              >
                <option value="">Sélectionner un utilisateur</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.prenom} {u.nom} ({u.email})
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.field}>
              <label>Privilège *</label>
              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value as SystemRole)}
                required
              >
                {availableRoles.map(role => (
                  <option key={role} value={role}>{roleLabels[role]}</option>
                ))}
              </select>
            </div>

            <button type="submit" className={styles.primaryBtn}>
              Attribuer
            </button>
          </div>
        </form>
      </div>

      <div className={styles.section}>
        <h3>Privilèges attribués</h3>
        <div className={styles.rolesList}>
          {roleAssignments.length === 0 ? (
            <div className={styles.emptyState}>Aucun privilège attribué</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Utilisateur</th>
                  <th>Privilège</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {roleAssignments.map((assignment) => {
                  const u = users.find((usr) => usr.id === assignment.user_id)
                  return (
                    <tr key={assignment.id}>
                      <td>
                        {u ? (
                          <div>
                            <strong>{u.prenom} {u.nom}</strong>
                            <div className={styles.userEmail}>{u.email}</div>
                          </div>
                        ) : (
                          'Utilisateur inconnu'
                        )}
                      </td>
                      <td>
                        <span
                          className={styles.roleBadge}
                          style={{ backgroundColor: getRoleColor(assignment.role) }}
                        >
                          {getRoleLabel(assignment.role)}
                        </span>
                      </td>
                      <td>
                        <button
                          onClick={() => handleRemoveRole(assignment.id)}
                          className={styles.removeBtn}
                        >
                          Retirer
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
