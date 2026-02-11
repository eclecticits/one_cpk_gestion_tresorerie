"""fix receipt numbering padding

Revision ID: 20260211_recu_numero_padding
Revises: 20260211_recu_numero_sequence
Create Date: 2026-02-11
"""

from alembic import op

revision = "20260211_recu_numero_padding"
down_revision = "20260211_recu_numero_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

            RETURN format('REC-ONE-CPK-%s-%s%s', yr, serie_letter, lpad(serie_number::text, 4, '0'));
        END;
        $$;
        """
    )


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

            RETURN format('REC-ONE-CPK-%s-%s%04s', yr, serie_letter, serie_number);
        END;
        $$;
        """
    )
