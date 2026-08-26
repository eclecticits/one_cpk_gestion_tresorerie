// ---------------------------------------------------------------------------
// ONEC Smart - Taxonomie des permissions : Role > Module > Menu > Taches
//
// Genere a partir de :
//   - frontend/src/components/Layout.tsx        (structure reelle du menu lateral)
//   - PermissionsMatrix.tsx (PERMISSION_LABELS, 91 codes) - composant retire
//     depuis que RolePermissionsEditor le remplace ; voir l'historique Git.
//   - backend/app/core/permissions.py           (MODULE_PERMISSION_MAP)
//   - backend/app/modules/secretariat/permissions.py
//   - backend/alembic/versions/*                (codes reellement semes en base)
//
// Regles :
//   * `menuCode` designe le code qui ouvre le menu dans la sidebar ; ce code
//     figure TOUJOURS aussi dans `tasks` (rien n'est perdu, rien n'est duplique).
//   * `deferred: true` = code DELIBEREMENT non seme. La migration
//     20260822_treso_actions pose la regle : « pas de route identifiable => pas
//     de code », parce qu'un code seme mais jamais evalue par l'API est une
//     fausse promesse de securite. Ces entrees documentent l'intention de
//     granularite ; elles ne sont PAS un reste-a-faire. Semer l'un d'eux n'a de
//     sens qu'accompagne, dans le meme lot, de la garde `has_permission(...)`
//     sur la route correspondante.
//   * `hidden: true` = code conserve en base mais non affiche dans la matrice.
//   * Les codes legacy `menu_*` / `can_*` restent la source de verite pour
//     l'ACCES au menu ; les codes `treso.*` ne font qu'AFFINER les actions.
//
// `usableTasks()` (RolePermissionsEditor) n'affiche que les codes presents dans
// le catalogue renvoye par le serveur : une entree `deferred` reste donc
// invisible tant qu'elle n'existe pas en base. Rien a filtrer en plus.
// ---------------------------------------------------------------------------

export type ActionKind =
  | 'read'
  | 'create'
  | 'update'
  | 'delete'
  | 'validate'
  | 'cancel'
  | 'export'
  | 'manage'
  | 'other'

export interface PermissionTask {
  /** Code technique stocke dans la table `permissions`. */
  code: string
  /** Libelle francais affiche dans la matrice. */
  label: string
  /** Nature de l'action, pour le pictogramme / la couleur. */
  kind: ActionKind
  /** true = code volontairement non seme faute de route a garder (voir en-tete). */
  deferred?: boolean
  /** true = code conserve en base mais masque dans l’interface. */
  hidden?: boolean
}

export interface PermissionMenu {
  /** Cle stable, utilisee pour l'etat deplie/replie. */
  key: string
  /** Libelle du menu, tel qu’il apparait dans la barre laterale. */
  label: string
  /** Code qui ouvre le menu (present aussi dans `tasks`). */
  menuCode?: string
  tasks: PermissionTask[]
}

export interface PermissionModule {
  key: string
  label: string
  /** Couleur d’accent du module (reprise de GROUP_CONFIG). */
  color: string
  menus: PermissionMenu[]
}

export const ACTION_KIND_LABELS: Record<ActionKind, string> = {
  read: 'Lire',
  create: 'Créer',
  update: 'Modifier',
  delete: 'Supprimer',
  validate: 'Valider',
  cancel: 'Annuler',
  export: 'Exporter',
  manage: 'Gérer',
  other: 'Autre',
}

