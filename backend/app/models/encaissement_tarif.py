"""Tarifs d'encaissement : ce qu'un libellé connu vaut, et où il s'impute.

La pré-liste des libellés n'était qu'un texte servi en auto-complétion : elle
faisait gagner de la frappe, mais le caissier restait libre du montant comme du
poste, et deux encaissements de la même cotisation pouvaient différer.

Un tarif porte le libellé et, **séparément**, un montant et un poste. Les deux
sont facultatifs et indépendants : un montant sans poste (le prix est ferme,
l'imputation se décide au cas par cas), un poste sans montant (le montant varie,
la recette tombe toujours au même endroit), ou les deux. Ce qui est défini est
imposé à la saisie ; le reste demeure libre.

Le poste est désigné par son **code**, jamais par un identifiant : les postes
appartiennent à un exercice, et l'identifiant de « II.1.1.2 » change chaque
année. Le code se résout au poste de l'exercice courant au moment où l'on s'en
sert, si bien qu'un tarif survit à l'ouverture d'un nouvel exercice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EncaissementTarif(Base):
    __tablename__ = "encaissement_tarifs"
    __table_args__ = (
        # Un libellé désigne un tarif et un seul : sans cela, la saisie ne
        # saurait pas lequel appliquer. La casse et les espaces ne font pas
        # deux tarifs (unicité posée sur le libellé normalisé).
        UniqueConstraint("organisation_id", "libelle_normalise", name="uq_encaissement_tarifs_org_libelle"),
        CheckConstraint("montant IS NULL OR montant > 0", name="ck_encaissement_tarifs_montant_positif"),
        CheckConstraint("devise IN ('USD','CDF')", name="ck_encaissement_tarifs_devise"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Libellé en minuscules, espaces resserrés : la clé qui reconnaît le tarif
    #: à la saisie, et qui porte l'unicité.
    libelle_normalise: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Prix UNITAIRE. La quantité reste libre : trois cotisations à 50, c'est
    #: quantité 3 et prix 50, jamais un total figé.
    montant: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    #: Code du poste de recette, résolu à l'exercice courant. Nul = imputation
    #: laissée libre.
    budget_poste_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    #: Ordre d'affichage voulu par l'administrateur (la pré-liste se classait
    #: déjà à la main, avec ses flèches monter/descendre).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def normaliser_libelle(valeur: str | None) -> str:
    """Clé de reconnaissance d'un libellé : minuscules, espaces resserrés."""
    return " ".join((valeur or "").split()).lower()
