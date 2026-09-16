"""Les verrous du Tableau laissent passer l'administrateur, comme les autres

Revision ID: 20260916_verrous_tableau
Revises: 20260916_source_feuille

`tableau_guard_reference_snapshot` et `tableau_guard_actualisation` gèlent un
snapshot dès qu'il est scellé, une actualisation dès qu'elle est complétée. La
règle est juste : un référentiel figé sur lequel une commission a délibéré ne
doit pas bouger dans le dos de qui l'a lu.

Mais elles ne prévoyaient aucune sortie. Un snapshot scellé par erreur — le
mauvais périmètre, une capture lancée deux fois — restait définitivement
intouchable : UPDATE refusé, DELETE refusé, et pour seul recours un
administrateur de base désactivant le déclencheur en production. Le produit a
déjà éprouvé ce mur ailleurs : `prevent_ligne_requisition_change_after_final`
interdisait, elle aussi, l'opération même qui devait la lever.

Ces deux gardes honorent désormais `onec.admin_reset`, le drapeau administratif
déjà utilisé par `reset_financial_operations.py` et par le verrou des lignes de
réquisition. On ne crée pas une seconde convention : un seul drapeau, connu,
posé par `SET LOCAL` dans la transaction qui l'assume, et qui ne survit pas à
celle-ci. Les tables du Tableau deviennent du même coup purgeables par l'outil
de remise à zéro, qui échouait silencieusement sur elles.

Ce que cela ne change pas : sans ce drapeau, rien ne bouge. L'immuabilité reste
la règle, et la lever reste un acte délibéré.

Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op


revision = "20260916_verrous_tableau"
down_revision = "20260916_source_feuille"
branch_labels = None
depends_on = None


def _garde_snapshot(*, avec_echappatoire: bool) -> str:
    sortie = (
        """
            IF current_setting('onec.admin_reset', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
            END IF;
"""
        if avec_echappatoire
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION tableau_guard_reference_snapshot() RETURNS trigger AS $$
DECLARE target_snapshot_id integer;
BEGIN
{sortie}
    IF TG_TABLE_NAME = 'tableau_reference_snapshots' THEN
        IF OLD.sealed_at IS NOT NULL THEN
            RAISE EXCEPTION 'A sealed Tableau reference snapshot is immutable';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;
    target_snapshot_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.snapshot_id ELSE NEW.snapshot_id END;
    IF EXISTS (
        SELECT 1 FROM tableau_reference_snapshots
        WHERE id = target_snapshot_id AND sealed_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Members of a sealed Tableau reference snapshot are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql
"""


def _garde_actualisation(*, avec_echappatoire: bool) -> str:
    sortie = (
        """
            IF current_setting('onec.admin_reset', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
            END IF;
"""
        if avec_echappatoire
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION tableau_guard_actualisation() RETURNS trigger AS $$
DECLARE parent_status text;
        target_actualisation_id integer;
BEGIN
{sortie}
    IF TG_TABLE_NAME = 'tableau_actualisations' THEN
        IF OLD.status = 'completed' THEN
            RAISE EXCEPTION 'A completed Tableau actualisation is immutable';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;
    target_actualisation_id := CASE
        WHEN TG_OP = 'DELETE' THEN OLD.actualisation_id ELSE NEW.actualisation_id
    END;
    SELECT status INTO parent_status FROM tableau_actualisations
    WHERE id = target_actualisation_id;
    IF parent_status = 'completed' THEN
        RAISE EXCEPTION 'Rows of a completed Tableau actualisation are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute(_garde_snapshot(avec_echappatoire=True))
    op.execute(_garde_actualisation(avec_echappatoire=True))


def downgrade() -> None:
    op.execute(_garde_snapshot(avec_echappatoire=False))
    op.execute(_garde_actualisation(avec_echappatoire=False))
