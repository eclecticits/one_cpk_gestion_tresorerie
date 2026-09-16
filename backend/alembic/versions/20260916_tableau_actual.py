"""Snapshot officiel et actualisations immuables du Tableau préparatoire.

La migration crée uniquement les structures. Elle ne lit ni ne capture les
données de ``experts_comptables`` : le snapshot est une opération métier
explicite, réalisée ultérieurement par le service.

Revision ID: 20260916_tableau_actual
Revises: 20260916_imputation_ligne
Create Date: 2026-09-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260916_tableau_actual"
down_revision = "20260916_imputation_ligne"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tableau_member_identities", sa.Column("numero_ordre_normalise", sa.String(50), nullable=True))
    op.add_column("tableau_member_identities", sa.Column("expert_comptable_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "tableau_member_identities",
        sa.Column("reference_status", sa.String(30), nullable=False, server_default="UNRESOLVED"),
    )
    op.add_column("tableau_member_identities", sa.Column("reference_match_method", sa.String(30), nullable=True))
    op.add_column("tableau_member_identities", sa.Column("reference_match_metadata", postgresql.JSONB(), nullable=True))
    op.add_column(
        "tableau_member_identities",
        sa.Column("origin_type", sa.String(20), nullable=False, server_default="PP"),
    )
    op.execute(
        """
        UPDATE tableau_member_identities
        SET numero_ordre_normalise = upper(regexp_replace(btrim(numero_ordre), '[[:space:]]+', '', 'g')),
            origin_type = CASE WHEN person_kind = 'MORALE' THEN 'PM' ELSE 'PP' END
        """
    )
    op.alter_column(
        "tableau_member_identities",
        "numero_ordre_normalise",
        existing_type=sa.String(50),
        nullable=False,
    )
    op.alter_column(
        "tableau_member_identities",
        "first_seen_import_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "tableau_member_identities",
        "last_seen_import_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_tableau_identity_official_expert",
        "tableau_member_identities",
        "experts_comptables",
        ["expert_comptable_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_tableau_identity_reference_status",
        "tableau_member_identities",
        "reference_status IN ('MATCHED_OFFICIAL', 'ABSENT_DU_REFERENTIEL', 'AMBIGUOUS', 'UNRESOLVED')",
    )
    op.create_check_constraint(
        "ck_tableau_identity_origin_type",
        "tableau_member_identities",
        "origin_type IN ('OFFICIAL', 'PP', 'PM')",
    )
    op.create_index(
        "ix_tableau_member_identities_numero_ordre_normalise",
        "tableau_member_identities",
        ["numero_ordre_normalise"],
    )
    op.create_index(
        "ix_tableau_member_identities_expert_comptable_id",
        "tableau_member_identities",
        ["expert_comptable_id"],
    )
    op.create_index(
        "ix_tableau_member_identities_reference_status",
        "tableau_member_identities",
        ["reference_status"],
    )
    op.create_index(
        "ix_tableau_member_identities_origin_type",
        "tableau_member_identities",
        ["origin_type"],
    )
    op.create_index(
        "ix_tableau_member_identity_normalized_key",
        "tableau_member_identities",
        ["organisation_id", "numero_ordre_normalise"],
    )
    op.create_unique_constraint(
        "uq_tableau_identity_official_org",
        "tableau_member_identities",
        ["organisation_id", "expert_comptable_id"],
    )

    op.create_table(
        "tableau_reference_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_name", sa.String(50), nullable=False, server_default="experts_comptables"),
        sa.Column("scope_type", sa.String(30), nullable=False, server_default="NATIONAL"),
        sa.Column(
            "scope_organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("scope_definition_json", postgresql.JSONB(), nullable=True),
        sa.Column("registry_checksum", sa.String(64), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("scope_type IN ('NATIONAL', 'EXPLICIT')", name="ck_tableau_reference_scope_type"),
    )
    for column in ("captured_at", "sealed_at", "scope_type", "scope_organisation_id", "registry_checksum"):
        op.create_index(f"ix_tableau_reference_snapshots_{column}", "tableau_reference_snapshots", [column])

    op.create_table(
        "tableau_reference_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("tableau_reference_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Preuve historique volontairement sans FK : une suppression future du
        # registre ne doit jamais réécrire un ancien snapshot.
        sa.Column("official_expert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("numero_ordre_normalise", sa.String(50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("province_attache", sa.String(100), nullable=True),
        sa.Column("official_values", postgresql.JSONB(), nullable=False),
        sa.Column("row_checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_id", "official_expert_id", name="uq_tableau_reference_member_official"),
    )
    for column in ("snapshot_id", "official_expert_id", "numero_ordre_normalise", "province_attache"):
        op.create_index(f"ix_tableau_reference_members_{column}", "tableau_reference_members", [column])
    op.create_index(
        "ix_tableau_reference_member_key",
        "tableau_reference_members",
        ["snapshot_id", "numero_ordre_normalise"],
    )

    op.create_table(
        "tableau_actualisations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("actualized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "reference_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("tableau_reference_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ruleset_version", sa.String(80), nullable=False),
        sa.Column("ruleset_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "organisation_id", "date_situation", "revision_number", name="uq_tableau_actualisation_revision"
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_tableau_actualisation_revision_positive"),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name="ck_tableau_actualisation_status"),
    )
    for column in ("organisation_id", "date_situation", "actualized_at", "reference_snapshot_id", "status"):
        op.create_index(f"ix_tableau_actualisations_{column}", "tableau_actualisations", [column])

    op.create_table(
        "tableau_actualisation_inputs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "actualisation_id",
            sa.Integer(),
            sa.ForeignKey("tableau_actualisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actualisation_id", "import_id", name="uq_tableau_actualisation_input"),
    )
    op.create_index(
        "ix_tableau_actualisation_inputs_actualisation_id",
        "tableau_actualisation_inputs",
        ["actualisation_id"],
    )
    op.create_index("ix_tableau_actualisation_inputs_import_id", "tableau_actualisation_inputs", ["import_id"])

    op.create_table(
        "tableau_actualisation_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "actualisation_id",
            sa.Integer(),
            sa.ForeignKey("tableau_actualisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.Integer(),
            sa.ForeignKey("tableau_member_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Même choix historique que pour le snapshot : pas de FK sur cet UUID
        # matérialisé, afin qu'une ancienne révision reste autonome.
        sa.Column("official_expert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("reference_status", sa.String(30), nullable=False),
        sa.Column("proposal_status", sa.String(30), nullable=False),
        sa.Column("official_values", postgresql.JSONB(), nullable=False),
        sa.Column("proposed_values", postgresql.JSONB(), nullable=False),
        sa.Column("field_provenance", postgresql.JSONB(), nullable=False),
        sa.Column("differences_json", postgresql.JSONB(), nullable=False),
        sa.Column("anomalies_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actualisation_id", "identity_id", name="uq_tableau_actualisation_row_identity"),
        sa.CheckConstraint(
            "proposal_status IN ('OFFICIAL_ONLY', 'UNCHANGED', 'UPDATE_PROPOSED', 'CONFLICT', "
            "'NEW_IDENTITY', 'AMBIGUOUS_MATCH', 'BLOCKED')",
            name="ck_tableau_actualisation_proposal_status",
        ),
    )
    for column in (
        "actualisation_id",
        "identity_id",
        "official_expert_id",
        "numero_ordre",
        "reference_status",
        "proposal_status",
    ):
        op.create_index(f"ix_tableau_actualisation_rows_{column}", "tableau_actualisation_rows", [column])

    op.execute(
        """
        CREATE FUNCTION tableau_guard_reference_snapshot() RETURNS trigger AS $$
        DECLARE target_snapshot_id integer;
        BEGIN
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
    )
    op.execute(
        "CREATE TRIGGER trg_tableau_reference_snapshot_immutable "
        "BEFORE UPDATE OR DELETE ON tableau_reference_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION tableau_guard_reference_snapshot()"
    )
    op.execute(
        "CREATE TRIGGER trg_tableau_reference_member_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON tableau_reference_members "
        "FOR EACH ROW EXECUTE FUNCTION tableau_guard_reference_snapshot()"
    )

    op.execute(
        """
        CREATE FUNCTION tableau_guard_actualisation() RETURNS trigger AS $$
        DECLARE parent_status text;
                target_actualisation_id integer;
        BEGIN
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
    )
    op.execute(
        "CREATE TRIGGER trg_tableau_actualisation_immutable "
        "BEFORE UPDATE OR DELETE ON tableau_actualisations "
        "FOR EACH ROW EXECUTE FUNCTION tableau_guard_actualisation()"
    )
    for table_name in ("tableau_actualisation_inputs", "tableau_actualisation_rows"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION tableau_guard_actualisation()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tableau_actualisation_rows_immutable ON tableau_actualisation_rows")
    op.execute("DROP TRIGGER IF EXISTS trg_tableau_actualisation_inputs_immutable ON tableau_actualisation_inputs")
    op.execute("DROP TRIGGER IF EXISTS trg_tableau_actualisation_immutable ON tableau_actualisations")
    op.execute("DROP FUNCTION IF EXISTS tableau_guard_actualisation()")
    op.execute("DROP TRIGGER IF EXISTS trg_tableau_reference_member_immutable ON tableau_reference_members")
    op.execute("DROP TRIGGER IF EXISTS trg_tableau_reference_snapshot_immutable ON tableau_reference_snapshots")
    op.execute("DROP FUNCTION IF EXISTS tableau_guard_reference_snapshot()")

    op.drop_table("tableau_actualisation_rows")
    op.drop_table("tableau_actualisation_inputs")
    op.drop_table("tableau_actualisations")
    op.drop_table("tableau_reference_members")
    op.drop_table("tableau_reference_snapshots")

    op.execute(
        "DELETE FROM tableau_member_identities "
        "WHERE first_seen_import_id IS NULL OR last_seen_import_id IS NULL"
    )
    op.drop_constraint("uq_tableau_identity_official_org", "tableau_member_identities", type_="unique")
    op.drop_index("ix_tableau_member_identity_normalized_key", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_origin_type", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_reference_status", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_expert_comptable_id", table_name="tableau_member_identities")
    op.drop_index("ix_tableau_member_identities_numero_ordre_normalise", table_name="tableau_member_identities")
    op.drop_constraint("ck_tableau_identity_origin_type", "tableau_member_identities", type_="check")
    op.drop_constraint("ck_tableau_identity_reference_status", "tableau_member_identities", type_="check")
    op.drop_constraint("fk_tableau_identity_official_expert", "tableau_member_identities", type_="foreignkey")
    op.alter_column(
        "tableau_member_identities", "last_seen_import_id", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "tableau_member_identities", "first_seen_import_id", existing_type=sa.Integer(), nullable=False
    )
    op.drop_column("tableau_member_identities", "origin_type")
    op.drop_column("tableau_member_identities", "reference_match_metadata")
    op.drop_column("tableau_member_identities", "reference_match_method")
    op.drop_column("tableau_member_identities", "reference_status")
    op.drop_column("tableau_member_identities", "expert_comptable_id")
    op.drop_column("tableau_member_identities", "numero_ordre_normalise")
