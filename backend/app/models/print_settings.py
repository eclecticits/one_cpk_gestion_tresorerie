from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrintSettings(Base):
    __tablename__ = "print_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    organization_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    organization_subtitle: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    header_text: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    bank_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bank_account: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    mobile_money_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    mobile_money_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    pied_de_page_legal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    afficher_qr_code: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_header_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_footer_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    logo_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    stamp_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    recu_label_signature: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    recu_nom_signataire: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sortie_label_signature: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sortie_nom_signataire: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sortie_sig_label_1: Mapped[str] = mapped_column(String(200), nullable=False, default="CAISSIER")
    sortie_sig_label_2: Mapped[str] = mapped_column(String(200), nullable=False, default="COMPTABLE")
    sortie_sig_label_3: Mapped[str] = mapped_column(String(200), nullable=False, default="AUTORITÉ (TRÉSORERIE)")
    sortie_sig_hint: Mapped[str] = mapped_column(String(200), nullable=False, default="Signature & date")
    show_sortie_qr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sortie_qr_base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    show_sortie_watermark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sortie_watermark_text: Mapped[str] = mapped_column(String(50), nullable=False, default="PAYÉ")
    sortie_watermark_opacity: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0.15)
    paper_format: Mapped[str] = mapped_column(String(3), nullable=False, default="A5")
    compact_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    req_titre_officiel: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    req_label_gauche: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    req_nom_gauche: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    req_label_droite: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    req_nom_droite: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    trans_titre_officiel: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    trans_label_gauche: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    trans_nom_gauche: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    trans_label_droite: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    trans_nom_droite: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    encaissement_libelle_presets: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "Cotisation annuelle - Expert-Comptable Cabinet\n"
            "Cotisation annuelle - Expert-Comptable Indépendant\n"
            "Cotisation annuelle - Expert-Comptable Salarié\n"
            "Cotisation annuelle - Stagiaire (SEC)\n"
            "Arriérés de cotisation\n"
            "Pénalité de retard - Cotisation\n"
            "Régularisation cotisation antérieure\n"
            "Frais de participation - Formation fiscale\n"
            "Frais de participation - Co-commissariat\n"
            "Inscription - Séminaire professionnel\n"
            "Attestation de formation\n"
            "Contribution FORCO annuelle\n"
            "Pénalité absence formation obligatoire\n"
            "Frais d'inscription au Tableau\n"
            "Frais de réinscription\n"
            "Frais d'étude de dossier\n"
            "Délivrance attestation d'inscription\n"
            "Délivrance duplicata carte professionnelle\n"
            "Mutation / Transfert de cabinet\n"
            "Frais de stage professionnel\n"
            "Délivrance certificat professionnel\n"
            "Légalisation de signature\n"
            "Certification de documents\n"
            "Attestation de conformité\n"
            "Vente de formulaire officiel\n"
            "Amende disciplinaire\n"
            "Pénalité administrative\n"
            "Régularisation décision disciplinaire\n"
            "Contribution Commission Tableau\n"
            "Contribution Commission FORCO\n"
            "Contribution Commission Discipline\n"
            "Contribution événement institutionnel\n"
            "Participation activité spéciale ONEC\n"
            "Location salle de réunion\n"
            "Contribution partenaire institutionnel\n"
            "Sponsoring événement\n"
            "Subvention reçue\n"
            "Don volontaire\n"
            "Recette exceptionnelle\n"
            "Vente matériel usagé\n"
            "Remboursement frais\n"
            "Autres recettes"
        ),
    )

    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    secondary_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CDF")
    exchange_rate: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    exchange_rate_cdf: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    exchange_rate_eur: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    exchange_rate_xof: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    budget_alert_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    budget_block_overrun: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    budget_force_roles: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
