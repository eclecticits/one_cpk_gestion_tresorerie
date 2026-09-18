from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganisationSettings(Base):
    __tablename__ = "organisation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    is_ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_mobile_money_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_audit_logs_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fiscal_year_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="CDF")
    theme_primary_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#4a9079")
    theme_sidebar_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3d7a66")
    theme_sidebar_text_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#ffffff")
    theme_sidebar_active_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#1a523f")
    theme_accent_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#eab308")
    theme_text_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#2d3748")
    theme_button_text_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#ffffff")
    accounting_integration_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    # Les deux bornes d'une collation de réunion en sortie directe. Le prix par
    # tête dit que c'en est bien une ; le total dit qu'elle reste une sortie
    # directe et non une dépense qui devrait passer par une réquisition.
    # Réglables : un traiteur fait varier ce qu'un code figé ne suivrait pas.
    collation_plafond_par_personne_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("5")
    )
    collation_plafond_total_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("100")
    )
    # Le plafond par réunion borne une dépense, pas une journée : sans cette
    # troisième borne, il suffirait d'aligner les réunions — une le matin, une
    # l'après-midi — pour vider la caisse par petites salles successives.
    collation_plafond_24h_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("400")
    )

    # Configuration détaillée par module métier (JSONB)
    modules_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Configuration du circuit de validation des réquisitions / sorties de fonds
    # (JSONB). Null => circuit complet par défaut (voir app.services.workflow_config).
    workflow_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
