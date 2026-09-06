"""Le verrou des lignes commence à la première validation, pas à la seconde

Revision ID: 20260911_lignes_verrou_val1
Revises: 20260910_od_cdf_usd

Le déclencheur ne refusait les lignes qu'à partir de APPROUVEE. Or une pièce
validée une fois est AUTORISEE : elle attend le visa, elle est déjà sortie des
mains du rédacteur, et le validateur qui appose son visa lit un texte censé ne
plus bouger. La couche applicative le refusait déjà (FINAL_REQUISITION_STATUSES
contient AUTORISEE) ; le déclencheur, dernier rempart, restait en retrait —
n'importe quelle écriture hors API passait entre les deux.

Le bypass administratif (`onec.admin_reset`) reste intact : le reset outillé
d'une réquisition continue de fonctionner.
"""

from __future__ import annotations

from alembic import op


revision = "20260911_lignes_verrou_val1"
down_revision = "20260910_od_cdf_usd"
branch_labels = None
depends_on = None


_STATUTS_VERROUILLES = "('AUTORISEE', 'APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT')"
_STATUTS_PRECEDENTS = "('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT')"


def _fonction(statuts: str) -> str:
    return f"""
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
    IF req_status IN {statuts} THEN
        RAISE EXCEPTION 'Réquisition validée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


LINE_TRIGGER_FUNCTION_VERROU_VALIDATION_1 = _fonction(_STATUTS_VERROUILLES)


def upgrade() -> None:
    op.execute(LINE_TRIGGER_FUNCTION_VERROU_VALIDATION_1)


def downgrade() -> None:
    op.execute(_fonction(_STATUTS_PRECEDENTS))
