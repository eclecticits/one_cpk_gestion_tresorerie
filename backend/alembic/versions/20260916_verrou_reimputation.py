"""Le verrou des lignes laisse passer une correction d'imputation, et rien d'autre

Revision ID: 20260916_verrou_reimput
Revises: 20260916_tableau_actual

`prevent_ligne_requisition_change_after_final` gèle les lignes d'une réquisition
dès la première validation : le validateur qui appose son visa lit un texte censé
ne plus bouger. La règle est juste et on n'y touche pas.

Mais elle interdisait aussi la ré-imputation, dont c'est précisément l'objet :
corriger le poste d'une réquisition déjà autorisée, approuvée ou payée. La
fonctionnalité ne pouvait donc s'exercer que sur un brouillon — le seul état où
elle ne sert à rien. Toute correction sur une pièce réelle repartait en 500.

Le déclencheur reconnaît désormais un second drapeau de session,
`onec.reimputation`, et ne l'honore que pour un UPDATE qui ne déplace que
l'imputation. Le texte signé reste figé : libellé, description, quantité,
montants et devise doivent être identiques, et la ligne ne peut pas changer de
réquisition. Un seul champ de trop, et le refus retombe.

Le drapeau est posé par `SET LOCAL` dans la transaction du service de
ré-imputation : il ne survit pas à la transaction et n'existe pour aucune autre
écriture. Le bypass administratif (`onec.admin_reset`) reste intact.
"""

from __future__ import annotations

from alembic import op


revision = "20260916_verrou_reimput"
down_revision = "20260916_tableau_actual"
branch_labels = None
depends_on = None


_STATUTS_VERROUILLES = "('AUTORISEE', 'APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT')"

# Les colonnes que la ré-imputation a le droit de bouger. Tout le reste doit
# rester identique — c'est ce qui distingue une correction d'imputation d'une
# réécriture de la pièce.
_COLONNES_FIGEES = (
    "requisition_id",
    "rubrique",
    "description",
    "quantite",
    "montant_unitaire",
    "montant_total",
    "devise",
)


def fonction(*, avec_reimputation: bool) -> str:
    """Le SQL du déclencheur, pour qu'il puisse être éprouvé plutôt que recopié."""
    clause_reimputation = ""
    if avec_reimputation:
        egalites = "\n".join(
            f"           AND NEW.{col} IS NOT DISTINCT FROM OLD.{col}" for col in _COLONNES_FIGEES
        )
        clause_reimputation = f"""
    -- Correction d'imputation : seul le poste bouge. Le texte que le validateur
    -- a signé ne change pas d'un caractère, et la ligne reste sur sa réquisition.
    IF TG_OP = 'UPDATE'
       AND current_setting('onec.reimputation', true) = 'on'
{egalites}
    THEN
        RETURN NEW;
    END IF;
"""

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
{clause_reimputation}
    req_id := COALESCE(NEW.requisition_id, OLD.requisition_id);
    SELECT status INTO req_status FROM requisitions WHERE id = req_id;
    IF req_status IN {_STATUTS_VERROUILLES} THEN
        RAISE EXCEPTION 'Réquisition validée: modification des lignes interdite';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def declencheur() -> str:
    """Le rattachement du déclencheur à la table.

    La migration ne s'en sert pas — le déclencheur existe depuis longtemps et
    seule sa fonction est redéfinie ici. Il est exposé pour les tests : le
    schéma de test naît de `Base.metadata.create_all()`, qui crée les tables
    mais aucun déclencheur. Sans ce SQL, aucun test ne peut voir le verrou.
    """
    return """
DROP TRIGGER IF EXISTS trg_lignes_requisition_immutable_after_final ON lignes_requisition;
CREATE TRIGGER trg_lignes_requisition_immutable_after_final
BEFORE INSERT OR UPDATE OR DELETE ON lignes_requisition
FOR EACH ROW EXECUTE FUNCTION prevent_ligne_requisition_change_after_final();
"""


def upgrade() -> None:
    op.execute(fonction(avec_reimputation=True))


def downgrade() -> None:
    op.execute(fonction(avec_reimputation=False))
