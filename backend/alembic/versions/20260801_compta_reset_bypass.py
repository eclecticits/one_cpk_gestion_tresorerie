"""Bypass administratif transactionnel pour reset comptable

Revision ID: 20260801_compta_reset_bypass
Revises: 20260801_req_reset_bypass
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op


revision = "20260801_compta_reset_bypass"
down_revision = "20260801_req_reset_bypass"
branch_labels = None
depends_on = None


COMPTA_ECRITURE_FUNCTION_WITH_ADMIN_BYPASS = """
CREATE OR REPLACE FUNCTION compta_ecriture_immutable() RETURNS trigger AS $$
BEGIN
    IF current_setting('onec.admin_reset', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

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


COMPTA_LIGNE_FUNCTION_WITH_ADMIN_BYPASS = """
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


COMPTA_ECRITURE_FUNCTION_STRICT = """
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


COMPTA_LIGNE_FUNCTION_STRICT = """
CREATE OR REPLACE FUNCTION compta_ligne_immutable() RETURNS trigger AS $$
DECLARE
    v_statut text;
    v_ecriture uuid;
BEGIN
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
    op.execute(COMPTA_ECRITURE_FUNCTION_WITH_ADMIN_BYPASS)
    op.execute(COMPTA_LIGNE_FUNCTION_WITH_ADMIN_BYPASS)


def downgrade() -> None:
    op.execute(COMPTA_ECRITURE_FUNCTION_STRICT)
    op.execute(COMPTA_LIGNE_FUNCTION_STRICT)
