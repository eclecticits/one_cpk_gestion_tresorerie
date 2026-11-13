"""Changer le canal d'une réquisition à décaissement progressif déjà entamée

Revision ID: 20261113_canal_progressif
Revises: 20261111b_compta_creances

Le changement de canal (20261008_changement_canal) s'arrête dès que la pièce
est en décaissement : son canal est alors celui par lequel l'argent est sorti.
Cela ne tient pas pour une réquisition à décaissement progressif. Elle se paie
tranche par tranche, chaque tranche est un ordre de décaissement qui porte son
propre canal, et il arrive qu'après les premières tranches en espèces le reste
doive partir par la banque. Sans cette porte, le reste était condamné au canal
du départ.

Le drapeau `onec.changement_canal` vaut donc aussi en décaissement, mais pour
ces seules pièces : les déclencheurs lisent `decaissement_progressif` sur la
réquisition elle-même, pas un second drapeau qu'on pourrait poser à tort. Une
pièce payée reste fermée, et toujours rien d'autre que le mode et le compte ne
bouge. La règle « aucune tranche en attente de paiement » est tenue par le
service.
"""

from __future__ import annotations

from importlib import util as _util
from pathlib import Path as _Path

from alembic import op


revision = "20261113_canal_progressif"
down_revision = "20261111b_compta_creances"
branch_labels = None
depends_on = None


def _module(nom: str):
    chemin = _Path(__file__).resolve().parent / f"{nom}.py"
    spec = _util.spec_from_file_location(chemin.stem, chemin)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clause_canal(colonnes: tuple[str, ...], statut: str, progressif: str) -> str:
    canal = _module("20261008_changement_canal")
    return f"""
    -- Changement de canal : seuls le mode et le compte bougent. Avant paiement
    -- pour toute pièce ; en décaissement pour une pièce à décaissement
    -- progressif, dont les tranches payées gardent le canal de leur ordre.
    IF TG_OP = 'UPDATE'
       AND current_setting('onec.changement_canal', true) = 'on'
       AND (
            COALESCE({statut}, '') NOT IN {canal._STATUTS_PAYES}
            OR (COALESCE({statut}, '') = 'EN_DECAISSEMENT' AND COALESCE({progressif}, false))
       )
       AND {canal._sans(colonnes, 'NEW')} = {canal._sans(colonnes, 'OLD')}
    THEN
        RETURN NEW;
    END IF;
"""


def fonction_lignes() -> str:
    canal = _module("20261008_changement_canal")
    volet = _module("20261104_compte_volet")
    return f"""
CREATE OR REPLACE FUNCTION prevent_ligne_requisition_change_after_final()
RETURNS trigger AS $$
DECLARE
    req_status text;
    req_progressif boolean;
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
    SELECT status, decaissement_progressif INTO req_status, req_progressif
    FROM requisitions WHERE id = req_id;
{_clause_canal(canal._COLONNES_CANAL, "req_status", "req_progressif")}
{volet._clause_compte(volet._COLONNE_COMPTE, "req_status")}
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
    canal = _module("20261008_changement_canal")
    volet = _module("20261104_compte_volet")
    differences = " OR\n                ".join(
        f"OLD.{col} IS DISTINCT FROM NEW.{col}" for col in canal._COLONNES_SENSIBLES_REQ
    )
    colonnes = canal._COLONNES_CANAL + canal._COLONNES_TECHNIQUES_REQ
    return f"""
CREATE OR REPLACE FUNCTION prevent_requisition_sensitive_update_after_final()
RETURNS trigger AS $$
BEGIN
{_clause_canal(colonnes, "OLD.status", "OLD.decaissement_progressif")}
{volet._clause_compte(volet._COLONNE_COMPTE + canal._COLONNES_TECHNIQUES_REQ, "OLD.status")}
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
    volet = _module("20261104_compte_volet")
    op.execute(volet.fonction_lignes())
    op.execute(volet.fonction_requisitions())
