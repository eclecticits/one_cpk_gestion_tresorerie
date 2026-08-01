"""Bypass administratif transactionnel pour reset des lignes de requisition

Revision ID: 20260801_req_reset_bypass
Revises: 20260801_compta_etats
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op


revision = "20260801_req_reset_bypass"
down_revision = "20260801_compta_etats"
branch_labels = None
depends_on = None


LINE_TRIGGER_FUNCTION_WITH_ADMIN_BYPASS = """
CREATE OR REPLACE FUNCTION prevent_ligne_requisition_change_after_final()
RETURNS trigger AS $$
DECLARE
    req_status text;
    req_id uuid;
BEGIN
    IF current_setting('onec.admin_reset', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    req_id := COALESCE(NEW.requisition_id, OLD.requisition_id);
    SELECT status INTO req_status FROM requisitions WHERE id = req_id;
    IF req_status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') THEN
        RAISE EXCEPTION 'Réquisition finalisée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


LINE_TRIGGER_FUNCTION_STRICT = """
CREATE OR REPLACE FUNCTION prevent_ligne_requisition_change_after_final()
RETURNS trigger AS $$
DECLARE
    req_status text;
    req_id uuid;
BEGIN
    req_id := COALESCE(NEW.requisition_id, OLD.requisition_id);
    SELECT status INTO req_status FROM requisitions WHERE id = req_id;
    IF req_status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') THEN
        RAISE EXCEPTION 'Réquisition finalisée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(LINE_TRIGGER_FUNCTION_WITH_ADMIN_BYPASS)


def downgrade() -> None:
    op.execute(LINE_TRIGGER_FUNCTION_STRICT)
