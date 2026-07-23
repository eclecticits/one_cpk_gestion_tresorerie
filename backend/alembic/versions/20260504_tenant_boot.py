"""Normalize tenant bootstrap data.

Revision ID: 20260504_tenant_boot
Revises: 20260423_menu_encaissements, 20260430_memfuncsvc
Create Date: 2026-05-04
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260504_tenant_boot"
down_revision = ("20260423_menu_encaissements", "20260430_memfuncsvc")
branch_labels = None
depends_on = None


DEFAULT_SERVICE_CODE = "ADM"
DEFAULT_SERVICE_LABEL = "Administration"
BUDGET_STATUS_ENUM = postgresql.ENUM(
    "Brouillon",
    "Voté",
    "Clôturé",
    name="statut_budget",
    create_type=False,
)

ORG_SETTINGS_TEMPLATE_FIELDS = (
    "max_users",
    "storage_quota_mb",
    "is_ai_enabled",
    "is_mobile_money_enabled",
    "is_audit_logs_enabled",
    "fiscal_year_start",
    "currency_code",
    "theme_primary_color",
    "theme_sidebar_color",
    "theme_sidebar_text_color",
    "theme_sidebar_active_color",
    "theme_accent_color",
    "theme_text_color",
    "theme_button_text_color",
)

PRINT_SETTINGS_TEMPLATE_FIELDS = (
    "pied_de_page_legal",
    "afficher_qr_code",
    "show_header_logo",
    "show_footer_signature",
    "recu_label_signature",
    "sortie_label_signature",
    "sortie_sig_label_1",
    "sortie_sig_label_2",
    "sortie_sig_label_3",
    "sortie_sig_hint",
    "show_sortie_qr",
    "sortie_qr_base_url",
    "show_sortie_watermark",
    "sortie_watermark_text",
    "sortie_watermark_opacity",
    "paper_format",
    "compact_header",
    "req_titre_officiel",
    "req_label_gauche",
    "req_label_droite",
    "trans_titre_officiel",
    "trans_label_gauche",
    "trans_label_droite",
    "encaissement_libelle_presets",
    "default_currency",
    "secondary_currency",
    "exchange_rate",
    "exchange_rate_cdf",
    "exchange_rate_eur",
    "exchange_rate_xof",
    "fiscal_year",
    "budget_alert_threshold",
    "budget_block_overrun",
    "budget_force_roles",
)

DEFAULT_ENCAISSEMENT_LIBELLE_PRESETS = """Cotisation annuelle - Expert-Comptable Cabinet
Cotisation annuelle - Expert-Comptable Indépendant
Cotisation annuelle - Expert-Comptable Salarié
Cotisation annuelle - Stagiaire (SEC)
Arriérés de cotisation
Pénalité de retard - Cotisation
Régularisation cotisation antérieure
Frais de participation - Formation fiscale
Frais de participation - Co-commissariat
Inscription - Séminaire professionnel
Attestation de formation
Contribution FORCO annuelle
Pénalité absence formation obligatoire
Frais d'inscription au Tableau
Frais de réinscription
Frais d'étude de dossier
Délivrance attestation d'inscription
Délivrance duplicata carte professionnelle
Mutation / Transfert de cabinet
Frais de stage professionnel
Délivrance certificat professionnel
Légalisation de signature
Certification de documents
Attestation de conformité
Vente de formulaire officiel
Amende disciplinaire
Pénalité administrative
Régularisation décision disciplinaire
Contribution Commission Tableau
Contribution Commission FORCO
Contribution Commission Discipline
Contribution événement institutionnel
Participation activité spéciale ONEC
Location salle de réunion
Contribution partenaire institutionnel
Sponsoring événement
Subvention reçue
Don volontaire
Recette exceptionnelle
Vente matériel usagé
Remboursement frais
Autres recettes"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _copy_fields(source: dict | None, target: dict, fields: tuple[str, ...]) -> None:
    if not source:
        return
    for field in fields:
        target[field] = source[field]


