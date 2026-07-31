"""Module Comptabilité — Lot 1 : fondations (référentiel, exercices, écritures)

Crée le socle de la comptabilité en partie double :
société/établissement, référentiel et plan comptable, journaux, exercices,
périodes, taux de change historisés, écritures et lignes d'écriture.

Garanties posées AU NIVEAU BASE (pas seulement applicatives) :
- débit et crédit toujours >= 0, mutuellement exclusifs, ligne jamais nulle ;
- statuts et types contrôlés par CHECK ;
- unicité de la numérotation par société / exercice / journal ;
- IMMUTABILITÉ : une écriture validée ne peut plus être modifiée ni supprimée
  (seule l'annulation est permise, via contre-passation) — trigger dédié.

Revision ID: 20260731_compta_fondations
Revises: 20260725_grant_authorize_disb
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260731_compta_fondations"
down_revision = "20260725_grant_authorize_disb"
branch_labels = None
depends_on = None


# Exposées en constantes (plutôt qu'inline dans upgrade()) pour être rejouables
# telles quelles par les tests d'intégration, qui construisent leur schéma via
# `Base.metadata.create_all` et n'exécutent donc pas les migrations Alembic.
TRIGGER_ECRITURE_FUNCTION_SQL = """
    CREATE OR REPLACE FUNCTION compta_ecriture_immutable() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.statut <> 'BROUILLON' THEN
                RAISE EXCEPTION
                    'Suppression interdite : une écriture % (statut %) est immuable. Utilisez la contre-passation.',
                    OLD.numero, OLD.statut;
            END IF;
            RETURN OLD;
        END IF;

        -- UPDATE
        IF OLD.statut = 'BROUILLON' THEN
            RETURN NEW;  -- un brouillon reste librement modifiable
        END IF;

        -- Écriture non brouillon : seuls les champs d'annulation peuvent bouger.
        IF NEW.exercice_id IS DISTINCT FROM OLD.exercice_id
           OR NEW.journal_id IS DISTINCT FROM OLD.journal_id
           OR NEW.societe_id IS DISTINCT FROM OLD.societe_id
           OR NEW.numero IS DISTINCT FROM OLD.numero
           OR NEW.date_ecriture IS DISTINCT FROM OLD.date_ecriture
           OR NEW.libelle IS DISTINCT FROM OLD.libelle
           OR NEW.devise IS DISTINCT FROM OLD.devise
           OR NEW.taux_change IS DISTINCT FROM OLD.taux_change
        THEN
            RAISE EXCEPTION
                'Modification interdite : l''écriture % est validée (statut %). Utilisez la contre-passation.',
                OLD.numero, OLD.statut;
        END IF;

        -- Transition de statut autorisée : uniquement vers ANNULEE.
        IF NEW.statut IS DISTINCT FROM OLD.statut AND NEW.statut <> 'ANNULEE' THEN
            RAISE EXCEPTION
                'Transition de statut interdite (% -> %) sur l''écriture %.',
                OLD.statut, NEW.statut, OLD.numero;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""

TRIGGER_ECRITURE_CREATE_SQL = """
    CREATE TRIGGER trg_compta_ecriture_immutable
    BEFORE UPDATE OR DELETE ON compta_ecritures
    FOR EACH ROW EXECUTE FUNCTION compta_ecriture_immutable();
"""

TRIGGER_LIGNE_FUNCTION_SQL = """
    CREATE OR REPLACE FUNCTION compta_ligne_immutable() RETURNS trigger AS $$
    DECLARE
        v_statut text;
        v_ecriture uuid;
    BEGIN
        v_ecriture := CASE WHEN TG_OP = 'DELETE' THEN OLD.ecriture_id ELSE NEW.ecriture_id END;
        SELECT statut INTO v_statut FROM compta_ecritures WHERE id = v_ecriture;

        -- Si l'écriture a déjà disparu (CASCADE d'un brouillon), on laisse faire.
        IF v_statut IS NULL THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END IF;

        IF v_statut <> 'BROUILLON' THEN
            RAISE EXCEPTION
                'Lignes figées : l''écriture % n''est plus au brouillon (statut %).',
                v_ecriture, v_statut;
        END IF;

        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END;
    $$ LANGUAGE plpgsql;
"""

TRIGGER_LIGNE_CREATE_SQL = """
    CREATE TRIGGER trg_compta_ligne_immutable
    BEFORE UPDATE OR DELETE ON compta_lignes_ecriture
    FOR EACH ROW EXECUTE FUNCTION compta_ligne_immutable();
"""


