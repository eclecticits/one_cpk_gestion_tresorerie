"""Canal WhatsApp multi-fournisseur : journal d'envoi, réglages, destinataires, droits

Quatre choses, dans cet ordre — l'ordre compte, la reprise de clé (3) suppose
les colonnes de (2) déjà posées.

1. **Table `notification_logs`.** Une ligne par (événement × destinataire ×
   canal). Elle n'existe pas pour faire joli : sans statut ni destinataire en
   colonnes indexables, on ne sait pas répondre à « quels envois ont échoué pour
   cette sortie ? », donc on ne peut pas offrir de bouton « Renvoyer ».
   `system_events` ne convient pas : c'est un journal d'incidents, sans
   destinataire, sans statut, sans canal. `dedup_key` est UNIQUE — c'est cette
   contrainte, et non un verrou applicatif, qui empêche un double-clic ou un
   rejeu HTTP de produire un second message.

2. **Colonnes WhatsApp sur `system_settings`, strictement additives.**
   `whatsapp_api_url`, `whatsapp_api_key` et `whatsapp_agents` RESTENT :
   requisitions.py:1966-1984, requisitions.py:2045-2063 et
   encaissements.py:1637-1657 les lisent encore, et `whatsapp_agents` reste la
   liste de repli des destinataires tant qu'un tenant n'a pas renseigné les
   téléphones de son Bureau. Aucun numéro n'est inventé ni effacé ici.
   Tous les défauts sont fermés (`whatsapp_enabled` = false) : une migration ne
   met pas un canal sortant en marche toute seule.

3. **Reprise de la clé API.** `whatsapp_api_key` est aujourd'hui stockée en
   clair et renvoyée telle quelle par `GET /admin/notification-settings`
   (admin.py:269). On la recopie chiffrée dans `whatsapp_api_key_encrypted` puis
   on vide la colonne en clair.

   Deux garde-fous, parce qu'une migration qui perd un secret est pire qu'une
   migration qui ne fait rien :
   - **Pas de clé maître, pas de reprise.** `encrypt_secret` ne lève pas en dev :
     il fabrique une clé Fernet éphémère (encryption.py:73-80) et le chiffré
     devient illisible au redémarrage suivant. Vider la colonne en clair après
     un tel chiffrement, c'est détruire la clé du tenant. On vérifie donc
     explicitement la présence de `AI_PROVIDER_ENCRYPTION_KEY` et, à défaut, on
     laisse tout en place en journalisant. `settings_loader.resolve_api_key`
     retombe alors sur la colonne en clair : rien ne casse.
   - **Chiffrement par ligne, échec isolé.** Une exception sur un tenant
     n'annule pas les autres et ne fait pas tomber la migration.

   Rejouable : la reprise ne prend que les lignes où le chiffré est vide. Un
   deuxième passage ne trouve plus rien à faire. Et un tenant sauté faute de clé
   maître sera repris tel quel au prochain `alembic upgrade` lancé, lui, avec la
   clé — c'est voulu.

4. **Quatre droits d'action `treso.notifications.*`, rétro-accordés.** Même
   technique que 20260822_treso_actions : chaque code est accordé à tout rôle
   détenant déjà `can_edit_settings`, la permission qui garde aujourd'hui
   `GET/PUT /admin/notification-settings` (admin.py:1146, :1164) et le test de
   connexion (:1241). Conséquence recherchée : au déploiement, personne ne perd
   un accès ; les gardes fines sont posées ensuite, endpoint par endpoint, sur
   une base déjà peuplée.

Revision ID: 20260823_whatsapp_notifs
Revises: 20260823_saas_invoicing
Create Date: 2026-08-23
"""

from __future__ import annotations

import logging
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20260823_whatsapp_notifs"
down_revision = "20260823_saas_invoicing"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


# ---------------------------------------------------------------------------
# 1. Table du journal d'envoi
# ---------------------------------------------------------------------------