export const PERMISSION_TREE: PermissionModule[] = [
  {
    key: 'tresorerie',
    label: 'Trésorerie',
    color: '#166534',
    menus: [
      {
        key: 'dashboard',
        label: 'Tableau de bord',
        menuCode: 'menu_dashboard',
        tasks: [
          { code: 'menu_dashboard', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.dashboard.export', label: 'Exporter le tableau de bord', kind: 'export', deferred: true },
        ],
      },
      {
        key: 'encaissements',
        label: 'Encaissements',
        menuCode: 'menu_encaissements',
        tasks: [
          { code: 'menu_encaissements', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.encaissements.read', label: 'Consulter les encaissements', kind: 'read', deferred: true },
          { code: 'treso.encaissements.create', label: 'Créer un encaissement', kind: 'create' },
          { code: 'treso.encaissements.update', label: 'Modifier un encaissement', kind: 'update', deferred: true },
          { code: 'treso.encaissements.delete', label: 'Supprimer un encaissement', kind: 'delete' },
          { code: 'treso.encaissements.export', label: 'Exporter les encaissements', kind: 'export' },
          { code: 'cancel_encaissement', label: 'Annuler un encaissement', kind: 'cancel' },
        ],
      },
      {
        key: 'requisitions',
        label: 'Réquisitions',
        menuCode: 'menu_requisitions',
        tasks: [
          { code: 'menu_requisitions', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.requisitions.read', label: 'Consulter les réquisitions', kind: 'read', deferred: true },
          { code: 'can_create_requisition', label: 'Créer une réquisition', kind: 'create' },
          { code: 'treso.requisitions.update', label: 'Modifier une réquisition', kind: 'update' },
          { code: 'treso.requisitions.delete', label: 'Supprimer une réquisition', kind: 'delete' },
          { code: 'treso.requisitions.cancel', label: 'Annuler une réquisition', kind: 'cancel', deferred: true },
          { code: 'treso.requisitions.export', label: 'Exporter les réquisitions', kind: 'export' },
        ],
      },
      {
        key: 'remboursement_transport',
        label: 'Remboursement transport',
        menuCode: 'menu_remboursement_transport',
        tasks: [
          { code: 'menu_remboursement_transport', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.remboursement_transport.read', label: 'Consulter les remboursements de transport', kind: 'read', deferred: true },
          { code: 'treso.remboursement_transport.create', label: 'Créer un remboursement de transport', kind: 'create' },
          { code: 'treso.remboursement_transport.update', label: 'Modifier un remboursement de transport', kind: 'update', deferred: true },
          { code: 'treso.remboursement_transport.delete', label: 'Supprimer un remboursement de transport', kind: 'delete', deferred: true },
          { code: 'treso.remboursement_transport.validate', label: 'Valider un remboursement de transport', kind: 'validate', deferred: true },
          { code: 'treso.remboursement_transport.export', label: 'Exporter les remboursements de transport', kind: 'export', deferred: true },
        ],
      },
      {
        key: 'requisitions_ocr',
        label: 'Analyse PDF réquisitions',
        menuCode: 'menu_requisitions_ocr',
        tasks: [
          { code: 'menu_requisitions_ocr', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.requisitions_ocr.read', label: 'Consulter les analyses PDF', kind: 'read', deferred: true },
          { code: 'treso.requisitions_ocr.create', label: 'Lancer une analyse PDF', kind: 'create', deferred: true },
          { code: 'treso.requisitions_ocr.delete', label: 'Supprimer une analyse PDF', kind: 'delete', deferred: true },
        ],
      },
      {
        key: 'validation',
        label: 'Validation',
        menuCode: 'menu_validation',
        tasks: [
          { code: 'menu_validation', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.validation.read', label: 'Consulter la file de validation', kind: 'read', deferred: true },
          { code: 'can_verify_technical', label: 'Avis technique', kind: 'validate' },
          { code: 'can_validate_final', label: 'Validation finale', kind: 'validate' },
          { code: 'treso.validation.cancel', label: 'Retirer une validation', kind: 'cancel', deferred: true },
          { code: 'treso.validation.export', label: 'Exporter la file de validation', kind: 'export', deferred: true },
        ],
      },
      {
        key: 'validation_examens',
        label: 'Dossiers d\'examen',
        menuCode: 'menu_validation_examens',
        tasks: [
          { code: 'menu_validation_examens', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.validation_examens.read', label: 'Consulter les dossiers d\'examen', kind: 'read' },
          { code: 'treso.validation_examens.create', label: 'Créer un dossier d\'examen', kind: 'create' },
          { code: 'treso.validation_examens.update', label: 'Modifier un dossier d\'examen', kind: 'update' },
          { code: 'treso.validation_examens.delete', label: 'Supprimer un dossier d\'examen', kind: 'delete' },
          { code: 'treso.validation_examens.validate', label: 'Valider un dossier d\'examen', kind: 'validate' },
          { code: 'treso.validation_examens.export', label: 'Exporter les dossiers d\'examen', kind: 'export' },
        ],
      },
      {
        key: 'sorties_fonds',
        label: 'Sorties de fonds',
        menuCode: 'menu_sorties_fonds',
        tasks: [
          { code: 'menu_sorties_fonds', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.sorties_fonds.read', label: 'Consulter les sorties de fonds', kind: 'read', deferred: true },
          { code: 'treso.sorties_fonds.create', label: 'Créer une sortie de fonds', kind: 'create' },
          { code: 'treso.sorties_fonds.update', label: 'Modifier une sortie de fonds', kind: 'update', deferred: true },
          { code: 'treso.sorties_fonds.delete', label: 'Supprimer une sortie de fonds', kind: 'delete', deferred: true },
          { code: 'can_execute_payment', label: 'Exécuter la sortie de fonds', kind: 'validate' },
          { code: 'can_authorize_disbursement', label: 'Autoriser un ordre de décaissement', kind: 'validate' },
          { code: 'can_direct_disbursement', label: 'Programmer une sortie directe', kind: 'validate' },
          { code: 'cancel_sortie_fonds', label: 'Annuler une sortie de fonds', kind: 'cancel' },
          { code: 'treso.sorties_fonds.export', label: 'Exporter les sorties de fonds', kind: 'export' },
        ],
      },
      {
        key: 'cloture_caisse',
        label: 'Clôture de caisse',
        menuCode: 'menu_cloture_caisse',
        tasks: [
          { code: 'menu_cloture_caisse', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.cloture_caisse.read', label: 'Consulter les clôtures de caisse', kind: 'read', deferred: true },
          { code: 'treso.cloture_caisse.create', label: 'Créer une clôture de caisse', kind: 'create', deferred: true },
          { code: 'treso.cloture_caisse.validate', label: 'Valider une clôture de caisse', kind: 'validate', deferred: true },
          { code: 'treso.cloture_caisse.cancel', label: 'Rouvrir une clôture de caisse', kind: 'cancel', deferred: true },
          { code: 'treso.cloture_caisse.export', label: 'Exporter les clôtures de caisse', kind: 'export' },
        ],
      },
      {
        key: 'budget',
        label: 'Budget',
        menuCode: 'menu_budget',
        tasks: [
          { code: 'menu_budget', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.budget.read', label: 'Consulter le budget', kind: 'read', deferred: true },
          { code: 'treso.budget.create', label: 'Créer une ligne budgétaire', kind: 'create' },
          { code: 'treso.budget.update', label: 'Modifier une ligne budgétaire', kind: 'update' },
          { code: 'treso.budget.delete', label: 'Supprimer une ligne budgétaire', kind: 'delete' },
          { code: 'treso.budget.validate', label: 'Valider le budget', kind: 'validate' },
          { code: 'treso.budget.export', label: 'Exporter le budget', kind: 'export' },
        ],
      },
      {
        key: 'rapports',
        label: 'Rapports',
        menuCode: 'menu_rapports',
        tasks: [
          { code: 'menu_rapports', label: 'Accès au menu', kind: 'other' },
          { code: 'can_view_reports', label: 'Consulter les rapports', kind: 'read' },
          { code: 'treso.rapports.export', label: 'Exporter les rapports', kind: 'export', deferred: true },
        ],
      },
      {
        key: 'experts_comptables',
        label: 'Experts-comptables',
        menuCode: 'menu_experts_comptables',
        tasks: [
          { code: 'menu_experts_comptables', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.experts_comptables.read', label: 'Consulter les experts-comptables', kind: 'read' },
          { code: 'treso.experts_comptables.create', label: 'Créer un expert-comptable', kind: 'create', deferred: true },
          { code: 'treso.experts_comptables.update', label: 'Modifier un expert-comptable', kind: 'update', deferred: true },
          { code: 'treso.experts_comptables.delete', label: 'Supprimer un expert-comptable', kind: 'delete', deferred: true },
          { code: 'treso.experts_comptables.export', label: 'Exporter la liste des experts', kind: 'export' },
        ],
      },
      {
        key: 'historique_imports',
        label: 'Historique des imports',
        menuCode: 'menu_historique_imports',
        tasks: [
          { code: 'menu_historique_imports', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.historique_imports.read', label: 'Consulter l\'historique des imports', kind: 'read' },
          { code: 'treso.historique_imports.create', label: 'Lancer un import d\'experts', kind: 'create' },
          { code: 'treso.historique_imports.delete', label: 'Purger un import', kind: 'delete', deferred: true },
        ],
      },
      {
        key: 'services',
        label: 'Unités opérationnelles',
        menuCode: 'menu_services',
        tasks: [
          { code: 'menu_services', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.services.read', label: 'Consulter les unités opérationnelles', kind: 'read', deferred: true },
          { code: 'treso.services.create', label: 'Créer une unité opérationnelle', kind: 'create' },
          { code: 'treso.services.update', label: 'Modifier une unité opérationnelle', kind: 'update' },
          { code: 'treso.services.delete', label: 'Supprimer une unité opérationnelle', kind: 'delete', deferred: true },
        ],
      },
      {
        key: 'administration_users',
        label: 'Administration — Utilisateurs & accès',
        tasks: [
          { code: 'can_manage_users', label: 'Gérer les utilisateurs', kind: 'manage' },
        ],
      },
      {
        key: 'audit_logs',
        label: 'Audit système',
        menuCode: 'menu_audit_logs',
        tasks: [
          { code: 'menu_audit_logs', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.audit_logs.export', label: 'Exporter les journaux d\'audit', kind: 'export' },
        ],
      },
      {
        key: 'settings',
        label: 'Paramètres généraux',
        menuCode: 'menu_settings',
        tasks: [
          { code: 'menu_settings', label: 'Accès au menu', kind: 'other' },
          { code: 'treso.settings.read', label: 'Consulter les paramètres', kind: 'read', deferred: true },
          { code: 'can_edit_settings', label: 'Gérer les paramètres', kind: 'manage' },
        ],
      },
      {
        // Pas de `menuCode` : les notifications ne sont pas une entrée de la barre
        // latérale mais une section de Paramètres. L'accès y est donc gouverné par
        // `menu_settings`, et ces quatre droits n'affinent que ce qu'on peut y faire.
        key: 'notifications',
        label: 'Notifications WhatsApp',
        tasks: [
          { code: 'treso.notifications.read', label: 'Consulter la configuration', kind: 'read' },
          { code: 'treso.notifications.update', label: 'Modifier la configuration et les destinataires', kind: 'update' },
          { code: 'treso.notifications.history', label: "Consulter l'historique des envois", kind: 'read' },
          { code: 'treso.notifications.test', label: 'Envoyer un test et renvoyer un message', kind: 'other' },
        ],
      },
      {
        key: 'organisation_settings',
        label: 'Organisation',
        menuCode: 'menu_organisation_settings',
        tasks: [
          { code: 'menu_organisation_settings', label: 'Accès au menu', kind: 'other' },
        ],
      },
      {
        key: 'denominations',
        label: 'Configuration billets',
        menuCode: 'menu_denominations',
        tasks: [
          { code: 'menu_denominations', label: 'Accès au menu', kind: 'other' },
        ],
      },
      {
        key: 'transversal',
        label: 'Portée & droits transversaux',
        tasks: [
          { code: 'can_view_all_services', label: 'Voir toutes les unités opérationnelles', kind: 'read' },
          { code: 'view_cancelled_financial_operations', label: 'Voir opérations annulées', kind: 'read' },
        ],
      },
    ],
  },
  {
    key: 'rh',
    label: 'Ressources Humaines',
    color: '#1e40af',
    menus: [
      {
        key: 'rh_dashboard',
        label: 'Vue d\'ensemble',
        menuCode: 'rh.dashboard.view',
        tasks: [
          { code: 'rh.dashboard.view', label: 'Vue d\'ensemble RH', kind: 'read' },
        ],
      },
      {
        key: 'rh_employees',
        label: 'Employés',
        menuCode: 'rh.employees.view',
        tasks: [
          { code: 'rh.employees.view', label: 'Consulter le personnel', kind: 'read' },
          { code: 'rh.employees.create', label: 'Créer des agents', kind: 'create' },
          { code: 'rh.employees.update', label: 'Modifier des agents', kind: 'update' },
          { code: 'rh.employees.archive', label: 'Archiver des agents', kind: 'delete' },
          { code: 'rh.salaries.view', label: 'Consulter les salaires', kind: 'read' },
        ],
      },
      {
        key: 'rh_attendance',
        label: 'Temps & présences',
        menuCode: 'rh.attendance.view',
        tasks: [
          { code: 'rh.attendance.view', label: 'Consulter les présences', kind: 'read' },
          { code: 'rh.attendance.manage', label: 'Gérer les présences', kind: 'manage' },
          { code: 'rh.attendance.correct', label: 'Corriger les pointages', kind: 'update' },
          { code: 'rh.attendance.export', label: 'Exporter les présences', kind: 'export' },
        ],
      },
      {
        key: 'rh_leave',
        label: 'Congés',
        menuCode: 'rh.leave.view',
        tasks: [
          { code: 'rh.leave.view', label: 'Consulter les congés', kind: 'read' },
          { code: 'rh.leave.request', label: 'Demander un congé', kind: 'create' },
          { code: 'rh.leave.approve', label: 'Approuver les congés', kind: 'validate' },
        ],
      },
      {
        key: 'rh_contracts',
        label: 'Contrats',
        menuCode: 'rh.contracts.view',
        tasks: [
          { code: 'rh.contracts.view', label: 'Consulter les contrats', kind: 'read' },
          { code: 'rh.contracts.manage', label: 'Gérer les contrats', kind: 'manage' },
        ],
      },
      {
        key: 'rh_payroll',
        label: 'Paie',
        menuCode: 'rh.payroll.view',
        tasks: [
          { code: 'rh.payroll.view', label: 'Consulter la paie', kind: 'read' },
          { code: 'rh.payroll.prepare', label: 'Préparer la paie', kind: 'create' },
          { code: 'rh.payroll.validate', label: 'Valider la paie', kind: 'validate' },
        ],
      },
      {
        key: 'rh_payslips',
        label: 'Bulletins de paie',
        menuCode: 'rh.payslips.view',
        tasks: [
          { code: 'rh.payslips.view', label: 'Bulletins de paie', kind: 'read' },
          { code: 'rh.payslips.generate', label: 'Générer les bulletins', kind: 'create' },
        ],
      },
      {
        key: 'rh_documents',
        label: 'Documents',
        menuCode: 'rh.documents.view',
        tasks: [
          { code: 'rh.documents.view', label: 'Documents RH', kind: 'read' },
          { code: 'rh.documents.manage', label: 'Gérer les documents RH', kind: 'manage' },
        ],
      },
      {
        key: 'rh_evaluations',
        label: 'Évaluations',
        menuCode: 'rh.evaluations.view',
        tasks: [
          { code: 'rh.evaluations.view', label: 'Consulter les évaluations', kind: 'read' },
          { code: 'rh.evaluations.manage', label: 'Gérer les évaluations', kind: 'manage' },
        ],
      },
      {
        key: 'rh_sanctions',
        label: 'Sanctions',
        menuCode: 'rh.sanctions.view',
        tasks: [
          { code: 'rh.sanctions.view', label: 'Consulter les sanctions', kind: 'read' },
          { code: 'rh.sanctions.manage', label: 'Gérer les sanctions', kind: 'manage' },
        ],
      },
      {
        key: 'rh_reports',
        label: 'Rapports',
        menuCode: 'rh.reports.view',
        tasks: [
          { code: 'rh.reports.view', label: 'Rapports RH', kind: 'read' },
        ],
      },
      {
        key: 'rh_settings',
        label: 'Configuration',
        menuCode: 'rh.settings.manage',
        tasks: [
          { code: 'rh.settings.manage', label: 'Configuration RH', kind: 'manage' },
        ],
      },
    ],
  },
  {
    key: 'secretariat',
    label: 'Secrétariat',
    color: '#5b21b6',
    menus: [
      {
        key: 'sec_module',
        label: 'Accès au module',
        menuCode: 'menu_secretariat',
        tasks: [
          { code: 'menu_secretariat', label: 'Accès au module', kind: 'other' },
        ],
      },
      {
        key: 'sec_dashboard',
        label: 'Tableau de bord',
        menuCode: 'secretariat.view',
        tasks: [
          { code: 'secretariat.view', label: 'Tableau de bord', kind: 'read' },
        ],
      },
      {
        key: 'sec_courrier',
        label: 'Agent Courrier',
        menuCode: 'secretariat.use_agent_courrier',
        tasks: [
          { code: 'secretariat.use_agent_courrier', label: 'Agent Courrier', kind: 'other', hidden: true },
          { code: 'secretariat.read_mail', label: 'Lire les mails', kind: 'read' },
          { code: 'secretariat.generate_mail_summary', label: 'Résumés courrier', kind: 'other' },
          { code: 'secretariat.generate_mail_draft', label: 'Projets de réponse', kind: 'create' },
          { code: 'secretariat.approve_mail_draft', label: 'Approuver les projets', kind: 'validate' },
          { code: 'secretariat.create_gmail_draft', label: 'Créer brouillon Gmail', kind: 'create' },
        ],
      },
      {
        key: 'sec_reunion',
        label: 'Agent Réunion',
        menuCode: 'secretariat.use_agent_reunion',
        tasks: [
          { code: 'secretariat.use_agent_reunion', label: 'Agent Réunion', kind: 'other', hidden: true },
          { code: 'secretariat.manage_meetings', label: 'Gérer les réunions', kind: 'manage' },
          { code: 'secretariat.generate_meeting_documents', label: 'Documents de réunion', kind: 'create' },
          { code: 'secretariat.submit_meeting_minutes', label: 'PV de réunion', kind: 'create' },
        ],
      },
      {
        key: 'sec_agenda',
        label: 'Agent Agenda',
        menuCode: 'secretariat.use_agent_agenda',
        tasks: [
          { code: 'secretariat.use_agent_agenda', label: 'Agent Agenda', kind: 'other', hidden: true },
          { code: 'secretariat.view_agenda', label: 'Consulter l\'agenda', kind: 'read' },
          { code: 'secretariat.manage_agenda', label: 'Gérer l\'agenda', kind: 'manage' },
          { code: 'secretariat.manage_agenda_reminders', label: 'Rappels agenda', kind: 'manage' },
        ],
      },
      {
        key: 'sec_documents',
        label: 'Agent Documents',
        menuCode: 'secretariat.use_agent_documents',
        tasks: [
          { code: 'secretariat.use_agent_documents', label: 'Agent Documents', kind: 'other', hidden: true },
          { code: 'secretariat.view_documents', label: 'Consulter les documents', kind: 'read' },
          { code: 'secretariat.manage_documents', label: 'Gérer les documents', kind: 'manage' },
          { code: 'secretariat.generate_document_summary', label: 'Résumés de documents', kind: 'other' },
          { code: 'secretariat.submit_document_synthesis', label: 'Fiches synthèse', kind: 'create' },
        ],
      },
      {
        key: 'sec_tableau',
        label: 'Agent Tableau',
        menuCode: 'secretariat.tableau.view',
        tasks: [
          { code: 'secretariat.tableau.view', label: 'Consulter le tableau', kind: 'read' },
          { code: 'secretariat.tableau.import', label: 'Importer un fichier Excel', kind: 'create' },
          { code: 'secretariat.tableau.analyze', label: 'Lancer l\'analyse', kind: 'other' },
          { code: 'secretariat.tableau.compare', label: 'Comparer deux exercices', kind: 'other' },
          { code: 'secretariat.tableau.generate_report', label: 'Générer un rapport', kind: 'create' },
          { code: 'secretariat.tableau.generate_pv', label: 'Générer un procès-verbal', kind: 'create' },
          { code: 'secretariat.tableau.export', label: 'Exporter les résultats', kind: 'export' },
        ],
      },
      {
        key: 'sec_manager',
        label: 'Agent Manager',
        menuCode: 'secretariat.use_agent_manager',
        tasks: [
          { code: 'secretariat.use_agent_manager', label: 'Agent Manager', kind: 'other', hidden: true },
          { code: 'secretariat.view_manager_dashboard', label: 'TDB Agent Manager', kind: 'read' },
          { code: 'secretariat.manage_tasks', label: 'Gérer les tâches', kind: 'manage' },
          { code: 'secretariat.view_pending_approvals', label: 'Validations en attente', kind: 'read' },
        ],
      },
      {
        key: 'sec_validations',
        label: 'Validations',
        menuCode: 'secretariat.view_approvals',
        tasks: [
          { code: 'secretariat.view_approvals', label: 'Demandes d\'approbation', kind: 'read' },
          { code: 'secretariat.create_approval', label: 'Créer une approbation', kind: 'create' },
          { code: 'secretariat.approve_action', label: 'Approuver une action', kind: 'validate' },
          { code: 'secretariat.reject_action', label: 'Rejeter une action', kind: 'validate' },
          { code: 'secretariat.cancel_approval', label: 'Annuler une approbation', kind: 'cancel' },
        ],
      },
      {
        key: 'sec_settings',
        label: 'Paramètres IA',
        menuCode: 'secretariat.manage_ai_settings',
        tasks: [
          { code: 'secretariat.manage_ai_settings', label: 'Paramètres IA', kind: 'manage' },
          { code: 'secretariat.manage_agents', label: 'Gérer les agents', kind: 'manage' },
          { code: 'secretariat.manage_oauth', label: 'Connexions OAuth', kind: 'manage' },
          { code: 'secretariat.view_audit_logs', label: 'Journaux d\'audit', kind: 'read' },
        ],
      },
    ],
  },
  {
    key: 'comptabilite',
    label: 'Comptabilité',
    color: '#9a3412',
    menus: [
      {
        key: 'compta_module',
        label: 'Accès au module',
        menuCode: 'menu_comptabilite',
        tasks: [
          { code: 'menu_comptabilite', label: 'Accès au module', kind: 'other' },
        ],
      },
      {
        key: 'compta_ecritures',
        label: 'Écritures',
        menuCode: 'compta.saisie',
        tasks: [
          { code: 'compta.saisie', label: 'Saisir et modifier des écritures en brouillon', kind: 'create' },
          { code: 'compta.validation', label: 'Valider les écritures', kind: 'validate' },
        ],
      },
      {
        key: 'compta_grand_livre',
        label: 'Grand Livre',
        menuCode: 'compta.lecture',
        tasks: [
          { code: 'compta.lecture', label: 'Consulter le Grand Livre et les balances', kind: 'read' },
        ],
      },
      {
        key: 'compta_etats',
        label: 'États financiers',
        menuCode: 'compta.export',
        tasks: [
          { code: 'compta.export', label: 'Exporter les états financiers', kind: 'export' },
        ],
      },
      {
        key: 'compta_parametrage',
        label: 'Paramétrage',
        menuCode: 'compta.parametrage',
        tasks: [
          { code: 'compta.parametrage', label: 'Gérer le plan comptable et les journaux', kind: 'manage' },
          { code: 'compta.cloture', label: 'Ouvrir, clôturer et verrouiller les exercices', kind: 'validate' },
        ],
      },
    ],
  },
]

/** Tous les codes de l’arbre, dans l’ordre d’affichage. */
export const ALL_TREE_CODES: string[] = PERMISSION_TREE.flatMap((m) =>
  m.menus.flatMap((menu) => menu.tasks.map((t) => t.code)),
)

/** Codes volontairement non semes : granularite documentee, pas reste-a-faire. */
export const DEFERRED_PERMISSION_CODES: string[] = PERMISSION_TREE.flatMap((m) =>
  m.menus.flatMap((menu) => menu.tasks.filter((t) => t.deferred).map((t) => t.code)),
)

/** Codes conserves en base mais masques dans la matrice. */
export const HIDDEN_PERMISSION_CODES: string[] = PERMISSION_TREE.flatMap((m) =>
  m.menus.flatMap((menu) => menu.tasks.filter((t) => t.hidden).map((t) => t.code)),
)

export interface PermissionLocation {
  module: PermissionModule
  menu: PermissionMenu
  task: PermissionTask
}

/** Retrouve le module + le menu + la tache d’un code donne. */
export function findPermissionLocation(code: string): PermissionLocation | undefined {
  for (const module of PERMISSION_TREE) {
    for (const menu of module.menus) {
      const task = menu.tasks.find((t) => t.code === code)
      if (task) return { module, menu, task }
    }
  }
  return undefined
}

/**
 * Libelle francais d’un code, avec repli sur la description serveur puis le code.
 * Remplace `PERMISSION_LABELS[perm.code] || perm.description || perm.code`.
 */
export function getPermissionLabel(code: string, fallback?: string | null): string {
  return findPermissionLocation(code)?.task.label ?? fallback ?? code
}

/**
 * Codes presents en base mais absents de l’arbre : a afficher dans un bloc
 * « Non classes » plutot que de les perdre silencieusement.
 */
export function findUnmappedCodes(serverCodes: string[]): string[] {
  const known = new Set(ALL_TREE_CODES)
  return serverCodes.filter((code) => !known.has(code))
}
