from __future__ import annotations


SECRETARIAT_PERMISSIONS = [
    ("menu_secretariat", "Secrétariat - accès au module"),
    ("secretariat.view", "Secrétariat - consulter le module"),
    ("secretariat.tableau.view", "Secrétariat - Tableau : consulter"),
    ("secretariat.tableau.import", "Secrétariat - Tableau : importer un fichier Excel"),
    ("secretariat.tableau.analyze", "Secrétariat - Tableau : lancer l'analyse"),
    ("secretariat.tableau.compare", "Secrétariat - Tableau : comparer deux exercices"),
    ("secretariat.tableau.generate_report", "Secrétariat - Tableau : générer un rapport"),
    ("secretariat.tableau.generate_pv", "Secrétariat - Tableau : générer un procès-verbal"),
    ("secretariat.tableau.export", "Secrétariat - Tableau : exporter les résultats"),
    ("secretariat.use_agent_courrier", "Secrétariat - utiliser l'agent courrier"),
    ("secretariat.use_agent_reunion", "Secrétariat - utiliser l'agent réunion"),
    ("secretariat.use_agent_agenda", "Secrétariat - utiliser l'agent agenda"),
    ("secretariat.use_agent_documents", "Secrétariat - utiliser l'agent documents"),
    ("secretariat.use_agent_manager", "Secrétariat - utiliser l'agent manager"),
    ("secretariat.manage_agents", "Secrétariat - gérer les agents"),
    ("secretariat.manage_ai_settings", "Secrétariat - gérer les paramètres IA"),
    ("secretariat.view_audit_logs", "Secrétariat - consulter les journaux d'audit"),
    ("secretariat.manage_oauth", "Secrétariat - gérer les connexions OAuth"),
    ("secretariat.read_mail", "Secrétariat - lire les mails Gmail"),
    ("secretariat.generate_mail_summary", "Secrétariat - générer les résumés et classifications courrier"),
    ("secretariat.generate_mail_draft", "Secrétariat - générer les projets de réponse courrier"),
    ("secretariat.approve_mail_draft", "Secrétariat - approuver les projets de réponse courrier"),
    ("secretariat.create_gmail_draft", "Secrétariat - créer un brouillon Gmail"),
    ("secretariat.view_manager_dashboard", "Secrétariat - consulter le tableau de bord Agent Manager"),
    ("secretariat.manage_tasks", "Secrétariat - gérer les tâches de suivi"),
    ("secretariat.view_agenda", "Secrétariat - consulter l'agenda"),
    ("secretariat.manage_agenda", "Secrétariat - gérer l'agenda"),
    ("secretariat.manage_agenda_reminders", "Secrétariat - gérer les rappels agenda"),
    ("secretariat.view_documents", "Secrétariat - consulter les documents"),
    ("secretariat.manage_documents", "Secrétariat - gérer les documents"),
    ("secretariat.generate_document_summary", "Secrétariat - générer les résumés de documents"),
    ("secretariat.submit_document_synthesis", "Secrétariat - soumettre les fiches synthèse"),
    ("secretariat.manage_meetings", "Secrétariat - gérer les réunions"),
    ("secretariat.generate_meeting_documents", "Secrétariat - générer les documents de réunion"),
    ("secretariat.submit_meeting_minutes", "Secrétariat - soumettre les PV de réunion"),
    ("secretariat.view_pending_approvals", "Secrétariat - consulter les validations en attente"),
    ("secretariat.view_approvals", "Secrétariat - consulter les demandes d'approbation"),
    ("secretariat.create_approval", "Secrétariat - créer une demande d'approbation"),
    ("secretariat.approve_action", "Secrétariat - approuver une action sensible"),
    ("secretariat.reject_action", "Secrétariat - rejeter une action sensible"),
    ("secretariat.cancel_approval", "Secrétariat - annuler une demande d'approbation"),
]

SECRETARIAT_PERMISSION_CODES = tuple(code for code, _ in SECRETARIAT_PERMISSIONS)
SECRETARIAT_PERMISSION_DESCRIPTIONS = {code: description for code, description in SECRETARIAT_PERMISSIONS}

