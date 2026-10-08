"""Changer le canal de paiement d'une réquisition validée et non payée

Revision ID: 20261008_changement_canal
Revises: 20261007_rt_brouillons

Une réquisition validée garde ses lignes et ses champs sensibles gelés par deux
déclencheurs : le validateur a signé un texte qui ne doit plus bouger. Le canal
(caisse ou banque, et le compte) n'est pourtant pas ce qu'il a signé sur le
fond : il arrive qu'on apprenne après la validation que la caisse n'a pas les
fonds, ou que le bénéficiaire veut un virement. Rejeter puis refaire toute la
pièce pour cela relançait tout le circuit.

Les deux déclencheurs reconnaissent donc un drapeau de session,
`onec.changement_canal`, posé par `SET LOCAL` dans la seule transaction du
service de changement de canal. Ils ne l'honorent que pour un UPDATE où rien
d'autre que `mode_paiement` et `compte_bancaire_id` (et, côté réquisition, les
champs techniques `updated_at` et `bank_account_snapshot`) ne change. Une
colonne de trop, et le refus retombe. La règle « non payée » est tenue par le
service, qui refuse dès qu'un paiement est engagé.

On compare les lignes entières via `to_jsonb` plutôt qu'en énumérant les
colonnes : une colonne ajoutée plus tard est ainsi gelée par défaut.

Le droit `treso.requisitions.changer_canal` est accordé au rôle `admin`, comme
celui de ré-imputer ; les autres rôles le reçoivent par attribution délibérée.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from importlib import util as _util
from pathlib import Path as _Path


revision = "20261008_changement_canal"
down_revision = "20261007_rt_brouillons"
branch_labels = None
depends_on = None


CODE = "treso.requisitions.changer_canal"
DESCRIPTION = "Trésorerie — Réquisitions : changer le canal de paiement d'une réquisition validée non payée"

_STATUTS_LIGNES_VERROUILLES = "('AUTORISEE', 'APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT')"

_COLONNES_CANAL = ("mode_paiement", "compte_bancaire_id")
_COLONNES_TECHNIQUES_REQ = ("updated_at", "bank_account_snapshot")


def _sans(colonnes: tuple[str, ...], ligne: str) -> str:
    return f"(to_jsonb({ligne})" + "".join(f" - '{c}'" for c in colonnes) + ")"


_STATUTS_PAYES = "('PAYEE', 'EN_DECAISSEMENT')"


def _clause_canal(colonnes: tuple[str, ...], statut: str) -> str:
    # Une pièce payée ou en cours de paiement garde son canal : le drapeau n'y
    # peut rien, même posé par erreur.
    return f"""
    -- Changement de canal : seuls le mode et le compte bougent, avant paiement.
    IF TG_OP = 'UPDATE'
       AND current_setting('onec.changement_canal', true) = 'on'
       AND COALESCE({statut}, '') NOT IN {_STATUTS_PAYES}
       AND {_sans(colonnes, 'NEW')} = {_sans(colonnes, 'OLD')}
    THEN
        RETURN NEW;
    END IF;
"""


def _clause_reimputation() -> str:
    """Reprise à l'identique de la clause posée par 20260916_verrou_reimput."""
    chemin = _Path(__file__).resolve().parent / "20260916_verrou_reimputation.py"
    spec = _util.spec_from_file_location(chemin.stem, chemin)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    egalites = "\n".join(
        f"           AND NEW.{col} IS NOT DISTINCT FROM OLD.{col}" for col in module._COLONNES_FIGEES
    )
    return f"""
    IF TG_OP = 'UPDATE'
       AND current_setting('onec.reimputation', true) = 'on'
{egalites}
    THEN
        RETURN NEW;
    END IF;
"""


def fonction_lignes(*, avec_canal: bool) -> str:
    clause_canal = _clause_canal(_COLONNES_CANAL, "req_status") if avec_canal else ""
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
{_clause_reimputation()}
    req_id := COALESCE(NEW.requisition_id, OLD.requisition_id);
    SELECT status INTO req_status FROM requisitions WHERE id = req_id;
{clause_canal}
    IF req_status IN {_STATUTS_LIGNES_VERROUILLES} THEN
        RAISE EXCEPTION 'Réquisition validée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


_COLONNES_SENSIBLES_REQ = (
    "numero_requisition",
    "reference_numero",
    "objet",
    "mode_paiement",
    "type_requisition",
    "montant_total",
    "devise",
    "service_id",
    "compte_bancaire_id",
    "created_by",
    "validee_par",
    "validee_le",
    "approuvee_par",
    "approuvee_le",
    "signed_by_id",
    "signed_at",
    "req_titre_officiel_hist",
    "req_label_gauche_hist",
    "req_nom_gauche_hist",
    "req_label_droite_hist",
    "req_nom_droite_hist",
    "signataire_g_label",
    "signataire_g_nom",
    "signataire_d_label",
    "signataire_d_nom",
    "exchange_rate_snapshot",
    "exchange_rate_source",
    "exchange_rate_date",
    "base_amount_snapshot",
    "converted_amount_snapshot",
)


def fonction_requisitions(*, avec_canal: bool) -> str:
    clause_canal = (
        _clause_canal(_COLONNES_CANAL + _COLONNES_TECHNIQUES_REQ, "OLD.status") if avec_canal else ""
    )
    differences = " OR\n                ".join(
        f"OLD.{col} IS DISTINCT FROM NEW.{col}" for col in _COLONNES_SENSIBLES_REQ
    )
    return f"""
CREATE OR REPLACE FUNCTION prevent_requisition_sensitive_update_after_final()
RETURNS trigger AS $$
BEGIN
{clause_canal}
    IF OLD.status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') AND (
                {differences}
    ) THEN
        RAISE EXCEPTION 'Réquisition finalisée: modification historique sensible interdite';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def declencheurs() -> list[str]:
    """Rattachements des déclencheurs, pour les tests (create_all n'en crée aucun)."""
    return [
        "DROP TRIGGER IF EXISTS trg_lignes_requisition_immutable_after_final ON lignes_requisition",
        """CREATE TRIGGER trg_lignes_requisition_immutable_after_final
BEFORE INSERT OR UPDATE OR DELETE ON lignes_requisition
FOR EACH ROW EXECUTE FUNCTION prevent_ligne_requisition_change_after_final()""",
        "DROP TRIGGER IF EXISTS trg_requisitions_immutable_after_final ON requisitions",
        """CREATE TRIGGER trg_requisitions_immutable_after_final
BEFORE UPDATE ON requisitions
FOR EACH ROW EXECUTE FUNCTION prevent_requisition_sensitive_update_after_final()""",
    ]


SEMER = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.execute(fonction_lignes(avec_canal=True))
    op.execute(fonction_requisitions(avec_canal=True))
    bind = op.get_bind()
    bind.execute(text(SEMER), {"code": CODE, "description": DESCRIPTION})
    bind.execute(text(ACCORDER), {"role": "admin", "code": CODE})


def downgrade() -> None:
    op.execute(fonction_lignes(avec_canal=False))
    op.execute(fonction_requisitions(avec_canal=False))
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": CODE},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": CODE})
