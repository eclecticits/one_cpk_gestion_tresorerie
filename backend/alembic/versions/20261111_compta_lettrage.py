"""Lettrage des comptes de tiers

Ajoute la date et l'auteur du lettrage sur les lignes d'écriture, et assouplit
le trigger d'immuabilité des lignes : sur une écriture validée, seules les
trois colonnes de lettrage peuvent changer. Lettrer n'altère ni un montant ni
un compte — c'est un pointage — mais sans cette exception le trigger refuserait
tout lettrage, puisqu'on ne lettre que des écritures validées.

Revision ID: 20261111_compta_lettrage
Revises: 20261110_virements_internes
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261111_compta_lettrage"
down_revision = "20261110_virements_internes"
branch_labels = None
depends_on = None


# La comparaison se fait sur la ligne entière privée des colonnes de lettrage :
# une colonne ajoutée plus tard sera figée d'office, sans retoucher le trigger.
TRIGGER_LIGNE_FUNCTION_LETTRAGE = """
CREATE OR REPLACE FUNCTION compta_ligne_immutable() RETURNS trigger AS $$
DECLARE
    v_statut text;
    v_ecriture uuid;
BEGIN
    IF current_setting('onec.admin_reset', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    v_ecriture := CASE WHEN TG_OP = 'DELETE' THEN OLD.ecriture_id ELSE NEW.ecriture_id END;
    SELECT statut INTO v_statut FROM compta_ecritures WHERE id = v_ecriture;

    IF v_statut IS NULL THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;

    IF v_statut <> 'BROUILLON' THEN
        IF TG_OP = 'UPDATE'
           AND v_statut IN ('VALIDEE', 'CLOTUREE')
           AND (to_jsonb(NEW) - 'lettrage' - 'date_lettrage' - 'lettre_par')
               = (to_jsonb(OLD) - 'lettrage' - 'date_lettrage' - 'lettre_par')
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'Lignes figées : l''écriture % n''est plus au brouillon (statut %).',
            v_ecriture, v_statut;
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_LIGNE_FUNCTION_AVANT = """
CREATE OR REPLACE FUNCTION compta_ligne_immutable() RETURNS trigger AS $$
DECLARE
    v_statut text;
    v_ecriture uuid;
BEGIN
    IF current_setting('onec.admin_reset', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    v_ecriture := CASE WHEN TG_OP = 'DELETE' THEN OLD.ecriture_id ELSE NEW.ecriture_id END;
    SELECT statut INTO v_statut FROM compta_ecritures WHERE id = v_ecriture;

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


def upgrade() -> None:
    op.add_column("compta_lignes_ecriture", sa.Column("date_lettrage", sa.Date(), nullable=True))
    op.add_column(
        "compta_lignes_ecriture",
        sa.Column("lettre_par", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_compta_ligne_compte_lettrage",
        "compta_lignes_ecriture",
        ["organisation_id", "compte_id", "lettrage"],
    )
    op.execute(TRIGGER_LIGNE_FUNCTION_LETTRAGE)
    # Les comptes de tiers existants deviennent lettrables : sans cela l'écran
    # de lettrage s'ouvrirait vide sur toutes les organisations déjà en service.
    op.execute(
        "UPDATE compta_comptes SET lettrable = true "
        "WHERE numero LIKE '4%' AND lettrable = false"
    )


def downgrade() -> None:
    op.execute(TRIGGER_LIGNE_FUNCTION_AVANT)
    op.drop_index("ix_compta_ligne_compte_lettrage", table_name="compta_lignes_ecriture")
    op.drop_column("compta_lignes_ecriture", "lettre_par")
    op.drop_column("compta_lignes_ecriture", "date_lettrage")
