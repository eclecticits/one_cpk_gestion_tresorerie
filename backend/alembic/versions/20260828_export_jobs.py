"""Table export_jobs : suivi des exports generes hors du chemin HTTP

Revision ID: 20260828_export_jobs
Revises: 20260827_perf_budget_recettes
Create Date: 2026-08-28

Phase 1 de docs/architecture-exports-asynchrones-20260828.md.

POURQUOI CETTE TABLE PLUTOT QUE REDIS. `app/core/cache.py` traite Redis comme
faillible par conception : toutes ses operations avalent RedisError et rendent
None. C'est le bon choix pour un cache, et c'est ce qui interdit d'en faire la
source de verite d'un job. Un FLUSHALL, un redemarrage sans persistance, et
l'historique des exports d'une organisation disparait. Ici PostgreSQL porte
l'etat, Redis ne transporte qu'un identifiant.

CINQ INDEX, ET PAS UN DE PLUS. perf-postgres.md reproche a une vingtaine
d'index existants d'etre redondants ; chacun de ceux-ci sert une requete
identifiee, et aucun ne double le prefixe d'un autre :

  org_created  -> la liste « mes exports », par organisation, recents d'abord
  org_status   -> « cette organisation a-t-elle deja des jobs actifs ? », posee
                  a chaque soumission (equite entre tenants)
  dedup        -> « un artefact identique et recent existe-t-il ? »
  baux         -> balayage des jobs dont le worker est mort. PARTIEL sur
                  status='RUNNING' : la requete tourne toutes les minutes et ne
                  regarde qu'une fraction infime de la table
  peremption   -> purge horaire des artefacts. PARTIEL sur status='DONE'

Pas d'index simple sur organisation_id : org_created l'a en tete et sert les
memes recherches. Pas d'index sur requested_by : aucune requete ne cherche par
demandeur aujourd'hui.

CREATE INDEX classique (non CONCURRENTLY) : alembic/env.py execute chaque
migration dans une transaction, incompatible avec CONCURRENTLY. La table est
creee vide par cette meme migration, donc la construction est instantanee et
ne verrouille rien d'existant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260828_export_jobs"
down_revision = "20260827_perf_budget_recettes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        # NOT NULL : un job sans organisation serait un job dont le worker ne
        # saurait pas quel contexte tenant poser, donc un job capable de
        # produire un fichier non filtre. La contrainte est le premier des
        # trois garde-fous du §4.1.
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="QUEUED"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=True),
        # Chemin RELATIF a UPLOAD_DIR : un chemin absolu rendrait la table
        # dependante du montage et casserait au premier deplacement du volume.
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # Peremption de l'ARTEFACT, pas du job : la ligne reste pour
        # l'historique, le fichier est supprime.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"], ondelete="CASCADE"
        ),
        # SET NULL : supprimer un compte ne doit pas effacer la trace de
        # l'export ni son fichier.
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
    )

    op.create_index("ix_export_jobs_org_created", "export_jobs", ["organisation_id", "created_at"])
    op.create_index("ix_export_jobs_org_status", "export_jobs", ["organisation_id", "status"])
    op.create_index(
        "ix_export_jobs_dedup", "export_jobs", ["organisation_id", "params_hash", "status"]
    )
    op.create_index(
        "ix_export_jobs_baux",
        "export_jobs",
        ["lease_until"],
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.create_index(
        "ix_export_jobs_peremption",
        "export_jobs",
        ["expires_at"],
        postgresql_where=sa.text("status = 'DONE'"),
    )


def downgrade() -> None:
    # Les index tombent avec la table ; les nommer serait du bruit.
    op.drop_table("export_jobs")
