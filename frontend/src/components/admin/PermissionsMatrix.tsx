import { useRef, useState } from 'react'
import styles from './PermissionsMatrix.module.css'
import type { PermissionInfo, RoleInfo } from '../../api/admin'

// ─── Labels ──────────────────────────────────────────────────────────────────

const PERMISSION_LABELS: Record<string, string> = {
  // Trésorerie — menus
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
  menu_services: 'Services / Commission',
  menu_rapports: 'Rapports',
  menu_audit_logs: 'Audit système',
  menu_experts_comptables: 'Experts-comptables',
  menu_historique_imports: 'Historique des imports',
  menu_settings: 'Paramètres généraux',
  menu_organisation_settings: 'Organisation',
  menu_denominations: 'Configuration billets',
  // Trésorerie — actions
  can_create_requisition: 'Créer une réquisition',
  can_verify_technical: 'Avis technique',
  can_validate_final: 'Validation finale',
  can_execute_payment: 'Exécuter la sortie de fonds',
  cancel_encaissement: 'Annuler un encaissement',
  cancel_sortie_fonds: 'Annuler une sortie de fonds',
  view_cancelled_financial_operations: 'Voir opérations annulées',
  can_manage_users: 'Gérer les utilisateurs',
  can_edit_settings: 'Gérer les paramètres',
  can_view_reports: 'Consulter les rapports',
  can_view_all_services: 'Voir toutes les commissions',
  // Ressources Humaines
  'rh.dashboard.view': 'Vue d\'ensemble RH',
  'rh.employees.view': 'Consulter le personnel',
  'rh.employees.create': 'Créer des agents',
  'rh.employees.update': 'Modifier des agents',
  'rh.employees.archive': 'Archiver des agents',
  'rh.contracts.view': 'Consulter les contrats',
  'rh.contracts.manage': 'Gérer les contrats',
  'rh.attendance.view': 'Consulter les présences',
  'rh.attendance.manage': 'Gérer les présences',
  'rh.leave.view': 'Consulter les congés',
  'rh.leave.request': 'Demander un congé',
  'rh.leave.approve': 'Approuver les congés',
  'rh.payroll.view': 'Consulter la paie',
  'rh.payroll.prepare': 'Préparer la paie',
  'rh.payroll.validate': 'Valider la paie',
  'rh.payslips.view': 'Bulletins de paie',
  'rh.payslips.generate': 'Générer les bulletins',
  'rh.documents.view': 'Documents RH',
  'rh.documents.manage': 'Gérer les documents RH',
  'rh.evaluations.view': 'Consulter les évaluations',
  'rh.evaluations.manage': 'Gérer les évaluations',
  'rh.sanctions.view': 'Consulter les sanctions',
  'rh.sanctions.manage': 'Gérer les sanctions',
  'rh.reports.view': 'Rapports RH',
  'rh.settings.manage': 'Configuration RH',
  'rh.salaries.view': 'Consulter les salaires',
  // Secrétariat
  menu_secretariat: 'Accès au module',
  'secretariat.view': 'Tableau de bord',
  'secretariat.use_agent_courrier': 'Agent Courrier',
  'secretariat.use_agent_reunion': 'Agent Réunion',
  'secretariat.use_agent_agenda': 'Agent Agenda',
  'secretariat.use_agent_documents': 'Agent Documents',
  'secretariat.use_agent_manager': 'Agent Manager',
  'secretariat.manage_agents': 'Gérer les agents',
  'secretariat.manage_ai_settings': 'Paramètres IA',
  'secretariat.view_audit_logs': 'Journaux d\'audit',
  'secretariat.manage_oauth': 'Connexions OAuth',
  'secretariat.read_mail': 'Lire les mails',
  'secretariat.generate_mail_summary': 'Résumés courrier',
  'secretariat.generate_mail_draft': 'Projets de réponse',
  'secretariat.approve_mail_draft': 'Approuver les projets',
  'secretariat.create_gmail_draft': 'Créer brouillon Gmail',
  'secretariat.view_manager_dashboard': 'TDB Agent Manager',
  'secretariat.manage_tasks': 'Gérer les tâches',
  'secretariat.view_agenda': "Consulter l'agenda",
  'secretariat.manage_agenda': "Gérer l'agenda",
  'secretariat.manage_agenda_reminders': 'Rappels agenda',
  'secretariat.view_documents': 'Consulter les documents',
  'secretariat.manage_documents': 'Gérer les documents',
  'secretariat.generate_document_summary': 'Résumés de documents',
  'secretariat.submit_document_synthesis': 'Fiches synthèse',
  'secretariat.manage_meetings': 'Gérer les réunions',
  'secretariat.generate_meeting_documents': 'Documents de réunion',
  'secretariat.submit_meeting_minutes': 'PV de réunion',
  'secretariat.view_pending_approvals': 'Validations en attente',
  'secretariat.view_approvals': "Demandes d'approbation",
  'secretariat.create_approval': "Créer une approbation",
  'secretariat.approve_action': 'Approuver une action',
  'secretariat.reject_action': 'Rejeter une action',
  'secretariat.cancel_approval': "Annuler une approbation",
}

