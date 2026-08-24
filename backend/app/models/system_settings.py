from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSettings(Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("organisation_id", name="uq_system_settings_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    email_expediteur: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_president: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_tresorier: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_sortie_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_validation_1: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_validation_final: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    max_caisse_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Postes budgétaires imputés par les régularisations d'écart de caisse
    # (excédent -> encaissement, déficit -> sortie). Tant qu'ils ne sont pas
    # renseignés, un écart constaté reste simplement non régularisé.
    budget_poste_excedent_caisse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("budget_postes.id", ondelete="SET NULL"), nullable=True
    )
    budget_poste_deficit_caisse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("budget_postes.id", ondelete="SET NULL"), nullable=True
    )
    smtp_password: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    smtp_host: Mapped[str] = mapped_column(String(200), nullable=False, default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=465)
    # ── WhatsApp : socle historique ──────────────────────────────────────────
    # Ces trois colonnes RESTENT. Le chemin d'envoi actuel (requisitions.py,
    # encaissements.py) les lit encore directement, et `whatsapp_agents` sert de
    # liste de repli tant qu'un tenant n'a pas renseigné les téléphones du
    # Bureau. Les supprimer, c'est couper les notifications d'un tenant qui n'a
    # pas encore migré sa configuration.
    whatsapp_api_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    whatsapp_api_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    whatsapp_agents: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── WhatsApp : canal multi-fournisseur ───────────────────────────────────
    # Ajout strictement additif. Défauts volontairement fermés : après la
    # migration, aucun tenant n'envoie quoi que ce soit tant qu'un humain n'a pas
    # coché « activer ». Une migration qui met un canal sortant en marche toute
    # seule est une migration qui envoie des messages à de vrais destinataires.
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    whatsapp_notify_payments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    whatsapp_notify_sorties: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 'evolution' : le fournisseur auto-hébergé déjà utilisé via whatsapp_api_url,
    # donc le défaut qui décrit le mieux l'existant.
    whatsapp_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="evolution")

    # Texte et non String(255) : un jeton Fernet est ~1,4× plus long que le
    # secret d'origine, une clé Meta de 200 caractères déborderait de 255.
    whatsapp_api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")

    whatsapp_phone_number_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    whatsapp_business_account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    whatsapp_sender: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    # Surcharges de gabarits par événement, nullable : « pas de surcharge » et
    # « surcharges vides » ne sont pas la même chose pour l'écran de réglages.
    whatsapp_templates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Spécifiques à un fournisseur : nom du template approuvé (Meta Cloud),
    # SID du compte (Twilio), version de l'API Graph.
    whatsapp_template_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    whatsapp_account_sid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    whatsapp_graph_version: Mapped[str] = mapped_column(String(10), nullable=False, default="")

    last_weekly_report_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_weekly_report_status: Mapped[str] = mapped_column(String(20), nullable=False, default="never")
    last_weekly_report_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_weekly_report_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_weekly_report_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
