"""Fiche « Détails de la réquisition » : les appels que fait la page.

La fiche a quitté la modale de l'écran Validation pour devenir la page
/validation/requisition/:id. Elle s'appuie sur trois appels que ces tests
couvrent bout en bout, avec une réquisition qui porte des pièces jointes :

  * GET /requisitions?id=…      relecture de la fiche au rechargement direct
                                de l'URL (filtre `id` ajouté à la liste) ;
  * GET /requisitions/{id}/annexes   la liste complète des pièces jointes ;
  * GET /requisitions/annexe/{id}    ce que déclenchent les boutons
                                     « ouvrir » et « télécharger ».
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.v1.endpoints.requisitions import UPLOAD_ROOT
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ecrire_piece_jointe(nom_fichier: str, contenu: bytes) -> str:
    """Dépose un vrai fichier là où le téléchargement ira le chercher."""
    dossier = os.path.join(UPLOAD_ROOT, "annexes")
    os.makedirs(dossier, exist_ok=True)
    with open(os.path.join(dossier, nom_fichier), "wb") as fichier:
        fichier.write(contenu)
    return f"/uploads/annexes/{nom_fichier}"


@pytest.mark.asyncio
async def test_fiche_requisition_avec_pieces_jointes(
    app_client: AsyncClient, admin_access_token: str, test_organisation, db_session
):
    org_id = test_organisation.id

    requisition = Requisition(
        numero_requisition=f"REQ-PJ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REQ-PJ-{uuid.uuid4().hex[:8]}",
        objet="Réquisition avec pièces jointes",
        mode_paiement="cash",
        type_requisition="classique",
        status="AUTORISEE",
        examen_status="EXAMINE",
        montant_total=Decimal("120.00"),
        organisation_id=org_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        is_deleted=False,
    )
    # Une seconde réquisition, sans pièce jointe : elle sert de témoin, à la
    # fois pour le filtre `id` et pour la section vide de la fiche.
    temoin = Requisition(
        numero_requisition=f"REQ-PJ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REQ-PJ-{uuid.uuid4().hex[:8]}",
        objet="Réquisition sans pièce jointe",
        mode_paiement="cash",
        type_requisition="classique",
        status="AUTORISEE",
        examen_status="EXAMINE",
        montant_total=Decimal("30.00"),
        organisation_id=org_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        is_deleted=False,
    )
    db_session.add_all([requisition, temoin])
    await db_session.flush()

    suffixe = uuid.uuid4().hex[:8]
    chemin_facture = _ecrire_piece_jointe(f"facture-{suffixe}.pdf", b"%PDF-1.4 facture")
    chemin_bordereau = _ecrire_piece_jointe(f"bordereau-{suffixe}.pdf", b"%PDF-1.4 bordereau")

    ancienne = RequisitionAnnexe(
        organisation_id=org_id,
        requisition_id=requisition.id,
        file_path=chemin_facture,
        filename="facture.pdf",
        file_type="application/pdf",
        file_size=16,
        upload_date=_utcnow() - timedelta(hours=2),
    )
    recente = RequisitionAnnexe(
        organisation_id=org_id,
        requisition_id=requisition.id,
        file_path=chemin_bordereau,
        filename="bordereau.pdf",
        file_type="application/pdf",
        file_size=18,
        upload_date=_utcnow(),
    )
    db_session.add_all([ancienne, recente])
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_access_token}"}

    # 1. Rechargement direct de /validation/requisition/:id — la page relit la
    #    réquisition par son identifiant.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={
            "id": str(requisition.id),
            "include": "demandeur,validateur,approbateur,examinateur,caissier,annexe",
            "limit": 1,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    fiche = resp.json()
    assert len(fiche) == 1
    assert fiche[0]["id"] == str(requisition.id)
    assert fiche[0]["objet"] == "Réquisition avec pièces jointes"
    # L'include « annexe » alimente le bouton « Voir la pièce jointe » de la
    # liste ; il ne rapporte que la plus récente des deux.
    assert fiche[0]["annexe"] is not None
    assert fiche[0]["annexe"]["filename"] == "bordereau.pdf"

    # La réquisition témoin n'a pas de pièce jointe : le champ reste vide.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"id": str(temoin.id), "include": "annexe", "limit": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["annexe"] is None

    # 2. La section « Pièces jointes » de la fiche : les deux, plus récente
    #    d'abord.
    resp = await app_client.get(
        f"/api/v1/requisitions/{requisition.id}/annexes", headers=headers
    )
    assert resp.status_code == 200, resp.text
    annexes = resp.json()
    assert [a["filename"] for a in annexes] == ["bordereau.pdf", "facture.pdf"]
    assert annexes[0]["file_size"] == 18
    assert annexes[0]["file_type"] == "application/pdf"

    resp = await app_client.get(f"/api/v1/requisitions/{temoin.id}/annexes", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    # 3. Les boutons « ouvrir » et « télécharger » pointent tous deux ici.
    resp = await app_client.get(
        f"/api/v1/requisitions/annexe/{annexes[0]['id']}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == b"%PDF-1.4 bordereau"
    assert "bordereau.pdf" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_filtre_id_rejette_un_identifiant_invalide(
    app_client: AsyncClient, admin_access_token: str
):
    """Un `id` mal formé répond 400, pas 500.

    Dans cette fonction, le paramètre de requête `status` masque le module
    `status` de FastAPI : écrire `status.HTTP_400_BAD_REQUEST` y lèverait un
    AttributeError, donc une 500.
    """
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"id": "pas-un-uuid"},
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    assert resp.status_code == 400, resp.text