// ─── Module groups ────────────────────────────────────────────────────────────

type ModuleGroup = 'TREASURY_MENUS' | 'TREASURY_ACTIONS' | 'HR' | 'SECRETARIAT'

const GROUP_CONFIG: Record<ModuleGroup, { label: string; color: string; bg: string; text: string; badgeBg: string }> = {
  TREASURY_MENUS: {
    label: 'Trésorerie — Menus',
    color: '#166534',
    bg: '#f0fdf4',
    text: '#14532d',
    badgeBg: '#dcfce7',
  },
  TREASURY_ACTIONS: {
    label: 'Trésorerie — Actions',
    color: '#9a3412',
    bg: '#fff7ed',
    text: '#7c2d12',
    badgeBg: '#ffedd5',
  },
  HR: {
    label: 'Ressources Humaines',
    color: '#1e40af',
    bg: '#eff6ff',
    text: '#1e3a8a',
    badgeBg: '#dbeafe',
  },
  SECRETARIAT: {
    label: 'Secrétariat',
    color: '#5b21b6',
    bg: '#f5f3ff',
    text: '#4c1d95',
    badgeBg: '#ede9fe',
  },
}

const GROUP_ORDER: ModuleGroup[] = ['TREASURY_MENUS', 'TREASURY_ACTIONS', 'HR', 'SECRETARIAT']

function getModuleGroup(code: string): ModuleGroup {
  if (code.startsWith('rh.')) return 'HR'
  if (code.startsWith('secretariat.')) return 'SECRETARIAT'
  if (
    code.startsWith('can_') ||
    code.startsWith('cancel_') ||
    code.startsWith('view_cancelled')
  )
    return 'TREASURY_ACTIONS'
  return 'TREASURY_MENUS'
}

// ─── Sort order within each group ────────────────────────────────────────────

const TREASURY_MENUS_ORDER = [
  'menu_dashboard', 'menu_encaissements', 'menu_requisitions',
  'menu_remboursement_transport', 'menu_requisitions_ocr',
  'menu_validation', 'menu_validation_examens',
  'menu_sorties_fonds', 'menu_cloture_caisse', 'menu_budget',
  'menu_services', 'menu_rapports', 'menu_audit_logs',
  'menu_experts_comptables', 'menu_historique_imports',
  'menu_settings', 'menu_organisation_settings', 'menu_denominations',
  'menu_secretariat',
]

const TREASURY_ACTIONS_ORDER = [
  'can_create_requisition', 'can_verify_technical', 'can_validate_final',
  'can_execute_payment', 'cancel_encaissement', 'cancel_sortie_fonds',
  'view_cancelled_financial_operations', 'can_manage_users',
  'can_edit_settings', 'can_view_reports', 'can_view_all_services',
]

const HR_ORDER = [
  'rh.dashboard.view',
  'rh.employees.view', 'rh.employees.create', 'rh.employees.update', 'rh.employees.archive',
  'rh.contracts.view', 'rh.contracts.manage',
  'rh.attendance.view', 'rh.attendance.manage',
  'rh.leave.view', 'rh.leave.request', 'rh.leave.approve',
  'rh.payroll.view', 'rh.payroll.prepare', 'rh.payroll.validate',
  'rh.payslips.view', 'rh.payslips.generate',
  'rh.salaries.view',
  'rh.documents.view', 'rh.documents.manage',
  'rh.evaluations.view', 'rh.evaluations.manage',
  'rh.sanctions.view', 'rh.sanctions.manage',
  'rh.reports.view',
  'rh.settings.manage',
]

const SECRETARIAT_ORDER = [
  'menu_secretariat',
  'secretariat.view',
  'secretariat.use_agent_courrier', 'secretariat.use_agent_reunion',
  'secretariat.use_agent_agenda', 'secretariat.use_agent_documents',
  'secretariat.use_agent_manager', 'secretariat.manage_agents',
  'secretariat.manage_ai_settings', 'secretariat.view_audit_logs',
  'secretariat.manage_oauth',
  'secretariat.read_mail', 'secretariat.generate_mail_summary',
  'secretariat.generate_mail_draft', 'secretariat.approve_mail_draft',
  'secretariat.create_gmail_draft',
  'secretariat.view_manager_dashboard', 'secretariat.manage_tasks',
  'secretariat.view_agenda', 'secretariat.manage_agenda', 'secretariat.manage_agenda_reminders',
  'secretariat.view_documents', 'secretariat.manage_documents',
  'secretariat.generate_document_summary', 'secretariat.submit_document_synthesis',
  'secretariat.manage_meetings', 'secretariat.generate_meeting_documents',
  'secretariat.submit_meeting_minutes',
  'secretariat.view_pending_approvals', 'secretariat.view_approvals',
  'secretariat.create_approval', 'secretariat.approve_action',
  'secretariat.reject_action', 'secretariat.cancel_approval',
]

