import uuid
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.api.v1.endpoints.exports import export_encaissements
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.models.user import User


async def _streaming_response_bytes(response) -> bytes:
    body = b""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode()
    return body


@pytest.mark.asyncio
async def test_export_encaissements_affiche_versement_banque_hors_totaux(db_session):
    org = Organisation(
        nom="Export Transferts",
        slug=f"export-transferts-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"export-transferts-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        organisation_id=org.id,
    )
    banque = Banque(organisation_id=org.id, nom="Equity BCDC", code="EQUITY", is_active=True)
    db_session.add_all([user, banque, CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("1000"), est_ouverte=True)])
    await db_session.flush()
    compte = CompteBancaire(
        organisation_id=org.id,
        banque_id=banque.id,
        intitule="Compte Equity",
        numero_compte="EQ-USD-001",
        devise="USD",
        solde_initial=Decimal("5000"),
        solde_actuel=Decimal("8000"),
        is_active=True,
        account_type="BANK",
    )
    db_session.add(compte)
    await db_session.flush()
    enc = Encaissement(
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client réel",
        libelle="Recette économique",
        montant=Decimal("500.00"),
        montant_total=Decimal("500.00"),
        montant_paye=Decimal("500.00"),
        montant_percu=Decimal("500.00"),
        devise_perception="USD",
        canal="CAISSE",
        statut_paiement="complet",
        mode_paiement="cash",
        est_proforma=False,
        is_deleted=False,
        statut_operation="ACTIVE",
        date_encaissement=datetime(2026, 8, 28, 13, 0, tzinfo=timezone.utc),
    )
    sortie = SortieFonds(
        organisation_id=org.id,
        type_sortie="versement_banque",
        montant_paye=Decimal("3000.00"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        compte_bancaire_id=compte.id,
        motif="Dépôt des recettes journalières à la banque",
        beneficiaire="Equity BCDC",
        statut="VALIDE",
        date_paiement=datetime(2026, 8, 28, 15, 54, tzinfo=timezone.utc),
        created_by=user.id,
        reference_numero="PAY-CENTRAL-2026-00003",
    )
    db_session.add_all([enc, sortie])
    await db_session.commit()

    response = await export_encaissements(
        date_debut="2026-01-01",
        date_fin="2026-08-28",
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        expert_comptable_id=None,
        deleted_status="all",
        est_proforma=False,
        user=user,
        db=db_session,
    )
    workbook = load_workbook(BytesIO(await _streaming_response_bytes(response)), data_only=False)
    ws = workbook["Encaissements"]
    rows = list(ws.iter_rows(values_only=True))

    versement_row = next(
        row for row in rows
        if any(value == "PAY-CENTRAL-2026-00003" for value in row)
    )
    assert versement_row[1] == "Versement banque"
    assert versement_row[2] == "Caisse"
    assert versement_row[3] == "Equity BCDC"
    assert versement_row[4] == "EQ-USD-001"
    assert versement_row[12] == "Transfert interne caisse → banque (entrée bancaire)"
    assert Decimal(str(versement_row[14])) == Decimal("3000")
    assert versement_row[18] == "Transfert interne"

    total_row = next(row for row in rows if row[0] == "TOTAL")
    assert Decimal(str(total_row[15])) == Decimal("500")
    assert Decimal(str(total_row[16])) == Decimal("500")
    assert Decimal(str(total_row[17])) == Decimal("0")
