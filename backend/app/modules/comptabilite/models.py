"""Modèles du module Comptabilité (Lot 1 — Fondations).

Conventions imposées par l'architecture (cf. docs/comptabilite/ARCHITECTURE_MODULE_COMPTABILITE.md) :
- Montants : Numeric(18, 2) — un budget de 5 M USD ≈ 14 Md CDF sature Numeric(15, 2).
- Taux de change : Numeric(18, 8) — le taux inverse CDF→USD (~0.000357) exige cette précision.
- organisation_id : Integer FK organisations.id ondelete=RESTRICT, indexé (1 organisation = 1 société).
- Aucune suppression physique : statut + contre-passation + historisation.

⚠️ RAPPEL CRITIQUE (contrainte C1) : chaque modèle ci-dessous DOIT être déclaré
dans `_apply_tenant_criteria` (app/db/session.py), sinon les SELECT ne sont pas
filtrés par organisation → fuite inter-tenant silencieuse.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Constantes de domaine ────────────────────────────────────────────────────

TYPES_REFERENTIEL = ("SYSCOHADA", "SYSCEBNL", "PCG", "ASSOCIATIF", "ONG", "PERSONNALISE")
NATURES_COMPTE = ("ACTIF", "PASSIF", "CHARGE", "PRODUIT", "ENGAGEMENT")
SENS = ("DEBIT", "CREDIT")
TYPES_JOURNAL = ("BQ", "CA", "AC", "VE", "OD", "SAL", "IMMO", "CLO", "OUV", "TVA", "AJU")
STATUTS_EXERCICE = ("OUVERT", "FERME", "ROUVERT", "CLOTURE", "VERROUILLE")
STATUTS_PERIODE = ("OUVERTE", "FERMEE")
STATUTS_ECRITURE = ("BROUILLON", "VALIDEE", "CLOTUREE", "ANNULEE")


# ── Entité comptable : société / établissement ───────────────────────────────
#
# En exploitation : 1 organisation (tenant) = 1 société, créée automatiquement.
# La dimension est néanmoins portée dès la fondation car l'ajouter plus tard
# imposerait de migrer des millions de lignes d'écriture.
# Portée : référentiel et comptes sont MUTUALISÉS au niveau organisation ;
# journaux, exercices et écritures sont RATTACHÉS à une société.


class ComptaSociete(Base):
    """Entité juridique tenant une comptabilité propre (bilan et résultat autonomes)."""

    __tablename__ = "compta_societes"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_compta_societe_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    raison_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    forme_juridique: Mapped[str | None] = mapped_column(String(100), nullable=True)
    identifiant_fiscal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rccm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Devise de tenue par défaut des exercices de cette société.
    devise_tenue: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    # Société créée d'office pour l'organisation (mode mono-société).
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Compte comptable (571) pour les opérations en canal CAISSE utilisant la
    # caisse unique (`CaisseCentrale`, singleton par organisation) plutôt
    # qu'un `CompteBancaire` de type CASH nommé individuellement — ces
    # derniers restent mappés via `ComptaMappingCompteBancaire`.
    compte_caisse_defaut_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="SET NULL"), nullable=True
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ComptaEtablissement(Base):
    """Établissement (site, agence, succursale) rattaché à une société.

    Ne tient pas de comptabilité autonome : sert d'axe de ventilation et de
    restitution (balance par établissement).
    """

    __tablename__ = "compta_etablissements"
    __table_args__ = (
        UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_etab_societe_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_siege: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# ── Référentiel : plan comptable ─────────────────────────────────────────────


class ComptaReferentiel(Base):
    """Plan comptable de référence. Plusieurs référentiels coexistent par organisation."""

    __tablename__ = "compta_referentiels"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_compta_referentiel_org_code"),
        CheckConstraint(
            "type_referentiel IN ('SYSCOHADA','SYSCEBNL','PCG','ASSOCIATIF','ONG','PERSONNALISE')",
            name="ck_compta_referentiel_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    type_referentiel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Référentiel utilisé par défaut pour les nouveaux exercices de l'organisation.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_import: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    comptes: Mapped[list["ComptaCompte"]] = relationship(back_populates="referentiel")


class ComptaCompte(Base):
    """Compte du plan comptable. Aucun numéro n'est codé en dur ailleurs dans l'application."""

    __tablename__ = "compta_comptes"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "referentiel_id", "numero", name="uq_compta_compte_org_ref_numero"
        ),
        CheckConstraint(
            "nature IN ('ACTIF','PASSIF','CHARGE','PRODUIT','ENGAGEMENT')", name="ck_compta_compte_nature"
        ),
        CheckConstraint("sens_normal IN ('DEBIT','CREDIT')", name="ck_compta_compte_sens"),
        Index("ix_compta_compte_org_ref_numero", "organisation_id", "referentiel_id", "numero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    referentiel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_referentiels.id", ondelete="CASCADE"), nullable=False, index=True
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    classe: Mapped[str | None] = mapped_column(String(5), nullable=True)
    sous_classe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Hiérarchie du plan (compte père) — facilite les restitutions agrégées.
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Collectif / auxiliaire : un compte auxiliaire (411CLI001) se rattache à son collectif (411).
    is_collectif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_auxiliaire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    compte_collectif_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    nature: Mapped[str] = mapped_column(String(20), nullable=False)
    sens_normal: Mapped[str] = mapped_column(String(10), nullable=False, default="DEBIT")

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    analytique_obligatoire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lettrable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # NULL = toutes devises autorisées.
    devise_autorisee: Mapped[str | None] = mapped_column(String(3), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    referentiel: Mapped["ComptaReferentiel"] = relationship(back_populates="comptes")


class ComptaJournal(Base):
    """Journal comptable. Nombre illimité, typé."""

    __tablename__ = "compta_journaux"
    __table_args__ = (
        UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_journal_societe_code"),
        CheckConstraint(
            "type_journal IN ('BQ','CA','AC','VE','OD','SAL','IMMO','CLO','OUV','TVA','AJU')",
            name="ck_compta_journal_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    type_journal: Mapped[str] = mapped_column(String(10), nullable=False)
    # Contrepartie automatique (ex. journal Banque → compte 512x).
    compte_contrepartie_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="SET NULL"), nullable=True
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# ── Exercices et périodes ────────────────────────────────────────────────────


class ComptaExercice(Base):
    """Exercice comptable. La devise de tenue est paramétrable (défaut USD)."""

    __tablename__ = "compta_exercices"
    __table_args__ = (
        UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_exercice_societe_code"),
        CheckConstraint(
            "statut IN ('OUVERT','FERME','ROUVERT','CLOTURE','VERROUILLE')", name="ck_compta_exercice_statut"
        ),
        CheckConstraint("date_fin > date_debut", name="ck_compta_exercice_dates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    referentiel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_referentiels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Devise de tenue de la comptabilité (défaut USD, paramétrable, convertible).
    devise_tenue: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="OUVERT", index=True)

    # Report des à-nouveaux depuis l'exercice précédent.
    exercice_precedent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_exercices.id", ondelete="SET NULL"), nullable=True
    )
    a_nouveaux_generes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    cloture_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cloture_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verrouille_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verrouille_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ComptaPeriode(Base):
    """Période (mois) d'un exercice — verrouillable indépendamment de la clôture annuelle."""

    __tablename__ = "compta_periodes"
    __table_args__ = (
        UniqueConstraint("exercice_id", "numero", name="uq_compta_periode_exercice_numero"),
        CheckConstraint("statut IN ('OUVERTE','FERMEE')", name="ck_compta_periode_statut"),
        CheckConstraint("numero BETWEEN 1 AND 12", name="ck_compta_periode_numero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    exercice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_exercices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="OUVERTE")
    fermee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Taux de change historisés ────────────────────────────────────────────────


class ComptaTauxChange(Base):
    """Taux de change historisé. Une écriture fige son taux : aucune réévaluation rétroactive."""

    __tablename__ = "compta_taux_change"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "devise_source", "devise_cible", "date_taux", name="uq_compta_taux_unique"
        ),
        CheckConstraint("taux > 0", name="ck_compta_taux_positif"),
        Index("ix_compta_taux_lookup", "organisation_id", "devise_source", "devise_cible", "date_taux"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    devise_source: Mapped[str] = mapped_column(String(3), nullable=False)
    devise_cible: Mapped[str] = mapped_column(String(3), nullable=False)
    taux: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    date_taux: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# ── Numérotation comptable ───────────────────────────────────────────────────


class ComptaSequence(Base):
    """Compteur de numérotation des pièces comptables.

    Volontairement distinct de `document_sequences` :
    - les codes OD / CLO / OUV y sont déjà pris (ordre de décaissement,
      clôture et ouverture de caisse) ;
    - `document_sequences` est calé sur l'ANNÉE CIVILE, alors qu'une pièce
      comptable se numérote par EXERCICE et par JOURNAL.
    """

    __tablename__ = "compta_sequences"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "societe_id", "exercice_id", "journal_id", name="uq_compta_sequence_unique"
        ),
        CheckConstraint("compteur >= 0", name="ck_compta_sequence_compteur"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_exercices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    journal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_journaux.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compteur: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# ── Écritures ────────────────────────────────────────────────────────────────


class ComptaEcriture(Base):
    """Entête d'écriture comptable.

    Invariants (garantis en base autant que possible) :
    - équilibre débit = crédit (contrôlé à la validation, cf. service) ;
    - date dans un exercice ouvert ;
    - immuabilité une fois VALIDEE (trigger ajouté par migration) ;
    - aucune suppression physique : ANNULEE + contre-passation.
    """

    __tablename__ = "compta_ecritures"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "societe_id", "exercice_id", "journal_id", "numero",
            name="uq_compta_ecriture_numero",
        ),
        CheckConstraint(
            "statut IN ('BROUILLON','VALIDEE','CLOTUREE','ANNULEE')", name="ck_compta_ecriture_statut"
        ),
        Index("ix_compta_ecriture_soc_ex_date", "organisation_id", "societe_id", "exercice_id", "date_ecriture"),
        Index("ix_compta_ecriture_origine", "organisation_id", "module_origine", "objet_origine_id"),
        # Idempotence de la génération automatique (Lot 2) : un même fait
        # générateur ne peut jamais produire deux écritures. NULL (écritures
        # manuelles, sans origine) n'est pas contraint par l'index partiel.
        Index(
            "uq_compta_ecriture_origine_idempotence",
            "organisation_id", "module_origine", "type_origine", "objet_origine_id",
            unique=True,
            postgresql_where=text(
                "module_origine IS NOT NULL AND type_origine IS NOT NULL AND objet_origine_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    etablissement_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_etablissements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    exercice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_exercices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    journal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_journaux.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # NULL tant que l'écriture est au brouillon : le numéro n'est attribué qu'à
    # la validation (pas de trou de séquence). PostgreSQL traitant les NULL
    # comme distincts, plusieurs brouillons coexistent sans heurter l'unicité.
    numero: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_ecriture: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    date_piece: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference_piece: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="BROUILLON", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    # Taux figé au moment de l'écriture (vers la devise de tenue de l'exercice).
    taux_change: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"))

    # Traçabilité de l'origine (la table de liaison dédiée arrive au Lot 2).
    module_origine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    type_origine: Mapped[str | None] = mapped_column(String(80), nullable=True)
    objet_origine_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    est_automatique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    justificatif_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    valide_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Contre-passation : lien réciproque, jamais de modification de l'écriture d'origine.
    contrepasse_ecriture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compta_ecritures.id", ondelete="SET NULL"), nullable=True
    )
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)
    annule_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    lignes: Mapped[list["ComptaLigneEcriture"]] = relationship(
        back_populates="ecriture", cascade="all, delete-orphan"
    )


class ComptaLigneEcriture(Base):
    """Ligne d'écriture. Débit et crédit sont toujours positifs et mutuellement exclusifs."""

    __tablename__ = "compta_lignes_ecriture"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_compta_ligne_montants_positifs"),
        CheckConstraint("NOT (debit > 0 AND credit > 0)", name="ck_compta_ligne_sens_exclusif"),
        CheckConstraint("(debit + credit) > 0", name="ck_compta_ligne_non_nulle"),
        Index("ix_compta_ligne_soc_compte", "organisation_id", "societe_id", "compte_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Dénormalisé depuis l'écriture : évite une jointure sur les restitutions
    # (Grand Livre, balances) qui portent sur des millions de lignes.
    societe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_societes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ecriture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compta_ecritures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compte_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    compte_auxiliaire_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Montants dans la devise de l'écriture.
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Contre-valeur figée dans la devise de tenue de l'exercice.
    debit_tenue: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit_tenue: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    taux_change: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"))

    # Lettrage (rapprochement des comptes de tiers) et échéance.
    lettrage: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    date_echeance: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    ecriture: Mapped["ComptaEcriture"] = relationship(back_populates="lignes")


# ── Mappings — résolution de comptes (Lot 2) ─────────────────────────────────
#
# Aucun numéro de compte codé en dur (cf. §2 du dossier d'architecture) :
# le poste budgétaire et le compte bancaire d'une opération métier se
# résolvent vers un compte comptable via ces tables de paramétrage, jamais
# par une valeur en Python. Un mapping absent est un échec bloquant à la
# génération (décision actée) — pas de compte d'attente silencieux.


class ComptaMappingPosteBudgetaire(Base):
    """Associe un poste budgétaire (charge ou recette) à son compte comptable."""

    __tablename__ = "compta_mapping_poste_budgetaire"
    __table_args__ = (
        UniqueConstraint("organisation_id", "budget_poste_id", name="uq_compta_mapping_poste_budgetaire"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    budget_poste_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_postes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compte_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ComptaMappingRubrique(Base):
    """Associe une RUBRIQUE TECHNIQUE à son compte comptable (Lot 3).

    Certains faits générateurs n'ont ni poste budgétaire ni compte bancaire
    pour porter la résolution : la paie (charges de personnel, net dû au
    personnel, cotisations sociales, IPR retenu) et les encaissements créés
    sans poste budgétaire (paiement en ligne encaissé par webhook).

    Le paramétrage reste donc en base — aucun numéro de compte n'apparaît en
    Python — mais la clé de résolution est un CODE fonctionnel stable
    (cf. `RUBRIQUES_TECHNIQUES`) plutôt qu'un identifiant d'objet métier.
    """

    __tablename__ = "compta_mapping_rubrique"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code_rubrique", name="uq_compta_mapping_rubrique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code_rubrique: Mapped[str] = mapped_column(String(60), nullable=False)
    compte_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


# Codes de rubriques techniques reconnus par le moteur de génération.
# Ajouter un code ici n'a d'effet qu'une fois le mapping renseigné pour
# l'organisation (échec bloquant sinon, comme pour les autres résolutions).
RUBRIQUE_PAIE_CHARGES_PERSONNEL = "PAIE_CHARGES_PERSONNEL"
RUBRIQUE_PAIE_PERSONNEL_DU = "PAIE_PERSONNEL_DU"
RUBRIQUE_PAIE_ORGANISMES_SOCIAUX = "PAIE_ORGANISMES_SOCIAUX"
RUBRIQUE_PAIE_ETAT_IPR = "PAIE_ETAT_IPR"
RUBRIQUE_PRODUIT_PAIEMENT_EN_LIGNE = "PRODUIT_PAIEMENT_EN_LIGNE"

RUBRIQUES_TECHNIQUES = (
    RUBRIQUE_PAIE_CHARGES_PERSONNEL,
    RUBRIQUE_PAIE_PERSONNEL_DU,
    RUBRIQUE_PAIE_ORGANISMES_SOCIAUX,
    RUBRIQUE_PAIE_ETAT_IPR,
    RUBRIQUE_PRODUIT_PAIEMENT_EN_LIGNE,
)

# Libellé et rôle de chaque rubrique, affichés dans l'écran de paramétrage :
# un code technique seul ne dit pas à un comptable ce qu'il doit y mapper.
RUBRIQUES_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    RUBRIQUE_PAIE_CHARGES_PERSONNEL: (
        "Paie — charges de personnel",
        "Débité du salaire brut à la validation d'un run de paie (compte 66x).",
    ),
    RUBRIQUE_PAIE_PERSONNEL_DU: (
        "Paie — net dû au personnel",
        "Crédité du net à payer : c'est la dette envers les salariés, soldée par le versement (compte 42x).",
    ),
    RUBRIQUE_PAIE_ORGANISMES_SOCIAUX: (
        "Paie — cotisations sociales retenues",
        "Crédité de la retenue CNSS salarié, en attente de reversement (compte 43x).",
    ),
    RUBRIQUE_PAIE_ETAT_IPR: (
        "Paie — IPR retenu à la source",
        "Crédité de l'impôt professionnel retenu, en attente de reversement (compte 44x).",
    ),
    RUBRIQUE_PRODUIT_PAIEMENT_EN_LIGNE: (
        "Produit — paiement en ligne",
        "Crédité lors d'un encaissement par carte ou mobile money, qui n'a pas de poste budgétaire.",
    ),
}


class ComptaMappingCompteBancaire(Base):
    """Associe un compte bancaire/caisse (trésorerie) à son compte comptable (512x/571)."""

    __tablename__ = "compta_mapping_compte_bancaire"
    __table_args__ = (
        UniqueConstraint("organisation_id", "compte_bancaire_id", name="uq_compta_mapping_compte_bancaire"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    compte_bancaire_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("comptes_bancaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compte_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("compta_comptes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
