"""Rubrique des virements internes, contrepartie à l'export comptable

Revision ID: 20261110_virements_internes
Revises: 20261110_modules_accueil

L'export pour le logiciel comptable part désormais de la trésorerie. Un
approvisionnement de caisse, un versement à la banque ou un transfert interne
y prend pour contrepartie le compte de la rubrique `VIREMENTS_INTERNES`. Les
organisations déjà paramétrées la reçoivent mappée sur leur compte 4713
« Virements de fonds », que tous les plans de démarrage portent ; les
nouvelles l'ont par le mapping par défaut.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20261110_virements_internes"
down_revision = "20261110_modules_accueil"
branch_labels = None
depends_on = None


MAPPER = """
    INSERT INTO compta_mapping_rubrique (organisation_id, code_rubrique, compte_id, created_at)
    SELECT DISTINCT ON (c.organisation_id) c.organisation_id, 'VIREMENTS_INTERNES', c.id, now()
    FROM compta_comptes c
    WHERE c.numero = '4713'
      -- Seules les organisations dont la comptabilité est paramétrée : celles
      -- qui ont déjà au moins une rubrique mappée.
      AND EXISTS (SELECT 1 FROM compta_mapping_rubrique m WHERE m.organisation_id = c.organisation_id)
      AND NOT EXISTS (
          SELECT 1 FROM compta_mapping_rubrique m
          WHERE m.organisation_id = c.organisation_id AND m.code_rubrique = 'VIREMENTS_INTERNES'
      )
    ORDER BY c.organisation_id, c.id
"""


def upgrade() -> None:
    op.get_bind().execute(text(MAPPER))


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM compta_mapping_rubrique WHERE code_rubrique = 'VIREMENTS_INTERNES'"))
