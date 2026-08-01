"""Module Comptabilité (Lot 5) — postes d'état financier et mapping

`compta_postes_etat` : structure d'un état (Bilan, Résultat, SIG, Flux),
rattachée à un référentiel — c'est une DONNÉE, pas du code, pour que
SYSCOHADA, SYSCEBNL et un plan personnalisé coexistent.

`compta_poste_etat_comptes` : rattachement des comptes à un poste, par
préfixe (cas courant) ou compte précis (exception), avec signe, filtre de
sens et colonne (brut / amortissement).

Ajoute aussi le journal de report à-nouveaux (`AN`) aux types autorisés.

Revision ID: 20260801_compta_etats
Revises: 20260731_compta_rubriques
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_compta_etats"
down_revision = "20260731_compta_rubriques"
branch_labels = None
depends_on = None

# Le type AN (à-nouveaux) n'existait pas au Lot 1 : la contrainte de type de
# journal doit être élargie avant que la clôture puisse créer ce journal.
TYPES_JOURNAL_AVANT = "'BQ','CA','AC','VE','OD','SAL','IMMO','CLO','OUV','TVA','AJU'"
TYPES_JOURNAL_APRES = TYPES_JOURNAL_AVANT + ",'AN'"

# Le trigger d'immuabilité du Lot 1 n'autorisait qu'une seule transition de
# statut sur une écriture non brouillon : vers ANNULEE. La clôture d'exercice
# doit pouvoir passer les écritures VALIDEE à CLOTUREE — un DURCISSEMENT (elles
# deviennent encore moins modifiables), pas une modification comptable. Sans
# cette évolution, `cloturer_exercice` échouerait en production.
TRIGGER_ECRITURE_FUNCTION_LOT1 = """
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

        IF OLD.statut = 'BROUILLON' THEN
            RETURN NEW;
        END IF;

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

        IF NEW.statut IS DISTINCT FROM OLD.statut AND NEW.statut <> 'ANNULEE' THEN
            RAISE EXCEPTION
                'Transition de statut interdite (% -> %) sur l''écriture %.',
                OLD.statut, NEW.statut, OLD.numero;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""

TRIGGER_ECRITURE_FUNCTION_LOT5 = """
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

        -- Transitions autorisées : annulation (contre-passation) et clôture
        -- d'exercice (VALIDEE -> CLOTUREE). Toute autre est refusée, en
        -- particulier une réouverture CLOTUREE -> VALIDEE.
        IF NEW.statut IS DISTINCT FROM OLD.statut
           AND NEW.statut <> 'ANNULEE'
           AND NOT (OLD.statut = 'VALIDEE' AND NEW.statut = 'CLOTUREE')
        THEN
            RAISE EXCEPTION
                'Transition de statut interdite (% -> %) sur l''écriture %.',
                OLD.statut, NEW.statut, OLD.numero;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "compta_postes_etat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id", sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "referentiel_id", sa.Integer(),
            sa.ForeignKey("compta_referentiels.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("type_etat", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("niveau", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_id", sa.Integer(),
            sa.ForeignKey("compta_postes_etat.id", ondelete="CASCADE"), nullable=True, index=True,
        ),
        sa.Column("est_total", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sens_normal", sa.String(length=10), nullable=False, server_default="DEBIT"),
        sa.Column("signe", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "organisation_id", "referentiel_id", "type_etat", "code",
            name="uq_compta_poste_etat_code",
        ),
        sa.CheckConstraint(
            "type_etat IN ('BILAN_ACTIF','BILAN_PASSIF','RESULTAT','SIG','FLUX')",
            name="ck_compta_poste_etat_type",
        ),
        sa.CheckConstraint("sens_normal IN ('DEBIT','CREDIT')", name="ck_compta_poste_etat_sens"),
        sa.CheckConstraint("signe IN (-1, 1)", name="ck_compta_poste_etat_signe"),
    )
    op.create_index(
        "ix_compta_poste_etat_ref_type",
        "compta_postes_etat",
        ["organisation_id", "referentiel_id", "type_etat", "ordre"],
    )

    op.create_table(
        "compta_poste_etat_comptes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id", sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "poste_etat_id", sa.Integer(),
            sa.ForeignKey("compta_postes_etat.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("prefixe_compte", sa.String(length=30), nullable=True),
        sa.Column(
            "compte_id", sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="CASCADE"), nullable=True, index=True,
        ),
        sa.Column("signe", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("filtre_solde", sa.String(length=20), nullable=False, server_default="TOUS"),
        sa.Column("colonne", sa.String(length=20), nullable=False, server_default="BRUT"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "(prefixe_compte IS NOT NULL AND compte_id IS NULL) "
            "OR (prefixe_compte IS NULL AND compte_id IS NOT NULL)",
            name="ck_compta_poste_etat_compte_source",
        ),
        sa.CheckConstraint("signe IN (-1, 1)", name="ck_compta_poste_etat_compte_signe"),
        sa.CheckConstraint(
            "filtre_solde IN ('TOUS','DEBITEUR','CREDITEUR')", name="ck_compta_poste_etat_compte_filtre"
        ),
        sa.CheckConstraint(
            "colonne IN ('BRUT','AMORTISSEMENT')", name="ck_compta_poste_etat_compte_colonne"
        ),
    )
    op.create_index(
        "ix_compta_poste_etat_compte_poste",
        "compta_poste_etat_comptes",
        ["organisation_id", "poste_etat_id"],
    )

    op.drop_constraint("ck_compta_journal_type", "compta_journaux", type_="check")
    op.create_check_constraint(
        "ck_compta_journal_type", "compta_journaux", f"type_journal IN ({TYPES_JOURNAL_APRES})"
    )

    op.execute(TRIGGER_ECRITURE_FUNCTION_LOT5)


def downgrade() -> None:
    # Restaure la version du Lot 1 (sans la transition VALIDEE -> CLOTUREE).
    op.execute(TRIGGER_ECRITURE_FUNCTION_LOT1)
    # Les journaux de type AN doivent disparaître avant de restreindre la
    # contrainte, sinon le downgrade échoue sur les données existantes.
    op.execute("DELETE FROM compta_journaux WHERE type_journal = 'AN'")
    op.drop_constraint("ck_compta_journal_type", "compta_journaux", type_="check")
    op.create_check_constraint(
        "ck_compta_journal_type", "compta_journaux", f"type_journal IN ({TYPES_JOURNAL_AVANT})"
    )

    op.drop_index("ix_compta_poste_etat_compte_poste", table_name="compta_poste_etat_comptes")
    op.drop_table("compta_poste_etat_comptes")
    op.drop_index("ix_compta_poste_etat_ref_type", table_name="compta_postes_etat")
    op.drop_table("compta_postes_etat")
