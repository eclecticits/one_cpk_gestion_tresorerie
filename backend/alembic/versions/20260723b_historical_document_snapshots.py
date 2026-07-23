"""Historical snapshots and generated document versions.

Revision ID: 20260723b_hist_doc_snap
Revises: 20260723a_finance_guards
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260723b_hist_doc_snap"
down_revision = "20260723a_finance_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisitions", sa.Column("print_settings_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("requisitions", sa.Column("organisation_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("requisitions", sa.Column("bank_account_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("requisitions", sa.Column("signatories_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column(
        "requisitions",
        sa.Column("historical_snapshot_status", sa.String(length=40), nullable=False, server_default="not_finalized"),
    )
    op.add_column("requisitions", sa.Column("snapshot_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("requisitions", sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("requisitions", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("requisitions", sa.Column("exchange_rate_snapshot", sa.Numeric(12, 4), nullable=True))
    op.add_column("requisitions", sa.Column("exchange_rate_source", sa.String(length=80), nullable=True))
    op.add_column("requisitions", sa.Column("exchange_rate_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("requisitions", sa.Column("base_amount_snapshot", sa.Numeric(14, 2), nullable=True))
    op.add_column("requisitions", sa.Column("converted_amount_snapshot", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint(
        "ck_requisitions_historical_snapshot_status",
        "requisitions",
        "historical_snapshot_status IN ('not_finalized','complete','legacy_data_unverified','historical_snapshot_incomplete')",
    )

    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("signatories_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("exchange_rate_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("rendered_hash", sa.String(length=128), nullable=True),
        sa.Column("pdf_path", sa.String(length=500), nullable=True),
        sa.Column("is_original", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reprint_of_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("legacy_data_status", sa.String(length=40), nullable=False, server_default="current_snapshot"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reprint_of_id"], ["generated_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organisation_id",
            "resource_type",
            "resource_id",
            "document_type",
            "version",
            name="uq_generated_documents_resource_version",
        ),
    )
    op.create_index("ix_generated_documents_organisation_id", "generated_documents", ["organisation_id"])
    op.create_index("ix_generated_documents_resource_type", "generated_documents", ["resource_type"])
    op.create_index("ix_generated_documents_resource_id", "generated_documents", ["resource_id"])
    op.create_index("ix_generated_documents_document_type", "generated_documents", ["document_type"])
    op.create_index("ix_generated_documents_generated_by", "generated_documents", ["generated_by"])
    op.create_index("ix_generated_documents_rendered_hash", "generated_documents", ["rendered_hash"])

    op.create_table(
        "document_signatory_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("full_name_snapshot", sa.String(length=200), nullable=True),
        sa.Column("title_snapshot", sa.String(length=200), nullable=True),
        sa.Column("role_snapshot", sa.String(length=100), nullable=True),
        sa.Column("signature_snapshot", sa.String(length=500), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["generated_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_signatory_snapshots_document_id", "document_signatory_snapshots", ["document_id"])
    op.create_index("ix_document_signatory_snapshots_organisation_id", "document_signatory_snapshots", ["organisation_id"])
    op.create_index("ix_document_signatory_snapshots_user_id", "document_signatory_snapshots", ["user_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_requisition_sensitive_update_after_final()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') AND (
                OLD.numero_requisition IS DISTINCT FROM NEW.numero_requisition OR
                OLD.reference_numero IS DISTINCT FROM NEW.reference_numero OR
                OLD.objet IS DISTINCT FROM NEW.objet OR
                OLD.mode_paiement IS DISTINCT FROM NEW.mode_paiement OR
                OLD.type_requisition IS DISTINCT FROM NEW.type_requisition OR
                OLD.montant_total IS DISTINCT FROM NEW.montant_total OR
                OLD.devise IS DISTINCT FROM NEW.devise OR
                OLD.service_id IS DISTINCT FROM NEW.service_id OR
                OLD.compte_bancaire_id IS DISTINCT FROM NEW.compte_bancaire_id OR
                OLD.created_by IS DISTINCT FROM NEW.created_by OR
                OLD.validee_par IS DISTINCT FROM NEW.validee_par OR
                OLD.validee_le IS DISTINCT FROM NEW.validee_le OR
                OLD.approuvee_par IS DISTINCT FROM NEW.approuvee_par OR
                OLD.approuvee_le IS DISTINCT FROM NEW.approuvee_le OR
                OLD.signed_by_id IS DISTINCT FROM NEW.signed_by_id OR
                OLD.signed_at IS DISTINCT FROM NEW.signed_at OR
                OLD.req_titre_officiel_hist IS DISTINCT FROM NEW.req_titre_officiel_hist OR
                OLD.req_label_gauche_hist IS DISTINCT FROM NEW.req_label_gauche_hist OR
                OLD.req_nom_gauche_hist IS DISTINCT FROM NEW.req_nom_gauche_hist OR
                OLD.req_label_droite_hist IS DISTINCT FROM NEW.req_label_droite_hist OR
                OLD.req_nom_droite_hist IS DISTINCT FROM NEW.req_nom_droite_hist OR
                OLD.signataire_g_label IS DISTINCT FROM NEW.signataire_g_label OR
                OLD.signataire_g_nom IS DISTINCT FROM NEW.signataire_g_nom OR
                OLD.signataire_d_label IS DISTINCT FROM NEW.signataire_d_label OR
                OLD.signataire_d_nom IS DISTINCT FROM NEW.signataire_d_nom OR
                OLD.exchange_rate_snapshot IS DISTINCT FROM NEW.exchange_rate_snapshot OR
                OLD.exchange_rate_source IS DISTINCT FROM NEW.exchange_rate_source OR
                OLD.exchange_rate_date IS DISTINCT FROM NEW.exchange_rate_date OR
                OLD.base_amount_snapshot IS DISTINCT FROM NEW.base_amount_snapshot OR
                OLD.converted_amount_snapshot IS DISTINCT FROM NEW.converted_amount_snapshot
            ) THEN
                RAISE EXCEPTION 'Réquisition finalisée: modification historique sensible interdite';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_requisitions_immutable_after_final
        BEFORE UPDATE ON requisitions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_requisition_sensitive_update_after_final();
        """
    )
    op.execute(
        """
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
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_lignes_requisition_immutable_after_final
        BEFORE INSERT OR UPDATE OR DELETE ON lignes_requisition
        FOR EACH ROW
        EXECUTE FUNCTION prevent_ligne_requisition_change_after_final();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_lignes_requisition_immutable_after_final ON lignes_requisition")
    op.execute("DROP FUNCTION IF EXISTS prevent_ligne_requisition_change_after_final()")
    op.execute("DROP TRIGGER IF EXISTS trg_requisitions_immutable_after_final ON requisitions")
    op.execute("DROP FUNCTION IF EXISTS prevent_requisition_sensitive_update_after_final()")
    op.drop_index("ix_document_signatory_snapshots_user_id", table_name="document_signatory_snapshots")
    op.drop_index("ix_document_signatory_snapshots_organisation_id", table_name="document_signatory_snapshots")
    op.drop_index("ix_document_signatory_snapshots_document_id", table_name="document_signatory_snapshots")
    op.drop_table("document_signatory_snapshots")
    op.drop_index("ix_generated_documents_rendered_hash", table_name="generated_documents")
    op.drop_index("ix_generated_documents_generated_by", table_name="generated_documents")
    op.drop_index("ix_generated_documents_document_type", table_name="generated_documents")
    op.drop_index("ix_generated_documents_resource_id", table_name="generated_documents")
    op.drop_index("ix_generated_documents_resource_type", table_name="generated_documents")
    op.drop_index("ix_generated_documents_organisation_id", table_name="generated_documents")
    op.drop_table("generated_documents")
    op.drop_constraint("ck_requisitions_historical_snapshot_status", "requisitions", type_="check")
    op.drop_column("requisitions", "converted_amount_snapshot")
    op.drop_column("requisitions", "base_amount_snapshot")
    op.drop_column("requisitions", "exchange_rate_date")
    op.drop_column("requisitions", "exchange_rate_source")
    op.drop_column("requisitions", "exchange_rate_snapshot")
    op.drop_column("requisitions", "row_version")
    op.drop_column("requisitions", "snapshot_version")
    op.drop_column("requisitions", "snapshot_created_at")
    op.drop_column("requisitions", "historical_snapshot_status")
    op.drop_column("requisitions", "signatories_snapshot")
    op.drop_column("requisitions", "bank_account_snapshot")
    op.drop_column("requisitions", "organisation_snapshot")
    op.drop_column("requisitions", "print_settings_snapshot")
