import { useState, useEffect } from 'react'
import { adminAssignUserRole, adminListUserRoles, adminListUsers, adminRemoveUserRole } from '../api/admin'
import { useAuth } from '../contexts/AuthContext'
import { User, UserRoleAssignment, SystemRole } from '../types'
import styles from './UserRoleManager.module.css'

export default function UserRoleManager() {
  const { user: currentUser } = useAuth()
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
    setIsAdmin(currentUser?.role === 'admin')
    loadData()
  }, [currentUser?.id])

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
      alert('Veuillez sélectionner un utilisateur et un rôle')
      return
    }

    try {
      await adminAssignUserRole({ user_id: selectedUser, role: selectedRole })

      alert('Rôle attribué avec succès')
      setSelectedUser('')
      setSelectedRole('caissier')
      loadData()
    } catch (error: any) {
      console.error('Error assigning role:', error)
      if (error?.status === 409) {
        alert('Cet utilisateur a déjà ce rôle')
      } else {
        alert(`Erreur: ${error.message || 'Erreur inconnue'}`)
      }
    }
  }

  const handleRemoveRole = async (roleId: string) => {
    if (!confirm('Voulez-vous vraiment retirer ce rôle?')) return

    try {
      await adminRemoveUserRole(roleId)
      alert('Rôle retiré avec succès')
      loadData()
    } catch (error: any) {
      console.error('Error removing role:', error)
      alert(`Erreur: ${error.message || 'Erreur inconnue'}`)
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

  if (loading) {
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