def _clone_budget_structure(
    conn,
    budget_exercices,
    budget_postes,
    *,
    source_org_id: int,
    target_org_id: int,
) -> None:
    target_exists = conn.execute(
        sa.select(budget_exercices.c.id).where(budget_exercices.c.organisation_id == target_org_id).limit(1)
    ).scalar_one_or_none()
    if target_exists is not None:
        return

    exercices = conn.execute(
        sa.select(
            budget_exercices.c.id,
            budget_exercices.c.annee,
            budget_exercices.c.statut,
        ).where(budget_exercices.c.organisation_id == source_org_id)
    ).mappings().all()
    if not exercices:
        return

    ex_map: dict[int, int] = {}
    for exercice in exercices:
        new_id = conn.execute(
            budget_exercices.insert()
            .values(
                organisation_id=target_org_id,
                annee=exercice["annee"],
                statut=sa.cast(sa.literal(exercice["statut"]), BUDGET_STATUS_ENUM),
            )
            .returning(budget_exercices.c.id)
        ).scalar_one()
        ex_map[exercice["id"]] = new_id

    postes = conn.execute(
        sa.select(
            budget_postes.c.id,
            budget_postes.c.exercice_id,
            budget_postes.c.code,
            budget_postes.c.libelle,
            budget_postes.c.parent_code,
            budget_postes.c.parent_id,
            budget_postes.c.type,
            budget_postes.c.active,
            budget_postes.c.is_global,
            budget_postes.c.montant_prevu,
            budget_postes.c.montant_engage,
            budget_postes.c.montant_paye,
            budget_postes.c.is_deleted,
            budget_postes.c.deleted_at,
            budget_postes.c.deleted_by,
        )
        .where(budget_postes.c.organisation_id == source_org_id)
        .order_by(budget_postes.c.id.asc())
    ).mappings().all()

    poste_map: dict[int, int] = {}
    for poste in postes:
        new_id = conn.execute(
            budget_postes.insert()
            .values(
                organisation_id=target_org_id,
                exercice_id=ex_map[poste["exercice_id"]],
                code=poste["code"],
                libelle=poste["libelle"],
                parent_code=poste["parent_code"],
                parent_id=None,
                type=poste["type"],
                active=poste["active"],
                is_global=poste["is_global"],
                montant_prevu=poste["montant_prevu"],
                montant_engage=poste["montant_engage"],
                montant_paye=poste["montant_paye"],
                is_deleted=poste["is_deleted"],
                deleted_at=poste["deleted_at"],
                deleted_by=poste["deleted_by"],
            )
            .returning(budget_postes.c.id)
        ).scalar_one()
        poste_map[poste["id"]] = new_id

    for poste in postes:
        if poste["parent_id"] and poste["parent_id"] in poste_map:
            conn.execute(
                budget_postes.update()
                .where(budget_postes.c.id == poste_map[poste["id"]])
                .values(parent_id=poste_map[poste["parent_id"]])
            )


