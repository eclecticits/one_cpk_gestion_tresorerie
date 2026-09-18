"""Cinq types de client au lieu de huit

Revision ID: 20260918_types_client
Revises: 20260918_collation5

La liste disait la même chose sous trop de noms : « Client externe »,
« Banque / Institution » et « Organisation » n'apportaient rien que
« Personne physique » ou « Personne morale » ne disent déjà, et l'on rangeait
une personne sous « Organisation ». Il reste : expert-comptable, personne
physique, personne morale, partenaire, autre.

Reclassement, sur les encaissements comme sur les fiches clients :
- client_externe → personne_physique : c'était le seul des trois à qui l'on
  demandait un sexe, il y avait donc une personne derrière ;
- banque_institution, organisation → personne_morale ;
- sauf la régularisation d'écart de caisse, enregistrée en « organisation »
  alors qu'elle n'a pas de client : elle passe en « autre » ;
- sauf Elie IWONDO, une personne saisie en « organisation » : personne
  physique. Son sexe reste à renseigner sur sa fiche.

Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op


revision = "20260918_types_client"
down_revision = "20260918_collation5"
branch_labels = None
depends_on = None


TYPES = "('expert_comptable','personne_physique','personne_morale','partenaire','autre')"
ANCIENS_TYPES = (
    "('expert_comptable','personne_physique','personne_morale','client_externe',"
    "'banque_institution','partenaire','organisation','autre')"
)
LIBELLE_REGULARISATION = "Régularisation d'écart de caisse"


def _reclasser(table: str, colonne_nom: str) -> None:
    op.execute(
        f"UPDATE {table} SET type_client = 'autre' "
        f"WHERE type_client = 'organisation' AND {colonne_nom} = '{LIBELLE_REGULARISATION.replace(chr(39), chr(39) * 2)}'"
    )
    op.execute(
        f"UPDATE {table} SET type_client = 'personne_physique' "
        f"WHERE type_client = 'organisation' AND lower(trim({colonne_nom})) = 'elie iwondo'"
    )
    op.execute(
        f"UPDATE {table} SET type_client = 'personne_physique' WHERE type_client = 'client_externe'"
    )
    op.execute(
        f"UPDATE {table} SET type_client = 'personne_morale' "
        f"WHERE type_client IN ('banque_institution', 'organisation')"
    )


def upgrade() -> None:
    _reclasser("encaissements", "client_nom")
    _reclasser("clients", "nom")
    # Une valeur hors liste sur une fiche (saisie libre de l'ancienne API) n'a
    # pas de sens à garder : le type d'une fiche n'est qu'indicatif.
    op.execute(f"UPDATE clients SET type_client = NULL WHERE type_client NOT IN {TYPES}")

    op.drop_constraint("ck_encaissements_type_client", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_type_client", "encaissements", f"type_client IN {TYPES}"
    )
    op.create_check_constraint(
        "ck_clients_type_client", "clients", f"type_client IS NULL OR type_client IN {TYPES}"
    )


def downgrade() -> None:
    # Le reclassement ne se défait pas : on ne sait plus qui était quoi.
    op.drop_constraint("ck_clients_type_client", "clients", type_="check")
    op.drop_constraint("ck_encaissements_type_client", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_type_client", "encaissements", f"type_client IN {ANCIENS_TYPES}"
    )
