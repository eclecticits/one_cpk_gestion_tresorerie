"""Additive internal transfers: dedicated statuses, reversal link, guarantees.

No historical transfer is copied or replayed here.  Existing rows stay in
their table; this revision only makes the dedicated table ready for new writes.

Reversal is **additive**: cancelling a transfer never rewrites the original
row's legs, it inserts an opposite transfer dated the day of the correction and
linked through ``transfert_origine_id``.  The original keeps its amount, its
date and its accounting entry, and stays visible in every report.  Its
``statut`` moves to ``CONTREPASSE`` for display only — see the invariant
documented on the model.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_transferts_additive"
down_revision = "20260829_sorties_idempotency"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_constraint(inspector: sa.Inspector, table: str, name: str) -> bool:
    constraints = inspector.get_unique_constraints(table)
    constraints += inspector.get_check_constraints(table)
    constraints += inspector.get_foreign_keys(table)
    return any(item.get("name") == name for item in constraints)


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(index["name"] == name for index in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        "organisation_id": sa.Column("organisation_id", sa.Integer(), nullable=True),
        "statut": sa.Column("statut", sa.String(20), nullable=False, server_default="EXECUTE"),
        "idempotency_key": sa.Column("idempotency_key", sa.String(128), nullable=True),
        "idempotency_payload_hash": sa.Column("idempotency_payload_hash", sa.String(64), nullable=True),
        "contrepasse_le": sa.Column("contrepasse_le", sa.DateTime(timezone=True), nullable=True),
        "contrepasse_par": sa.Column("contrepasse_par", sa.UUID(), nullable=True),
        "motif_contrepassation": sa.Column("motif_contrepassation", sa.String(500), nullable=True),
        "transfert_origine_id": sa.Column("transfert_origine_id", sa.Integer(), nullable=True),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    }
    for name, column in columns.items():
        if not _has_column(inspector, "transferts_internes", name):
            op.add_column("transferts_internes", column)

    inspector = sa.inspect(bind)
    if not _has_constraint(inspector, "transferts_internes", "fk_transferts_internes_organisation_id"):
        op.create_foreign_key(
            "fk_transferts_internes_organisation_id",
            "transferts_internes",
            "organisations",
            ["organisation_id"], ["id"], ondelete="RESTRICT",
        )
    if not _has_constraint(inspector, "transferts_internes", "fk_transferts_internes_origine"):
        op.create_foreign_key(
            "fk_transferts_internes_origine",
            "transferts_internes",
            "transferts_internes",
            ["transfert_origine_id"], ["id"], ondelete="RESTRICT",
        )
    if not _has_constraint(inspector, "transferts_internes", "ck_transferts_internes_montant_positif"):
        # Une contre-passation est un transfert de montant positif dont la source
        # et la destination sont permutées : aucun montant négatif ne circule.
        op.create_check_constraint(
            "ck_transferts_internes_montant_positif", "transferts_internes", "montant > 0"
        )
    if not _has_constraint(inspector, "transferts_internes", "ck_transferts_internes_sources_distinctes"):
        op.create_check_constraint(
            "ck_transferts_internes_sources_distinctes",
            "transferts_internes",
            "NOT (source_type = destination_type AND COALESCE(source_id, 0) = COALESCE(destination_id, 0))",
        )
    if not _has_constraint(inspector, "transferts_internes", "ck_transferts_internes_statut"):
        op.create_check_constraint(
            "ck_transferts_internes_statut",
            "transferts_internes",
            "statut IN ('EXECUTE', 'CONTREPASSE')",
        )
    if not _has_constraint(inspector, "transferts_internes", "ck_transferts_internes_contrepassation_terminale"):
        # Une contre-passation ne se contre-passe pas : corriger une correction
        # est un nouveau transfert, pas une chaîne d'annulations.
        op.create_check_constraint(
            "ck_transferts_internes_contrepassation_terminale",
            "transferts_internes",
            "transfert_origine_id IS NULL OR statut = 'EXECUTE'",
        )
    if not _has_constraint(inspector, "transferts_internes", "ck_transferts_internes_contrepassation_complete"):
        # Un transfert contre-passé porte toujours qui, quand et pourquoi.
        op.create_check_constraint(
            "ck_transferts_internes_contrepassation_complete",
            "transferts_internes",
            "statut <> 'CONTREPASSE' OR ("
            "contrepasse_le IS NOT NULL AND contrepasse_par IS NOT NULL "
            "AND motif_contrepassation IS NOT NULL)",
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "transferts_internes", "uq_transferts_internes_org_idempotency"):
        op.create_index(
            "uq_transferts_internes_org_idempotency",
            "transferts_internes", ["organisation_id", "idempotency_key"], unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )
    if not _has_index(inspector, "transferts_internes", "uq_transferts_internes_org_reference"):
        op.create_index(
            "uq_transferts_internes_org_reference",
            "transferts_internes", ["organisation_id", "reference"], unique=True,
            postgresql_where=sa.text("reference IS NOT NULL"),
        )
    if not _has_index(inspector, "transferts_internes", "uq_transferts_internes_origine"):
        # Au plus une contre-passation par transfert, garanti par la base : le
        # double-clic reste sans effet même si le verrou applicatif lâche.
        op.create_index(
            "uq_transferts_internes_origine",
            "transferts_internes", ["transfert_origine_id"], unique=True,
            postgresql_where=sa.text("transfert_origine_id IS NOT NULL"),
        )
    if not _has_index(inspector, "transferts_internes", "ix_transferts_internes_org_date"):
        op.create_index("ix_transferts_internes_org_date", "transferts_internes", ["organisation_id", "date_transfert"])
    if not _has_index(inspector, "transferts_internes", "ix_transferts_internes_org_statut"):
        op.create_index("ix_transferts_internes_org_statut", "transferts_internes", ["organisation_id", "statut"])
    if not _has_index(inspector, "transferts_internes", "ix_transferts_internes_org_reference"):
        op.create_index("ix_transferts_internes_org_reference", "transferts_internes", ["organisation_id", "reference"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index in (
        "ix_transferts_internes_org_statut",
        "ix_transferts_internes_org_date",
        "ix_transferts_internes_org_reference",
        "uq_transferts_internes_origine",
        "uq_transferts_internes_org_reference",
        "uq_transferts_internes_org_idempotency",
    ):
        if _has_index(inspector, "transferts_internes", index):
            op.drop_index(index, table_name="transferts_internes")
    inspector = sa.inspect(bind)
    for constraint, type_ in (
        ("ck_transferts_internes_contrepassation_complete", "check"),
        ("ck_transferts_internes_contrepassation_terminale", "check"),
        ("ck_transferts_internes_statut", "check"),
        ("ck_transferts_internes_sources_distinctes", "check"),
        ("ck_transferts_internes_montant_positif", "check"),
        ("fk_transferts_internes_origine", "foreignkey"),
    ):
        if _has_constraint(inspector, "transferts_internes", constraint):
            op.drop_constraint(constraint, "transferts_internes", type_=type_)
    for column in (
        "updated_at", "created_at", "transfert_origine_id", "motif_contrepassation",
        "contrepasse_par", "contrepasse_le", "idempotency_payload_hash",
        "idempotency_key", "statut",
        # Colonnes d'une version antérieure de cette révision, restées en base
        # sur les environnements déjà estampillés : le cycle downgrade/upgrade
        # doit reposer sur une table propre.
        "annule_par", "annule_le",
    ):
        inspector = sa.inspect(bind)
        if _has_column(inspector, "transferts_internes", column):
            op.drop_column("transferts_internes", column)
