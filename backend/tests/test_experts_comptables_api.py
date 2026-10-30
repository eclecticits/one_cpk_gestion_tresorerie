"""Page Experts-comptables : ajout par catégorie, changement de catégorie, historique, export."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_current_user
from app.main import app

BASE = "/api/v1/experts-comptables"


@pytest_asyncio.fixture(loop_scope="session")
async def client_admin(app_client: AsyncClient, test_admin_user):
    """Client connecté en super_admin : les écritures sont réservées au Conseil National."""
    test_admin_user.role = "super_admin"
    app.dependency_overrides[get_current_user] = lambda: test_admin_user
    yield app_client
    app.dependency_overrides.pop(get_current_user, None)
    test_admin_user.role = "admin"


def _numero() -> str:
    return f"T{uuid.uuid4().hex[:10]}"


def _independant(**champs) -> dict:
    return {
        "numero_ordre": _numero(),
        "nom_denomination": "KALALA Marie",
        "type_ec": "EC",
        "categorie_personne": "Personne Physique",
        "statut_professionnel": "Indépendant",
        "nif": f"A{uuid.uuid4().hex[:8]}X",
        **champs,
    }


@pytest.mark.asyncio
async def test_ajout_d_un_independant_avec_son_nif(client_admin: AsyncClient) -> None:
    payload = _independant(telephone="0812345678", email=" Marie@Example.CD ")
    resp = await client_admin.post(BASE, json=payload)
    assert resp.status_code == 201, resp.text
    expert = resp.json()
    assert expert["nif"] == payload["nif"]
    # Même normalisation que l'import Excel.
    assert expert["telephone"] == "+243812345678"
    assert expert["email"] == "marie@example.cd"

    # Le NIF saisi doit permettre de retrouver l'expert.
    resp = await client_admin.get(BASE, params={"q": payload["nif"], "include_inactive": True})
    assert [e["id"] for e in resp.json()] == [expert["id"]]


@pytest.mark.asyncio
async def test_numero_d_ordre_en_double_refuse(client_admin: AsyncClient) -> None:
    payload = _independant()
    assert (await client_admin.post(BASE, json=payload)).status_code == 201
    assert (await client_admin.post(BASE, json=payload)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("champ,valeur", [("telephone", "abcd"), ("email", "pas-un-email")])
async def test_contact_invalide_refuse_a_l_ajout(client_admin: AsyncClient, champ: str, valeur: str) -> None:
    resp = await client_admin.post(BASE, json=_independant(**{champ: valeur}))
    assert resp.status_code == 400
    assert resp.json()["detail"]


@pytest.mark.asyncio
async def test_un_contact_ancien_invalide_ne_bloque_pas_la_modification(client_admin: AsyncClient) -> None:
    """Des e-mails invalides existent en base : corriger le nom doit rester possible."""
    from sqlalchemy import update

    from app.db.session import get_db
    from app.models.expert_comptable import ExpertComptable

    expert = (await client_admin.post(BASE, json=_independant())).json()
    async for session in app.dependency_overrides[get_db]():
        await session.execute(
            update(ExpertComptable).where(ExpertComptable.numero_ordre == expert["numero_ordre"]).values(email="ancien@invalide")
        )
        await session.commit()

    resp = await client_admin.put(
        f"{BASE}/{expert['id']}", json={"nom_denomination": "KALALA M.", "email": "ancien@invalide"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["nom_denomination"] == "KALALA M."


@pytest.mark.asyncio
async def test_changement_de_categorie_et_historique(client_admin: AsyncClient) -> None:
    expert = (await client_admin.post(BASE, json=_independant())).json()

    resp = await client_admin.post(
        f"{BASE}/category-change",
        json={
            "expert_id": expert["id"],
            "new_category": "salarie",
            "nom_employeur": "BCC",
            "reason": "Recrutement",
        },
    )
    assert resp.status_code == 200, resp.text

    apres = (await client_admin.get(f"{BASE}/{expert['id']}")).json()
    assert apres["statut_professionnel"] == "Salarié"
    assert apres["nom_employeur"] == "BCC"
    assert apres["nif"] is None

    historique = (await client_admin.get(f"{BASE}/category-changes/{expert['id']}")).json()
    assert [(h["old_category"], h["new_category"], h["reason"]) for h in historique] == [
        ("independant", "salarie", "Recrutement")
    ]


@pytest.mark.asyncio
async def test_provinces_toutes_pages_confondues(client_admin: AsyncClient) -> None:
    province = f"Province-{uuid.uuid4().hex[:6]}"
    assert (await client_admin.post(BASE, json=_independant(province_attache=province))).status_code == 201
    # Route fixe : ne doit pas être capturée par /{expert_id}.
    resp = await client_admin.get(f"{BASE}/provinces")
    assert resp.status_code == 200, resp.text
    assert province in resp.json()


@pytest.mark.asyncio
async def test_compteurs_de_categorie_alignes_sur_le_filtre_d_etat(client_admin: AsyncClient) -> None:
    """Le chiffre d'une catégorie doit être celui de la liste obtenue en cliquant dessus."""
    province = f"Province-{uuid.uuid4().hex[:6]}"
    actif = (await client_admin.post(BASE, json=_independant(province_attache=province))).json()
    inactif = (await client_admin.post(BASE, json=_independant(province_attache=province))).json()
    await client_admin.patch(f"{BASE}/{inactif['id']}", json={"active": False})

    resp = await client_admin.get(
        BASE, params={"province_attache": province, "active": True, "include_summary": True}
    )
    body = resp.json()
    assert [e["id"] for e in body["items"]] == [actif["id"]]
    assert body["summary"]["independant"] == 1
    # Les compteurs d'état, eux, restent ceux des deux états.
    assert body["summary"]["active"] == 1
    assert body["summary"]["inactive"] == 1


@pytest.mark.asyncio
async def test_export_applique_les_filtres_de_la_page_et_porte_le_nif(client_admin: AsyncClient, db_session) -> None:
    from app.api.v1.endpoints.exports import construire_classeur_experts

    province = f"Province-{uuid.uuid4().hex[:6]}"
    gardé = _independant(province_attache=province)
    assert (await client_admin.post(BASE, json=gardé)).status_code == 201
    autre_province = _independant(province_attache=f"{province}-bis")
    assert (await client_admin.post(BASE, json=autre_province)).status_code == 201
    autre_categorie = _independant(province_attache=province, statut_professionnel="Salarié")
    assert (await client_admin.post(BASE, json=autre_categorie)).status_code == 201

    wb, _ = await construire_classeur_experts(
        db_session, None, province_attache=province, category="Indépendant"
    )
    cellules = {cell.value for row in wb.active.iter_rows() for cell in row}
    assert "NIF" in cellules
    assert gardé["numero_ordre"] in cellules
    assert gardé["nif"] in cellules
    assert autre_province["numero_ordre"] not in cellules
    assert autre_categorie["numero_ordre"] not in cellules