SECRETARIAT_CORE_PERMISSION_CODES = (
    "menu_secretariat",
    "secretariat.view",
    "secretariat.use_agent_courrier",
    "secretariat.use_agent_reunion",
    "secretariat.use_agent_agenda",
    "secretariat.use_agent_documents",
    "secretariat.use_agent_manager",
    "secretariat.manage_agents",
    "secretariat.manage_ai_settings",
    "secretariat.view_audit_logs",
    "secretariat.manage_oauth",
)

SECRETARIAT_MAIL_PERMISSION_CODES = (
    "secretariat.read_mail",
    "secretariat.generate_mail_summary",
    "secretariat.generate_mail_draft",
    "secretariat.approve_mail_draft",
    "secretariat.create_gmail_draft",
)

SECRETARIAT_MANAGER_PERMISSION_CODES = (
    "secretariat.view_manager_dashboard",
    "secretariat.manage_tasks",
    "secretariat.view_pending_approvals",
)

SECRETARIAT_APPROVAL_PERMISSION_CODES = (
    "secretariat.view_approvals",
    "secretariat.create_approval",
    "secretariat.approve_action",
    "secretariat.reject_action",
    "secretariat.cancel_approval",
)

SECRETARIAT_AGENDA_PERMISSION_CODES = (
    "secretariat.view_agenda",
    "secretariat.manage_agenda",
    "secretariat.manage_agenda_reminders",
)

SECRETARIAT_DOCUMENT_PERMISSION_CODES = (
    "secretariat.view_documents",
    "secretariat.manage_documents",
    "secretariat.generate_document_summary",
    "secretariat.submit_document_synthesis",
)

SECRETARIAT_MEETING_PERMISSION_CODES = (
    "secretariat.manage_meetings",
    "secretariat.generate_meeting_documents",
    "secretariat.submit_meeting_minutes",
)

SECRETARIAT_ROLE_TEMPLATES: dict[str, dict[str, tuple[str, ...] | str]] = {
    "administrateur_secretariat": {
        "label": "Administrateur Secrétariat",
        "permissions": SECRETARIAT_PERMISSION_CODES,
    },
    "agent_courrier": {
        "label": "Agent Courrier",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.use_agent_courrier",
            "secretariat.read_mail",
            "secretariat.generate_mail_summary",
            "secretariat.generate_mail_draft",
            "secretariat.create_gmail_draft",
        ),
    },
    "agent_reunion": {
        "label": "Agent Réunion",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.use_agent_reunion",
            "secretariat.manage_meetings",
            "secretariat.generate_meeting_documents",
            "secretariat.submit_meeting_minutes",
        ),
    },
    "agent_agenda": {
        "label": "Agent Agenda",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.use_agent_agenda",
            "secretariat.view_agenda",
            "secretariat.manage_agenda",
            "secretariat.manage_agenda_reminders",
        ),
    },
    "agent_documents": {
        "label": "Agent Documents",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.use_agent_documents",
            "secretariat.view_documents",
            "secretariat.manage_documents",
            "secretariat.generate_document_summary",
            "secretariat.submit_document_synthesis",
        ),
    },
    "validateur": {
        "label": "Validateur",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.view_approvals",
            "secretariat.view_pending_approvals",
            "secretariat.approve_action",
            "secretariat.reject_action",
        ),
    },
    "auditeur": {
        "label": "Auditeur",
        "permissions": (
            "menu_secretariat",
            "secretariat.view",
            "secretariat.view_audit_logs",
        ),
    },
}

SECRETARIAT_ROLE_PERMISSION_MATRIX: dict[str, tuple[str, ...]] = {
    role_code: tuple(template["permissions"]) for role_code, template in SECRETARIAT_ROLE_TEMPLATES.items()
}


SECRETARIAT_TABLEAU_PERMISSION_CODES = (
    "secretariat.tableau.view",
    "secretariat.tableau.import",
    "secretariat.tableau.analyze",
    "secretariat.tableau.compare",
    "secretariat.tableau.generate_report",
    "secretariat.tableau.generate_pv",
    "secretariat.tableau.export",
)

AGENT_TYPE_PERMISSIONS = {
    "courrier": "secretariat.use_agent_courrier",
    "reunion": "secretariat.use_agent_reunion",
    "agenda": "secretariat.use_agent_agenda",
    "documents": "secretariat.use_agent_documents",
    "manager": "secretariat.use_agent_manager",
    "tableau": "secretariat.tableau.view",
}