NOTIFICATION_LOGS_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_notification_logs_organisation_id", ["organisation_id"]),
    ("ix_notification_logs_event_type", ["event_type"]),
    ("ix_notification_logs_status", ["status"]),
    # Répond à « quels envois pour CETTE sortie de fonds ? » — la requête de
    # l'écran de détail et du bouton « Renvoyer ».
    ("ix_notification_logs_entity", ["entity_type", "entity_id"]),
    # Répond à « le journal du tenant, du plus récent au plus ancien ».
    ("ix_notification_logs_org_created", ["organisation_id", "created_at"]),
)


# ---------------------------------------------------------------------------
# 2. Colonnes additives
# ---------------------------------------------------------------------------

# Fabriques, et non constantes : un objet `sa.Column` ne peut être rattaché
# qu'à une seule table. Le réutiliser ferait échouer un second `op.add_column`
# dans le même processus — exactement ce que fait un test qui enchaîne
# upgrade / downgrade / upgrade.


def _system_settings_columns() -> list[sa.Column]:
    """Colonnes WhatsApp ajoutées à `system_settings`, dans l'ordre d'ajout."""
    return [
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("whatsapp_notify_payments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("whatsapp_notify_sorties", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("whatsapp_provider", sa.String(length=30), nullable=False, server_default="evolution"),
        # Text : un jeton Fernet dépasse 255 caractères dès que le secret
        # d'origine approche 190. String(255) tronquerait une clé Meta.
        sa.Column("whatsapp_api_key_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("whatsapp_phone_number_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("whatsapp_business_account_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("whatsapp_sender", sa.String(length=40), nullable=False, server_default=""),
        # Nullable et sans défaut : « aucune surcharge de gabarit » et
        # « surcharges vides » sont deux états distincts pour l'écran de réglages.
        sa.Column("whatsapp_templates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("whatsapp_template_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("whatsapp_account_sid", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("whatsapp_graph_version", sa.String(length=10), nullable=False, server_default=""),
    ]


def _commission_member_columns() -> list[sa.Column]:
    """Colonnes de notification ajoutées à `commission_members`."""
    return [
        # Nullable : la quasi-totalité des membres existants n'a pas de numéro,
        # et une chaîne vide serait un faux numéro à filtrer partout ensuite.
        sa.Column("telephone", sa.String(length=50), nullable=True),
        # server_default obligatoire : la table n'est pas vide en production, un
        # NOT NULL sans défaut échouerait à l'ALTER.
        sa.Column("notify_whatsapp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    ]


# ---------------------------------------------------------------------------
# 4. Droits d'action
# ---------------------------------------------------------------------------

PERMISSIONS: list[tuple[str, str]] = [
    ("treso.notifications.read", "Trésorerie — Notifications : consulter les réglages du canal WhatsApp"),
    ("treso.notifications.update", "Trésorerie — Notifications : modifier les réglages (fournisseur, clé, gabarits, destinataires)"),
    ("treso.notifications.history", "Trésorerie — Notifications : consulter le journal des envois et relancer un message"),
    ("treso.notifications.test", "Trésorerie — Notifications : envoyer un message de test"),
]

# Source unique et volontairement étroite : `can_edit_settings` est la garde
# effective de GET/PUT /admin/notification-settings et de
# /admin/test-email-connection. Élargir cette liste (à `menu_settings` par
# exemple) accorderait un droit à des rôles qui ne l'ont pas aujourd'hui.
RETRO_GRANT_SOURCES: list[str] = ["can_edit_settings"]


def _table_exists(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _existing_columns(bind, table_name: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def _master_key_available() -> bool:
    """La clé maître de chiffrement est-elle réellement configurée ?

    Question distincte de « encrypt_secret fonctionne-t-il ? » : sans clé,
    `encrypt_secret` réussit quand même, avec une clé éphémère, et produit un
    chiffré illisible au prochain démarrage. C'est précisément le cas où il ne
    faut PAS vider la colonne en clair.
    """
    try:
        from app.core.config import settings as app_settings

        if (getattr(app_settings, "ai_provider_encryption_key", "") or "").strip():
            return True
    except Exception:  # pragma: no cover - config indisponible hors application
        pass
    return bool(os.environ.get("AI_PROVIDER_ENCRYPTION_KEY", "").strip())


def _create_notification_logs() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "notification_logs"):
        logger.info("notification_logs déjà présente — création ignorée")
        return

    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        # ON DELETE CASCADE : le journal d'envoi d'un tenant supprimé n'a plus de
        # destinataire ni de lecteur ; le conserver orphelin ne servirait qu'à
        # bloquer la suppression de l'organisation.
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("entity_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("recipient", sa.String(length=120), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("recipient_role", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        # Nom de colonne `metadata` : c'est celui du contrat côté modèle, où
        # l'attribut Python s'appelle `event_metadata` parce que `metadata` est
        # réservé par la couche déclarative de SQLAlchemy.
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dedup_key", name="uq_notification_logs_dedup_key"),
    )

    for index_name, columns in NOTIFICATION_LOGS_INDEXES:
        op.create_index(index_name, "notification_logs", columns)


def _add_columns(table_name: str, columns: list[sa.Column]) -> None:
    present = _existing_columns(op.get_bind(), table_name)
    for column in columns:
        if column.name not in present:
            op.add_column(table_name, column)


def _drop_columns(table_name: str, columns: list[sa.Column]) -> None:
    present = _existing_columns(op.get_bind(), table_name)
    for column in reversed(columns):
        if column.name in present:
            op.drop_column(table_name, column.name)


# ---------------------------------------------------------------------------
# 3. Reprise de la clé API
# ---------------------------------------------------------------------------


def _migrate_api_keys() -> None:
    """Recopie `whatsapp_api_key` chiffrée, puis vide la colonne en clair."""
    bind = op.get_bind()

    if not _master_key_available():
        logger.warning(
            "whatsapp: AI_PROVIDER_ENCRYPTION_KEY absent — reprise des clés API "
            "IGNOREE. Les clés restent en clair dans system_settings.whatsapp_api_key "
            "et resolve_api_key() continue de les lire. Relancez la migration avec "
            "la clé maître configurée pour effectuer la reprise."
        )
        return

    try:
        from app.core.encryption import encrypt_secret
    except Exception:  # pragma: no cover - dépendance cryptography absente
        logger.warning("whatsapp: app.core.encryption indisponible — reprise des clés API ignorée")
        return

    rows = bind.execute(
        text(
            """
            SELECT id::text AS sid, organisation_id, whatsapp_api_key
            FROM system_settings
            WHERE COALESCE(whatsapp_api_key, '') <> ''
              AND COALESCE(whatsapp_api_key_encrypted, '') = ''
            """
        )
    ).fetchall()

    migrated = 0
    for row in rows:
        try:
            token = encrypt_secret(row.whatsapp_api_key)
        except Exception:
            # Un tenant en échec ne doit ni faire tomber la migration ni empêcher
            # la reprise des autres. La clé reste en clair, donc exploitable.
            logger.warning(
                "whatsapp: chiffrement impossible pour org=%s — clé laissée en clair",
                row.organisation_id,
            )
            continue
        if not token:
            continue
        bind.execute(
            text(
                """
                UPDATE system_settings
                SET whatsapp_api_key_encrypted = :token,
                    whatsapp_api_key = ''
                WHERE id = CAST(:sid AS uuid)
                """
            ),
            {"token": token, "sid": row.sid},
        )
        migrated += 1

    logger.info("whatsapp: %s clé(s) API reprise(s) sur %s candidate(s)", migrated, len(rows))


def _seed_permissions() -> None:
    bind = op.get_bind()
    for code, description in PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (code, description, created_at) "
                "VALUES (:code, :description, NOW()) "
                "ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description"
            ),
            {"code": code, "description": description},
        )


def _grant_from_sources(target_code: str, source_codes: list[str]) -> None:
    """Accorde `target_code` à tout rôle détenant l'une des `source_codes`."""
    op.get_bind().execute(
        text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT DISTINCT rp.role_id, target.id
            FROM role_permissions rp
            JOIN permissions source
              ON source.id = rp.permission_id
             AND source.code = ANY(:source_codes)
            JOIN permissions target
              ON target.code = :target_code
            ON CONFLICT DO NOTHING
            """
        ),
        {"source_codes": source_codes, "target_code": target_code},
    )


def _grant_to_admin_role() -> None:
    """Le rôle `admin` porte les nouveaux codes, comme pour Trésorerie et RH.

    Sans effet sur l'autorisation runtime (deps.py court-circuite sur la chaîne
    users.role), mais la matrice de l'écran Rôles reflète alors la base réelle.
    """
    op.get_bind().execute(
        text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = ANY(:codes)
            WHERE r.code = 'admin'
            ON CONFLICT DO NOTHING
            """
        ),
        {"codes": [code for code, _ in PERMISSIONS]},
    )


def upgrade() -> None:
    _create_notification_logs()
    _add_columns("system_settings", _system_settings_columns())
    _add_columns("commission_members", _commission_member_columns())
    _migrate_api_keys()

    _seed_permissions()
    for target_code, _description in PERMISSIONS:
        _grant_from_sources(target_code, RETRO_GRANT_SOURCES)
    _grant_to_admin_role()


def _restore_api_keys() -> None:
    """Remet les clés en clair avant de perdre la colonne chiffrée.

    Sans cette étape, un downgrade détruirait définitivement la clé API de
    chaque tenant repris à l'upgrade : la colonne en clair a été vidée, la
    colonne chiffrée est sur le point d'être supprimée.
    """
    bind = op.get_bind()
    if "whatsapp_api_key_encrypted" not in _existing_columns(bind, "system_settings"):
        return

    try:
        from app.core.encryption import decrypt_secret
    except Exception:  # pragma: no cover
        logger.warning("whatsapp: app.core.encryption indisponible — clés chiffrées non restaurées")
        return

    rows = bind.execute(
        text(
            """
            SELECT id::text AS sid, organisation_id, whatsapp_api_key_encrypted
            FROM system_settings
            WHERE COALESCE(whatsapp_api_key_encrypted, '') <> ''
              AND COALESCE(whatsapp_api_key, '') = ''
            """
        )
    ).fetchall()

    for row in rows:
        try:
            plaintext = decrypt_secret(row.whatsapp_api_key_encrypted)
        except Exception:
            # Clé maître changée ou absente : on ne peut rien restaurer. On le
            # dit fort, plutôt que de laisser croire à une reprise silencieuse.
            logger.warning(
                "whatsapp: clé indéchiffrable pour org=%s — non restaurée en clair",
                row.organisation_id,
            )
            continue
        if not plaintext:
            continue
        bind.execute(
            text("UPDATE system_settings SET whatsapp_api_key = :key WHERE id = CAST(:sid AS uuid)"),
            {"key": plaintext[:255], "sid": row.sid},
        )


def downgrade() -> None:
    bind = op.get_bind()

    codes = [code for code, _ in PERMISSIONS]
    # role_permissions serait purgée par la cascade FK, mais les migrations du
    # dépôt la vident explicitement : on garde la convention.
    bind.execute(
        text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

    _restore_api_keys()

    _drop_columns("commission_members", _commission_member_columns())
    _drop_columns("system_settings", _system_settings_columns())

    if _table_exists(bind, "notification_logs"):
        for index_name, _columns in reversed(NOTIFICATION_LOGS_INDEXES):
            op.drop_index(index_name, table_name="notification_logs")
        op.drop_table("notification_logs")
