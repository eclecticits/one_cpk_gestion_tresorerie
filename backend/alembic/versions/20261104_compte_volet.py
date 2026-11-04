"""Changer le compte bancaire d'un volet de réquisition, même en décaissement

Revision ID: 20261104_compte_volet
Revises: 20261031_tableau_assurance_cp

Le changement de canal (20261008_changement_canal) bascule toute la pièce sur
un seul canal et s'arrête dès qu'un paiement est engagé. Une réquisition mixte
paie pourtant ses volets l'un après l'autre : la caisse a pu régler sa part
alors que le virement n'est pas parti, et c'est à ce moment qu'on apprend que
le loyer doit sortir d'un autre compte. Rejeter la pièce pour si peu défaisait
des paiements déjà faits.

Un second drapeau de session, `onec.changement_compte_volet`, ouvre une porte
plus étroite encore : seul `compte_bancaire_id` bouge (plus, côté réquisition,
les champs techniques `updated_at` et `bank_account_snapshot`) ; le mode reste
le même. Il vaut en décaissement, jamais sur une pièce payée. La règle « ce
volet n'a encore rien décaissé » est tenue par le service, qui refuse dès
qu'un ordre ou une sortie de fonds existe sur le compte quitté.
"""

from __future__ import annotations

from importlib import util as _util
from pathlib import Path as _Path

from alembic import op


revision = "20261104_compte_volet"
down_revision = "20261031_tableau_assurance_cp"
branch_labels = None
depends_on = None


def _canal():
    chemin = _Path(__file__).resolve().parent / "20261008_changement_canal.py"
    spec = _util.spec_from_file_location(chemin.stem, chemin)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_COLONNE_COMPTE = ("compte_bancaire_id",)


def _clause_compte(colonnes: tuple[str, ...], statut: str) -> str:
    canal = _canal()
    return f"""
    -- Changement du compte d'un volet : seul le compte bouge, jamais une pièce payée.
    IF TG_OP = 'UPDATE'
       AND current_setting('onec.changement_compte_volet', true) = 'on'
       AND COALESCE({statut}, '') <> 'PAYEE'
       AND {canal._sans(colonnes, 'NEW')} = {canal._sans(colonnes, 'OLD')}
    THEN
        RETURN NEW;
    END IF;
"""


def fonction_lignes() -> str:
    canal = _canal()
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
{canal._clause_reimputation()}
    req_id := COALESCE(NEW.requisition_id, OLD.requisition_id);
    SELECT status INTO req_status FROM requisitions WHERE id = req_id;
{canal._clause_canal(canal._COLONNES_CANAL, "req_status")}
{_clause_compte(_COLONNE_COMPTE, "req_status")}
    IF req_status IN {canal._STATUTS_LIGNES_VERROUILLES} THEN
        RAISE EXCEPTION 'Réquisition validée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def fonction_requisitions() -> str:
    canal = _canal()
    differences = " OR\n                ".join(
        f"OLD.{col} IS DISTINCT FROM NEW.{col}" for col in canal._COLONNES_SENSIBLES_REQ
    )
    return f"""
CREATE OR REPLACE FUNCTION prevent_requisition_sensitive_update_after_final()
RETURNS trigger AS $$
BEGIN
{canal._clause_canal(canal._COLONNES_CANAL + canal._COLONNES_TECHNIQUES_REQ, "OLD.status")}
{_clause_compte(_COLONNE_COMPTE + canal._COLONNES_TECHNIQUES_REQ, "OLD.status")}
    IF OLD.status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') AND (
                {differences}
    ) THEN
        RAISE EXCEPTION 'Réquisition finalisée: modification historique sensible interdite';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(fonction_lignes())
    op.execute(fonction_requisitions())


def downgrade() -> None:
    canal = _canal()
    op.execute(canal.fonction_lignes(avec_canal=True))
    op.execute(canal.fonction_requisitions(avec_canal=True))
