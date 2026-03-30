"""per-tenant receipt numbering

Revision ID: 20260330_recu_numero_per_tenant
Revises: 20260330_recu_tenant_uc
Create Date: 2026-03-30
"""

from alembic import op

revision = "20260330_recu_numero_per_tenant"
down_revision = "20260330_recu_tenant_uc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION generate_recu_numero(p_tenant_id INTEGER)
        RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            yr TEXT := to_char(current_date, 'YYYY');
            seq_name TEXT := format('rec_num_seq_%s_%s', p_tenant_id, yr);
            seq_val BIGINT;
            letter_index INT;
            serie_letter TEXT;
            serie_number INT;
            org_slug TEXT;
        BEGIN
            SELECT upper(trim(coalesce(o.slug, 'ORG'))) INTO org_slug
            FROM organisations o
            WHERE o.id = p_tenant_id
            LIMIT 1;

            IF org_slug IS NULL THEN
                org_slug := 'ORG';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND c.relname = seq_name AND n.nspname = 'public'
            ) THEN
                EXECUTE format('CREATE SEQUENCE public.%I START 1', seq_name);
            END IF;

            EXECUTE format('SELECT nextval(''public.%I'')', seq_name) INTO seq_val;
            letter_index := ((seq_val - 1) / 9999);
            serie_number := ((seq_val - 1) % 9999) + 1;
            serie_letter := chr(65 + letter_index);

            RETURN format('REC-ONEC-%s-%s-%s%04s', org_slug, yr, serie_letter, serie_number);
        END;
        $$;
        """
    )

    op.execute("ALTER TABLE encaissements ALTER COLUMN numero_recu DROP DEFAULT;")


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION generate_recu_numero()
        RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            yr TEXT := to_char(current_date, 'YYYY');
            seq_name TEXT := format('rec_num_seq_%s', yr);
            seq_val BIGINT;
            letter_index INT;
            serie_letter TEXT;
            serie_number INT;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND c.relname = seq_name AND n.nspname = 'public'
            ) THEN
                EXECUTE format('CREATE SEQUENCE public.%I START 1', seq_name);
            END IF;

            EXECUTE format('SELECT nextval(''public.%I'')', seq_name) INTO seq_val;
            letter_index := ((seq_val - 1) / 9999);
            serie_number := ((seq_val - 1) % 9999) + 1;
            serie_letter := chr(65 + letter_index);

            RETURN format('REC-ONEC-CPK-%s-%s%04s', yr, serie_letter, serie_number);
        END;
        $$;
        """
    )
    op.execute("ALTER TABLE encaissements ALTER COLUMN numero_recu SET DEFAULT generate_recu_numero();")