def upgrade() -> None:
    # ── Société / établissement ──────────────────────────────────────────────
    op.create_table(
        "compta_societes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("raison_sociale", sa.String(length=255), nullable=False),
        sa.Column("forme_juridique", sa.String(length=100), nullable=True),
        sa.Column("identifiant_fiscal", sa.String(length=50), nullable=True),
        sa.Column("rccm", sa.String(length=50), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("devise_tenue", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "code", name="uq_compta_societe_org_code"),
    )

    op.create_table(
        "compta_etablissements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("is_siege", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_etab_societe_code"),
    )

    # ── Référentiel et plan comptable ────────────────────────────────────────
    op.create_table(
        "compta_referentiels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("libelle", sa.String(length=200), nullable=False),
        sa.Column("type_referentiel", sa.String(length=20), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_import", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "code", name="uq_compta_referentiel_org_code"),
        sa.CheckConstraint(
            "type_referentiel IN ('SYSCOHADA','SYSCEBNL','PCG','ASSOCIATIF','ONG','PERSONNALISE')",
            name="ck_compta_referentiel_type",
        ),
    )

    op.create_table(
        "compta_comptes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "referentiel_id",
            sa.Integer(),
            sa.ForeignKey("compta_referentiels.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("numero", sa.String(length=30), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("classe", sa.String(length=5), nullable=True),
        sa.Column("sous_classe", sa.String(length=10), nullable=True),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("is_collectif", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_auxiliaire", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "compte_collectif_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("nature", sa.String(length=20), nullable=False),
        sa.Column("sens_normal", sa.String(length=10), nullable=False, server_default="DEBIT"),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("analytique_obligatoire", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lettrable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("devise_autorisee", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "referentiel_id", "numero", name="uq_compta_compte_org_ref_numero"
        ),
        sa.CheckConstraint(
            "nature IN ('ACTIF','PASSIF','CHARGE','PRODUIT','ENGAGEMENT')", name="ck_compta_compte_nature"
        ),
        sa.CheckConstraint("sens_normal IN ('DEBIT','CREDIT')", name="ck_compta_compte_sens"),
    )
    op.create_index(
        "ix_compta_compte_org_ref_numero", "compta_comptes", ["organisation_id", "referentiel_id", "numero"]
    )

    # ── Journaux ─────────────────────────────────────────────────────────────
    op.create_table(
        "compta_journaux",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("libelle", sa.String(length=200), nullable=False),
        sa.Column("type_journal", sa.String(length=10), nullable=False),
        sa.Column(
            "compte_contrepartie_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_journal_societe_code"),
        sa.CheckConstraint(
            "type_journal IN ('BQ','CA','AC','VE','OD','SAL','IMMO','CLO','OUV','TVA','AJU')",
            name="ck_compta_journal_type",
        ),
    )

    # ── Exercices et périodes ────────────────────────────────────────────────
    op.create_table(
        "compta_exercices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("libelle", sa.String(length=200), nullable=True),
        sa.Column("date_debut", sa.Date(), nullable=False),
        sa.Column("date_fin", sa.Date(), nullable=False),
        sa.Column(
            "referentiel_id",
            sa.Integer(),
            sa.ForeignKey("compta_referentiels.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("devise_tenue", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="OUVERT", index=True),
        sa.Column(
            "exercice_precedent_id",
            sa.Integer(),
            sa.ForeignKey("compta_exercices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("a_nouveaux_generes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cloture_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cloture_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verrouille_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verrouille_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "societe_id", "code", name="uq_compta_exercice_societe_code"),
        sa.CheckConstraint(
            "statut IN ('OUVERT','FERME','ROUVERT','CLOTURE','VERROUILLE')", name="ck_compta_exercice_statut"
        ),
        sa.CheckConstraint("date_fin > date_debut", name="ck_compta_exercice_dates"),
    )

    op.create_table(
        "compta_periodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "exercice_id",
            sa.Integer(),
            sa.ForeignKey("compta_exercices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("date_debut", sa.Date(), nullable=False),
        sa.Column("date_fin", sa.Date(), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="OUVERTE"),
        sa.Column("fermee_le", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("exercice_id", "numero", name="uq_compta_periode_exercice_numero"),
        sa.CheckConstraint("statut IN ('OUVERTE','FERMEE')", name="ck_compta_periode_statut"),
        sa.CheckConstraint("numero BETWEEN 1 AND 12", name="ck_compta_periode_numero"),
    )

    # ── Taux de change historisés ────────────────────────────────────────────
    op.create_table(
        "compta_taux_change",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("devise_source", sa.String(length=3), nullable=False),
        sa.Column("devise_cible", sa.String(length=3), nullable=False),
        sa.Column("taux", sa.Numeric(18, 8), nullable=False),
        sa.Column("date_taux", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "devise_source", "devise_cible", "date_taux", name="uq_compta_taux_unique"
        ),
        sa.CheckConstraint("taux > 0", name="ck_compta_taux_positif"),
    )
    op.create_index(
        "ix_compta_taux_lookup",
        "compta_taux_change",
        ["organisation_id", "devise_source", "devise_cible", "date_taux"],
    )

    # ── Numérotation comptable (distincte de document_sequences) ─────────────
    op.create_table(
        "compta_sequences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "exercice_id",
            sa.Integer(),
            sa.ForeignKey("compta_exercices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("compta_journaux.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("compteur", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "societe_id", "exercice_id", "journal_id", name="uq_compta_sequence_unique"
        ),
        sa.CheckConstraint("compteur >= 0", name="ck_compta_sequence_compteur"),
    )

    # ── Écritures ────────────────────────────────────────────────────────────
    op.create_table(
        "compta_ecritures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "etablissement_id",
            sa.Integer(),
            sa.ForeignKey("compta_etablissements.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "exercice_id",
            sa.Integer(),
            sa.ForeignKey("compta_exercices.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("compta_journaux.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        # NULL au brouillon : le numéro n'est attribué qu'à la validation.
        # Les NULL étant distincts en PostgreSQL, plusieurs brouillons du même
        # journal coexistent sans violer l'unicité.
        sa.Column("numero", sa.String(length=50), nullable=True),
        sa.Column("date_ecriture", sa.Date(), nullable=False, index=True),
        sa.Column("date_piece", sa.Date(), nullable=True),
        sa.Column("reference_piece", sa.String(length=100), nullable=True, index=True),
        sa.Column("libelle", sa.Text(), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="BROUILLON", index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("taux_change", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("module_origine", sa.String(length=50), nullable=True),
        sa.Column("type_origine", sa.String(length=80), nullable=True),
        sa.Column("objet_origine_id", sa.String(length=64), nullable=True),
        sa.Column("est_automatique", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("justificatif_path", sa.String(length=500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("valide_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("valide_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "contrepasse_ecriture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compta_ecritures.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        sa.Column("annule_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "societe_id", "exercice_id", "journal_id", "numero",
            name="uq_compta_ecriture_numero",
        ),
        sa.CheckConstraint(
            "statut IN ('BROUILLON','VALIDEE','CLOTUREE','ANNULEE')", name="ck_compta_ecriture_statut"
        ),
    )
    op.create_index(
        "ix_compta_ecriture_soc_ex_date",
        "compta_ecritures",
        ["organisation_id", "societe_id", "exercice_id", "date_ecriture"],
    )
    op.create_index(
        "ix_compta_ecriture_origine",
        "compta_ecritures",
        ["organisation_id", "module_origine", "objet_origine_id"],
    )

    op.create_table(
        "compta_lignes_ecriture",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "societe_id",
            sa.Integer(),
            sa.ForeignKey("compta_societes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "ecriture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compta_ecritures.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "compte_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "compte_auxiliaire_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("libelle", sa.Text(), nullable=True),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("debit_tenue", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_tenue", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taux_change", sa.Numeric(18, 8), nullable=False, server_default="1"),
        sa.Column("lettrage", sa.String(length=20), nullable=True, index=True),
        sa.Column("date_echeance", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_compta_ligne_montants_positifs"),
        sa.CheckConstraint("NOT (debit > 0 AND credit > 0)", name="ck_compta_ligne_sens_exclusif"),
        sa.CheckConstraint("(debit + credit) > 0", name="ck_compta_ligne_non_nulle"),
    )
    op.create_index(
        "ix_compta_ligne_soc_compte", "compta_lignes_ecriture", ["organisation_id", "societe_id", "compte_id"]
    )
    # (ecriture_id est déjà indexé via index=True sur la colonne)

    # ── Immutabilité des écritures validées ──────────────────────────────────
    # Une écriture VALIDEE/CLOTUREE/ANNULEE ne peut plus être modifiée : seule
    # l'annulation (contre-passation) est permise, et uniquement via les champs
    # dédiés. Aucune suppression physique hors brouillon.
    op.execute(TRIGGER_ECRITURE_FUNCTION_SQL)
    op.execute(TRIGGER_ECRITURE_CREATE_SQL)

    # Les lignes suivent le sort de leur écriture : figées dès que l'écriture
    # n'est plus au brouillon.
    op.execute(TRIGGER_LIGNE_FUNCTION_SQL)
    op.execute(TRIGGER_LIGNE_CREATE_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_compta_ligne_immutable ON compta_lignes_ecriture;")
    op.execute("DROP FUNCTION IF EXISTS compta_ligne_immutable();")
    op.execute("DROP TRIGGER IF EXISTS trg_compta_ecriture_immutable ON compta_ecritures;")
    op.execute("DROP FUNCTION IF EXISTS compta_ecriture_immutable();")

    op.drop_table("compta_lignes_ecriture")
    op.drop_table("compta_ecritures")
    op.drop_table("compta_sequences")
    op.drop_table("compta_taux_change")
    op.drop_table("compta_periodes")
    op.drop_table("compta_exercices")
    op.drop_table("compta_journaux")
    op.drop_table("compta_comptes")
    op.drop_table("compta_referentiels")
    op.drop_table("compta_etablissements")
    op.drop_table("compta_societes")
