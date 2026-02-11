import styles from './PermissionsMatrix.module.css'
import type { PermissionInfo, RoleInfo } from '../../api/admin'

const PERMISSION_LABELS: Record<string, string> = {
  can_create_requisition: 'Créer une réquisition',
  can_verify_technical: 'Avis technique',
  can_validate_final: 'Validation finale',
  can_execute_payment: 'Exécuter la sortie de fonds',
  can_manage_users: 'Gérer les utilisateurs',
  can_edit_settings: 'Gérer les paramètres',
  can_view_reports: 'Accès aux rapports',
}

interface MatrixProps {
  roles: RoleInfo[]
  permissions: PermissionInfo[]
  matrix: Record<string, Record<string, boolean>>
  onToggle: (roleId: number, permissionCode: string) => void
  onSave: () => void
  onAddRole: () => void
  onDeleteRole: (roleId: number) => void
  onUpdateRoleLabel: (roleId: number, label: string) => void
  saving: boolean
  dirty: boolean
}

export default function PermissionsMatrix({
  roles,
  permissions,
  matrix,
  onToggle,
  onSave,
  onAddRole,
  onDeleteRole,
  onUpdateRoleLabel,
  saving,
  dirty,
}: MatrixProps) {
  const getPermissionLabel = (perm: PermissionInfo) =>
    perm.description || PERMISSION_LABELS[perm.code] || perm.code

  return (
    <div className={styles.wrapper}>
      <div className={styles.headerRow}>
        <div>
          <h3 className={styles.title}>Matrice des permissions</h3>
          <p className={styles.subtitle}>Cochez les droits accordés à chaque rôle.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className={styles.secondaryBtn} onClick={onAddRole}>
            + Ajouter un rôle
          </button>
          <button
            type="button"
            className={`${styles.saveBtn} ${dirty ? styles.saveBtnActive : ''}`}
            onClick={onSave}
            disabled={saving}
          >
            {saving ? 'Sauvegarde...' : 'Enregistrer les permissions'}
          </button>
        </div>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Rôle</th>
              {permissions.map((perm) => (
                <th key={perm.code} title={perm.code}>
                  {getPermissionLabel(perm)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id}>
                <td>
                  <div className={styles.roleCell}>
                    <div className={styles.roleCode}>{role.code}</div>
                    <input
                      className={styles.roleInput}
                      value={role.label || ''}
                      onChange={(e) => onUpdateRoleLabel(role.id, e.target.value)}
                      placeholder="Nom du rôle"
                    />
                    {role.code !== 'admin' && (
                      <button
                        type="button"
                        className={styles.deleteBtn}
                        onClick={() => onDeleteRole(role.id)}
                        title="Supprimer le rôle"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </td>
                {permissions.map((perm) => (
                  <td key={`${role.id}-${perm.code}`}>
                    <input
                      type="checkbox"
                      checked={!!matrix[String(role.id)]?.[perm.code]}
                      onChange={() => onToggle(role.id, perm.code)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