def upgrade() -> None:
    conn = op.get_bind()
    now = _utcnow()

    organisations = sa.table(
        "organisations",
        sa.column("id", sa.Integer),
        sa.column("nom", sa.String),
        sa.column("devise_preferee", sa.String),
        sa.column("limite_utilisateurs", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    system_settings = sa.table(
        "system_settings",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("organisation_id", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    organisation_settings = sa.table(
        "organisation_settings",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("max_users", sa.Integer),
        sa.column("storage_quota_mb", sa.Integer),
        sa.column("is_ai_enabled", sa.Boolean),
        sa.column("is_mobile_money_enabled", sa.Boolean),
        sa.column("is_audit_logs_enabled", sa.Boolean),
        sa.column("fiscal_year_start", sa.Integer),
        sa.column("currency_code", sa.String),
        sa.column("theme_primary_color", sa.String),
        sa.column("theme_sidebar_color", sa.String),
        sa.column("theme_sidebar_text_color", sa.String),
        sa.column("theme_sidebar_active_color", sa.String),
        sa.column("theme_accent_color", sa.String),
        sa.column("theme_text_color", sa.String),
        sa.column("theme_button_text_color", sa.String),
    )
    print_settings = sa.table(
        "print_settings",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("organisation_id", sa.Integer),
        sa.column("organization_name", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("pied_de_page_legal", sa.Text),
        sa.column("afficher_qr_code", sa.Boolean),
        sa.column("show_header_logo", sa.Boolean),
        sa.column("show_footer_signature", sa.Boolean),
        sa.column("recu_label_signature", sa.String),
        sa.column("sortie_label_signature", sa.String),
        sa.column("sortie_sig_label_1", sa.String),
        sa.column("sortie_sig_label_2", sa.String),
        sa.column("sortie_sig_label_3", sa.String),
        sa.column("sortie_sig_hint", sa.String),
        sa.column("show_sortie_qr", sa.Boolean),
        sa.column("sortie_qr_base_url", sa.String),
        sa.column("show_sortie_watermark", sa.Boolean),
        sa.column("sortie_watermark_text", sa.String),
        sa.column("sortie_watermark_opacity", sa.Numeric),
        sa.column("paper_format", sa.String),
        sa.column("compact_header", sa.Boolean),
        sa.column("req_titre_officiel", sa.String),
        sa.column("req_label_gauche", sa.String),
        sa.column("req_label_droite", sa.String),
        sa.column("trans_titre_officiel", sa.String),
        sa.column("trans_label_gauche", sa.String),
        sa.column("trans_label_droite", sa.String),
        sa.column("encaissement_libelle_presets", sa.Text),
        sa.column("default_currency", sa.String),
        sa.column("secondary_currency", sa.String),
        sa.column("exchange_rate", sa.Numeric),
        sa.column("exchange_rate_cdf", sa.Numeric),
        sa.column("exchange_rate_eur", sa.Numeric),
        sa.column("exchange_rate_xof", sa.Numeric),
        sa.column("fiscal_year", sa.Integer),
        sa.column("budget_alert_threshold", sa.Integer),
        sa.column("budget_block_overrun", sa.Boolean),
        sa.column("budget_force_roles", sa.String),
    )
    caisse_centrale = sa.table(
        "caisse_centrale",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("solde_usd", sa.Numeric),
        sa.column("solde_cdf", sa.Numeric),
    )
    comptes_bancaires = sa.table(
        "comptes_bancaires",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("banque_id", sa.Integer),
        sa.column("intitule", sa.String),
        sa.column("numero_compte", sa.String),
        sa.column("devise", sa.String),
        sa.column("solde_initial", sa.Numeric),
        sa.column("solde_actuel", sa.Numeric),
        sa.column("is_active", sa.Boolean),
        sa.column("account_type", sa.String),
    )
    services = sa.table(
        "services",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("libelle", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("organisation_id", sa.Integer),
    )
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String),
        sa.column("organisation_id", sa.Integer),
        sa.column("service_id", sa.Integer),
    )
    user_services = sa.table(
        "user_services",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("service_id", sa.Integer),
    )
    budget_exercices = sa.table(
        "budget_exercices",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("annee", sa.Integer),
        sa.column("statut", sa.String),
    )
    budget_postes = sa.table(
        "budget_postes",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("exercice_id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("libelle", sa.String),
        sa.column("parent_code", sa.String),
        sa.column("parent_id", sa.Integer),
        sa.column("type", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("is_global", sa.Boolean),
        sa.column("montant_prevu", sa.Numeric),
        sa.column("montant_engage", sa.Numeric),
        sa.column("montant_paye", sa.Numeric),
        sa.column("is_deleted", sa.Boolean),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("deleted_by", postgresql.UUID(as_uuid=True)),
    )

    template_org_settings = conn.execute(
        sa.select(*[getattr(organisation_settings.c, field) for field in ORG_SETTINGS_TEMPLATE_FIELDS]).where(
            organisation_settings.c.organisation_id == 1
        )
    ).mappings().first()
    template_print_settings = conn.execute(
        sa.select(*[getattr(print_settings.c, field) for field in PRINT_SETTINGS_TEMPLATE_FIELDS]).where(
            print_settings.c.organisation_id == 1
        )
    ).mappings().first()

    org_rows = conn.execute(
        sa.select(
            organisations.c.id,
            organisations.c.nom,
            organisations.c.is_active,
        ).where(organisations.c.is_active.is_(True))
    ).mappings().all()

    for org in org_rows:
        org_id = org["id"]
        org_name = (org["nom"] or "").strip()

        system_exists = conn.execute(
            sa.select(system_settings.c.id).where(system_settings.c.organisation_id == org_id).limit(1)
        ).scalar_one_or_none()
        if system_exists is None:
            conn.execute(
                system_settings.insert().values(
                    id=uuid.uuid4(),
                    organisation_id=org_id,
                    updated_at=now,
                )
            )

        org_settings_row = conn.execute(
            sa.select(organisation_settings).where(organisation_settings.c.organisation_id == org_id).limit(1)
        ).mappings().first()
        if org_settings_row is None:
            values = {
                "organisation_id": org_id,
                "max_users": 2,
                "storage_quota_mb": 1024,
                "is_ai_enabled": False,
                "is_mobile_money_enabled": True,
                "is_audit_logs_enabled": True,
                "fiscal_year_start": 1,
                "currency_code": "CDF",
            }
            _copy_fields(template_org_settings, values, ORG_SETTINGS_TEMPLATE_FIELDS)
            conn.execute(organisation_settings.insert().values(**values))
            org_settings_row = values

        conn.execute(
            organisations.update()
            .where(organisations.c.id == org_id)
            .values(
                devise_preferee=org_settings_row["currency_code"],
                limite_utilisateurs=org_settings_row["max_users"],
                updated_at=now,
            )
        )

        print_row = conn.execute(
            sa.select(print_settings).where(print_settings.c.organisation_id == org_id).limit(1)
        ).mappings().first()
        if print_row is None:
            values = {
                "id": uuid.uuid4(),
                "organisation_id": org_id,
                "organization_name": org_name,
                "encaissement_libelle_presets": DEFAULT_ENCAISSEMENT_LIBELLE_PRESETS,
                "exchange_rate_cdf": 0,
                "exchange_rate_eur": 0,
                "exchange_rate_xof": 0,
                "updated_at": now,
            }
            _copy_fields(template_print_settings, values, PRINT_SETTINGS_TEMPLATE_FIELDS)
            conn.execute(print_settings.insert().values(**values))
        elif not (print_row["organization_name"] or "").strip():
            conn.execute(
                print_settings.update()
                .where(print_settings.c.id == print_row["id"])
                .values(organization_name=org_name, updated_at=now)
            )

        caisse_exists = conn.execute(
            sa.select(caisse_centrale.c.id).where(caisse_centrale.c.organisation_id == org_id).limit(1)
        ).scalar_one_or_none()
        if caisse_exists is None:
            conn.execute(
                caisse_centrale.insert().values(
                    organisation_id=org_id,
                    solde_usd=0,
                    solde_cdf=0,
                )
            )

        cash_currencies = {
            str(row[0] or "").upper()
            for row in conn.execute(
                sa.select(comptes_bancaires.c.devise).where(
                    comptes_bancaires.c.organisation_id == org_id,
                    comptes_bancaires.c.account_type == "CASH",
                )
            ).all()
        }
        if "USD" not in cash_currencies:
            conn.execute(
                comptes_bancaires.insert().values(
                    organisation_id=org_id,
                    banque_id=None,
                    intitule="Caisse USD",
                    numero_compte=f"CASH-USD-{org_id}",
                    devise="USD",
                    solde_initial=0,
                    solde_actuel=0,
                    is_active=True,
                    account_type="CASH",
                )
            )
        if "CDF" not in cash_currencies:
            conn.execute(
                comptes_bancaires.insert().values(
                    organisation_id=org_id,
                    banque_id=None,
                    intitule="Caisse CDF",
                    numero_compte=f"CASH-CDF-{org_id}",
                    devise="CDF",
                    solde_initial=0,
                    solde_actuel=0,
                    is_active=True,
                    account_type="CASH",
                )
            )

        service_id = conn.execute(
            sa.select(services.c.id).where(
                services.c.organisation_id == org_id,
                services.c.code == DEFAULT_SERVICE_CODE,
            ).limit(1)
        ).scalar_one_or_none()
        if service_id is None:
            service_id = conn.execute(
                services.insert()
                .values(
                    code=DEFAULT_SERVICE_CODE,
                    libelle=DEFAULT_SERVICE_LABEL,
                    is_active=True,
                    organisation_id=org_id,
                )
                .returning(services.c.id)
            ).scalar_one()

        admin_rows = conn.execute(
            sa.select(users.c.id, users.c.service_id).where(
                users.c.organisation_id == org_id,
                sa.func.lower(users.c.role).in_(("admin", "super_admin")),
            )
        ).mappings().all()
        for admin in admin_rows:
            if admin["service_id"] is None:
                conn.execute(
                    users.update()
                    .where(users.c.id == admin["id"])
                    .values(service_id=service_id)
                )
            link_exists = conn.execute(
                sa.select(user_services.c.user_id).where(
                    user_services.c.user_id == admin["id"],
                    user_services.c.service_id == service_id,
                ).limit(1)
            ).scalar_one_or_none()
            if link_exists is None:
                conn.execute(
                    user_services.insert().values(
                        user_id=admin["id"],
                        service_id=service_id,
                    )
                )

        if org_id != 1:
            _clone_budget_structure(
                conn,
                budget_exercices,
                budget_postes,
                source_org_id=1,
                target_org_id=org_id,
            )


def downgrade() -> None:
    # Data normalization is intentionally not reverted.
    pass
