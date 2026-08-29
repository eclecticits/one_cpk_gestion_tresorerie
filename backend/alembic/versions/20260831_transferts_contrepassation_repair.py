"""Convergence des environnements estampillés sur une version antérieure de
`20260830_transferts_additive`.

Cette révision existe pour une raison précise et désagréable : la révision
`20260830_transferts_additive` a été **réécrite après avoir été appliquée**.
Une première version modélisait la correction d'un transfert comme une
annulation (`annule_le`, `annule_par`) ; la version retenue la modélise comme
une contre-passation additive (`contrepasse_le`, `contrepasse_par`,
`motif_contrepassation`, plus les garanties qui vont avec).

Un environnement ayant joué la première version porte l'estampille de la
révision **et** l'ancien schéma. Alembic ne rejouera jamais une révision déjà
estampillée : `upgrade head` y est un no-op définitif, et le modèle SQLAlchemy
y référence des colonnes qui n'existent pas — toute lecture de transfert
répond 500. C'est le cas de la base de développement au 29/08/2026.

D'où une révision de convergence, en avant, idempotente : elle amène à l'état
attendu aussi bien une base issue de la première version que d'une base neuve
déjà correcte, où elle ne fait alors rien.

Les colonnes `annule_*` ne sont retirées que si elles ne portent **aucune**
valeur. Une annulation enregistrée sous l'ancien modèle est une information
comptable : la perdre en silence serait pire que l'incohérence de schéma. Dans
ce cas, la migration s'arrête et le dit.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260831_transferts_repair"
down_revision = "20260830_transferts_additive"
branch_labels = None
depends_on = None

TABLE = "transferts_internes"


def _colonnes(inspector: sa.Inspector) -> set[str]:
    return {col["name"] for col in inspector.get_columns(TABLE)}


def _contraintes(inspector: sa.Inspector) -> set[str]:
    noms = set()
    for groupe in (
        inspector.get_unique_constraints(TABLE),
        inspector.get_check_constraints(TABLE),
        inspector.get_foreign_keys(TABLE),
    ):
        noms.update(item.get("name") for item in groupe if item.get("name"))
    return noms


def _index(inspector: sa.Inspector) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    colonnes = _colonnes(inspector)
    #: État de départ, figé avant toute modification : c'est lui qui dit si la
    #: base vient de l'ancien modèle et s'il y a donc des annulations à
    #: reprendre. Le relire après coup ne distinguerait plus les deux cas.
    venait_de_l_ancien_modele = "annule_le" in colonnes
    contrepassation_a_creer = "contrepasse_le" not in colonnes

    for nom, colonne in (
        ("contrepasse_le", sa.Column("contrepasse_le", sa.DateTime(timezone=True), nullable=True)),
        ("contrepasse_par", sa.Column("contrepasse_par", sa.UUID(), nullable=True)),
        ("motif_contrepassation", sa.Column("motif_contrepassation", sa.String(500), nullable=True)),
    ):
        if nom not in colonnes:
            op.add_column(TABLE, colonne)

    # Reprise des annulations de l'ancien modèle, s'il y en a : une ligne
    # annulée devient une ligne contre-passée, sans motif (l'ancien modèle n'en
    # demandait pas). Le faire AVANT de poser la contrainte d'exhaustivité, qui
    # exigerait justement ce motif.
    if venait_de_l_ancien_modele and contrepassation_a_creer:
        op.execute(
            f"UPDATE {TABLE} SET contrepasse_le = annule_le, contrepasse_par = annule_par, "
            "motif_contrepassation = 'Annulation reprise de l''ancien modèle' "
            "WHERE annule_le IS NOT NULL"
        )

    inspector = sa.inspect(bind)
    contraintes = _contraintes(inspector)
    if "ck_transferts_internes_statut" not in contraintes:
        op.create_check_constraint(
            "ck_transferts_internes_statut", TABLE, "statut IN ('EXECUTE', 'CONTREPASSE')"
        )
    if "ck_transferts_internes_contrepassation_terminale" not in contraintes:
        # Une contre-passation ne se contre-passe pas : corriger une correction
        # est un nouveau transfert, pas une chaîne d'annulations.
        op.create_check_constraint(
            "ck_transferts_internes_contrepassation_terminale",
            TABLE,
            "transfert_origine_id IS NULL OR statut = 'EXECUTE'",
        )
    if "ck_transferts_internes_contrepassation_complete" not in contraintes:
        # Un transfert contre-passé porte toujours qui, quand et pourquoi.
        op.create_check_constraint(
            "ck_transferts_internes_contrepassation_complete",
            TABLE,
            "statut <> 'CONTREPASSE' OR ("
            "contrepasse_le IS NOT NULL AND contrepasse_par IS NOT NULL "
            "AND motif_contrepassation IS NOT NULL)",
        )

    inspector = sa.inspect(bind)
    index = _index(inspector)
    if "uq_transferts_internes_origine" not in index:
        # Au plus une contre-passation par transfert, garanti par la base : le
        # double-clic reste sans effet même si le verrou applicatif lâche.
        op.create_index(
            "uq_transferts_internes_origine", TABLE, ["transfert_origine_id"], unique=True,
            postgresql_where=sa.text("transfert_origine_id IS NOT NULL"),
        )
    if "ix_transferts_internes_org_reference" not in index:
        op.create_index("ix_transferts_internes_org_reference", TABLE, ["organisation_id", "reference"])

    # Enfin, les colonnes de l'ancien modèle — et seulement si elles sont vides.
    inspector = sa.inspect(bind)
    colonnes = _colonnes(inspector)
    if "annule_le" in colonnes or "annule_par" in colonnes:
        restants = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE annule_le IS NOT NULL OR annule_par IS NOT NULL")
        ).scalar_one()
        if restants:
            raise RuntimeError(
                f"{restants} transfert(s) portent encore une annulation de l'ancien modèle "
                "après reprise : vérifier la reprise avant de retirer annule_le/annule_par."
            )
        for nom in ("annule_le", "annule_par"):
            if nom in colonnes:
                op.drop_column(TABLE, nom)


def downgrade() -> None:
    """Retour à l'état attendu de `20260830_transferts_additive`.

    Les colonnes `annule_*` ne sont pas recréées : elles n'appartiennent à
    aucune version publiée de cette révision, seulement à un état transitoire
    que cette migration a précisément pour objet de faire disparaître.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for nom in ("ix_transferts_internes_org_reference", "uq_transferts_internes_origine"):
        if nom in _index(inspector):
            op.drop_index(nom, table_name=TABLE)

    inspector = sa.inspect(bind)
    contraintes = _contraintes(inspector)
    for nom in (
        "ck_transferts_internes_contrepassation_complete",
        "ck_transferts_internes_contrepassation_terminale",
        "ck_transferts_internes_statut",
    ):
        if nom in contraintes:
            op.drop_constraint(nom, TABLE, type_="check")

    inspector = sa.inspect(bind)
    colonnes = _colonnes(inspector)
    for nom in ("motif_contrepassation", "contrepasse_par", "contrepasse_le"):
        if nom in colonnes:
            op.drop_column(TABLE, nom)
