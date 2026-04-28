import { useRef } from 'react'
import styles from './PermissionsMatrix.module.css'
import type { PermissionInfo, RoleInfo } from '../../api/admin'

const PERMISSION_LABELS: Record<string, string> = {
  menu_dashboard: 'Tableau de bord',
  menu_encaissements: 'Encaissements',
  menu_requisitions: 'Réquisitions',
  menu_remboursement_transport: 'Remboursement transport',
  menu_requisitions_ocr: 'Analyse PDF réquisitions',
  menu_validation: 'Validation',
  menu_validation_examens: "Dossiers d'examen",
  menu_sorties_fonds: 'Sorties de fonds',
  menu_cloture_caisse: 'Clôture de caisse',
  menu_budget: 'Budget',
  menu_services: 'Services / portail Commission',
  menu_rapports: 'Rapports',
  menu_audit_logs: 'Audit système',
  menu_experts_comptables: 'Experts-comptables',
  menu_historique_imports: 'Historique des imports',
  menu_settings: 'Paramètres généraux',
  menu_organisation_settings: 'Organisation',
  menu_denominations: 'Configuration billets',
  can_create_requisition: 'Créer une réquisition',
  can_verify_technical: 'Avis technique',
  can_validate_final: 'Validation finale',
  can_execute_payment: 'Exécuter la sortie de fonds',
  can_manage_users: 'Gérer les utilisateurs',
  can_edit_settings: 'Gérer les paramètres',
  can_view_reports: 'Consulter les rapports',
  can_view_all_services: 'Voir toutes les commissions',
}

const MODULE_ORDER = [
  'menu_dashboard',
  'menu_encaissements',
  'menu_requisitions',
  'menu_remboursement_transport',
  'menu_requisitions_ocr',
  'menu_validation',
  'menu_validation_examens',
  'menu_sorties_fonds',
  'menu_cloture_caisse',
  'menu_budget',
  'menu_services',
  'menu_rapports',
  'menu_audit_logs',
  'menu_experts_comptables',
  'menu_historique_imports',
  'menu_settings',
  'menu_organisation_settings',
  'menu_denominations',
]

const ACTION_ORDER = [
  'can_create_requisition',
  'can_verify_technical',
  'can_validate_final',
  'can_execute_payment',
  'can_manage_users',
  'can_edit_settings',
  'can_view_reports',
  'can_view_all_services',
]

const permissionRank = (code: string) => {
  const moduleIndex = MODULE_ORDER.indexOf(code)
  if (moduleIndex >= 0) return moduleIndex
  const actionIndex = ACTION_ORDER.indexOf(code)
  if (actionIndex >= 0) return 1000 + actionIndex
  return 2000 + code.localeCompare('')
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
  const rolePaneRef = useRef<HTMLDivElement | null>(null)
  const tableWrapRef = useRef<HTMLDivElement | null>(null)

  const getPermissionLabel = (perm: PermissionInfo) =>
    perm.description || PERMISSION_LABELS[perm.code] || perm.code
  const getPermissionGroup = (code: string) => code.startsWith('menu_') ? 'Module' : 'Action'
  const orderedPermissions = [...permissions].sort((a, b) => {
    const rankDiff = permissionRank(a.code) - permissionRank(b.code)
    return rankDiff || a.code.localeCompare(b.code)
  })

  const syncVerticalScroll = (source: 'roles' | 'permissions') => {
    const rolePane = rolePaneRef.current
    const tableWrap = tableWrapRef.current
    if (!rolePane || !tableWrap) return
    if (source === 'roles') {
      if (tableWrap.scrollTop !== rolePane.scrollTop) {
        tableWrap.scrollTop = rolePane.scrollTop
      }
      return
    }
    if (rolePane.scrollTop !== tableWrap.scrollTop) {
      rolePane.scrollTop = tableWrap.scrollTop
    }
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.headerRow}>
        <div>
          <h3 className={styles.title}>Matrice des permissions</h3>
          <p className={styles.subtitle}>Cochez d’abord les modules visibles, puis les actions autorisées.</p>
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
      <div className={styles.matrixShell}>
        <div
          ref={rolePaneRef}
          className={styles.rolePane}
          onScroll={() => syncVerticalScroll('roles')}
        >
          <table className={styles.roleTable}>
            <thead>
              <tr>
                <th className={styles.roleHeader}>Rôle</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((role) => (
                <tr key={role.id}>
                  <td className={styles.roleStickyCell}>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div
          ref={tableWrapRef}
          className={styles.tableWrap}
          onScroll={() => syncVerticalScroll('permissions')}
        >
          <table className={styles.table}>
            <thead>
              <tr>
                {orderedPermissions.map((perm) => (
                  <th
                    key={perm.code}
                    title={perm.code}
                    className={`${styles.headerCell} ${styles.permissionHeader}`}
                  >
                    <span className={styles.permissionGroup}>{getPermissionGroup(perm.code)}</span>
                    <span className={styles.headerLabel}>{getPermissionLabel(perm)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {roles.map((role) => (
                <tr key={role.id}>
                  {orderedPermissions.map((perm) => (
                    <td key={`${role.id}-${perm.code}`} className={styles.permissionCell}>
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
      <div className={styles.scrollHint}>
        ← Faites défiler horizontalement pour voir toutes les permissions →
      </div>
    </div>
  )
}