const WITHIN_GROUP_ORDER: Record<ModuleGroup, string[]> = {
  TREASURY_MENUS: TREASURY_MENUS_ORDER,
  TREASURY_ACTIONS: TREASURY_ACTIONS_ORDER,
  HR: HR_ORDER,
  SECRETARIAT: SECRETARIAT_ORDER,
}

function permissionSortKey(code: string): [number, number] {
  const group = getModuleGroup(code)
  const groupRank = GROUP_ORDER.indexOf(group)
  const withinRank = WITHIN_GROUP_ORDER[group].indexOf(code)
  return [groupRank, withinRank >= 0 ? withinRank : 9999]
}

// ─── Component ───────────────────────────────────────────────────────────────

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
  const [activeGroup, setActiveGroup] = useState<ModuleGroup>('TREASURY_MENUS')

  const getPermissionLabel = (perm: PermissionInfo) =>
    PERMISSION_LABELS[perm.code] || perm.description || perm.code

  const orderedRoles = [...roles].sort((a, b) =>
    (a.label || a.code || '').trim().localeCompare((b.label || b.code || '').trim(), 'fr')
  )

  const allPermissions = [...permissions].sort((a, b) => {
    const [gA, wA] = permissionSortKey(a.code)
    const [gB, wB] = permissionSortKey(b.code)
    return gA !== gB ? gA - gB : wA !== wB ? wA - wB : a.code.localeCompare(b.code)
  })

  const orderedPermissions = allPermissions.filter(p => getModuleGroup(p.code) === activeGroup)

  const syncVerticalScroll = (source: 'roles' | 'permissions') => {
    const rolePane = rolePaneRef.current
    const tableWrap = tableWrapRef.current
    if (!rolePane || !tableWrap) return
    if (source === 'roles') {
      if (tableWrap.scrollTop !== rolePane.scrollTop) tableWrap.scrollTop = rolePane.scrollTop
    } else {
      if (rolePane.scrollTop !== tableWrap.scrollTop) rolePane.scrollTop = tableWrap.scrollTop
    }
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.headerRow}>
        <div>
          <h3 className={styles.title}>Matrice des permissions</h3>
          <p className={styles.subtitle}>
            Cochez d'abord les modules visibles, puis les actions autorisées par module.
          </p>
          <div className={styles.tabs}>
            {GROUP_ORDER.map(g => {
              const cfg = GROUP_CONFIG[g]
              const isActive = g === activeGroup
              const count = allPermissions.filter(p => getModuleGroup(p.code) === g).length
              return (
                <button
                  key={g}
                  type="button"
                  className={`${styles.tab} ${isActive ? styles.tabActive : ''}`}
                  style={isActive ? {
                    background: cfg.badgeBg,
                    color: cfg.text,
                    borderColor: cfg.color,
                  } : undefined}
                  onClick={() => setActiveGroup(g)}
                >
                  {cfg.label}
                  <span className={styles.tabCount}>{count}</span>
                </button>
              )
            })}
          </div>
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
        {/* ── Role pane (left, sticky) ── */}
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
              {orderedRoles.map(role => (
                <tr key={role.id}>
                  <td className={styles.roleStickyCell}>
                    <div className={styles.roleCell}>
                      <div className={styles.roleCode}>{role.code}</div>
                      <input
                        className={styles.roleInput}
                        value={role.label || ''}
                        onChange={e => onUpdateRoleLabel(role.id, e.target.value)}
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

        {/* ── Permissions table (right, scrollable) ── */}
        <div
          ref={tableWrapRef}
          className={styles.tableWrap}
          onScroll={() => syncVerticalScroll('permissions')}
        >
          <table className={styles.table}>
            <thead>
              <tr>
                {orderedPermissions.map(perm => {
                  const cfg = GROUP_CONFIG[activeGroup]
                  return (
                    <th
                      key={perm.code}
                      title={perm.code}
                      className={`${styles.headerCell} ${styles.permissionHeader}`}
                      style={{ borderTop: `3px solid ${cfg.color}` }}
                    >
                      <span className={styles.headerLabel}>{getPermissionLabel(perm)}</span>
                      <code className={styles.permCode}>{perm.code}</code>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {orderedRoles.map(role => (
                <tr key={role.id}>
                  {orderedPermissions.map(perm => {
                    const cfg = GROUP_CONFIG[activeGroup]
                    const isAdmin = role.code === 'admin'
                    const checked = isAdmin || !!matrix[String(role.id)]?.[perm.code]
                    return (
                      <td
                        key={`${role.id}-${perm.code}`}
                        className={styles.permissionCell}
                        style={checked && !isAdmin ? { background: `color-mix(in srgb, ${cfg.bg} 60%, white)` } : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={isAdmin}
                          onChange={() => onToggle(role.id, perm.code)}
                          title={isAdmin ? "L'admin a toujours accès à tout" : undefined}
                          style={checked && !isAdmin ? { accentColor: cfg.color } : undefined}
                        />
                      </td>
                    )
                  })}
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
