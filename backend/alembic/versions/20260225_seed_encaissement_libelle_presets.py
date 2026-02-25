"""seed encaissement libelle presets

Revision ID: 20260225_seed_enc_libelle
Revises: 20260225_add_enc_libelle_presets
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260225_seed_enc_libelle"
down_revision = "20260225_add_enc_libelle_presets"
branch_labels = None
depends_on = None

PRESET = """Cotisation annuelle - Expert-Comptable Cabinet
Cotisation annuelle - Expert-Comptable Indépendant
Cotisation annuelle - Expert-Comptable Salarié
Cotisation annuelle - Stagiaire (SEC)
Arriérés de cotisation
Pénalité de retard - Cotisation
Régularisation cotisation antérieure
Frais de participation - Formation fiscale
Frais de participation - Co-commissariat
Inscription - Séminaire professionnel
Attestation de formation
Contribution FORCO annuelle
Pénalité absence formation obligatoire
Frais d'inscription au Tableau
Frais de réinscription
Frais d'étude de dossier
Délivrance attestation d'inscription
Délivrance duplicata carte professionnelle
Mutation / Transfert de cabinet
Frais de stage professionnel
Délivrance certificat professionnel
Légalisation de signature
Certification de documents
Attestation de conformité
Vente de formulaire officiel
Amende disciplinaire
Pénalité administrative
Régularisation décision disciplinaire
Contribution Commission Tableau
Contribution Commission FORCO
Contribution Commission Discipline
Contribution événement institutionnel
Participation activité spéciale ONEC
Location salle de réunion
Contribution partenaire institutionnel
Sponsoring événement
Subvention reçue
Don volontaire
Recette exceptionnelle
Vente matériel usagé
Remboursement frais
Autres recettes"""


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE print_settings
            SET encaissement_libelle_presets = :preset
            WHERE encaissement_libelle_presets IS NULL OR encaissement_libelle_presets = ''
            """
        ).bindparams(preset=PRESET)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE print_settings
            SET encaissement_libelle_presets = ''
            WHERE encaissement_libelle_presets = :preset
            """
        ).bindparams(preset=PRESET)
    )
