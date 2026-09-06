"""Réglages de la console super-admin : grille tarifaire et logo éditeur.

La console ne savait ni décrire les tarifs de l'application ni porter le logo
de l'éditeur : `Organisation.plan_type` était une chaîne libre sans catalogue
derrière, et la facture n'imprimait que la raison sociale en texte.
"""

import io
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.security import hash_password
from app.models.user import User

SUPER_ADMIN_EMAIL = "super-admin-reglages@example.com"
SUPER_ADMIN_PASSWORD = "Super_Reglages_2026!"


@pytest_asyncio.fixture
async def super_admin_access_token(
    app_client: AsyncClient, db_session, test_organisation
) -> str:
    """Un super administrateur connecté.

    Les tests super-admin existants passent par des mocks ; ceux-ci attaquent
    les endpoints, il leur faut donc un vrai compte et un vrai jeton.
    """
    from sqlalchemy import select

    res = await db_session.execute(select(User).where(User.email == SUPER_ADMIN_EMAIL))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=SUPER_ADMIN_EMAIL,
            hashed_password=hash_password(SUPER_ADMIN_PASSWORD),
            prenom="Console",
            nom="Editeur",
            role="super_admin",
            organisation_id=test_organisation.id,
            active=True,
            is_email_verified=True,
            is_first_login=False,
            must_change_password=False,
        )
        db_session.add(user)
        await db_session.commit()

    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASSWORD},
        headers={"X-Tenant-ID": str(test_organisation.id)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _entete(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@pytest.mark.asyncio
async def test_grille_tarifaire_se_lit_et_s_enregistre(
    app_client: AsyncClient, super_admin_access_token: str
):
    entetes = _entete(super_admin_access_token)
    suffixe = uuid.uuid4().hex[:6].upper()

    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={
            "plans": [
                {
                    "code": f"socle {suffixe}",
                    "name": "Socle",
                    "description": "Le nécessaire",
                    "price": "49.9",
                    "currency": "USD",
                    "interval": "monthly",
                },
                {
                    "code": f"etendu-{suffixe}",
                    "name": "Étendu",
                    "price": 149,
                    "currency": "CDF",
                    "interval": "yearly",
                    "active": False,
                },
            ]
        },
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    plans = {p["code"]: p for p in resp.json()}

    # Le code est normalisé : majuscules, espaces remplacés.
    socle = plans[f"SOCLE_{suffixe}"]
    assert socle["name"] == "Socle"
    # Le prix est arrondi au centime et voyage en texte.
    assert socle["price"] == "49.90"
    assert socle["currency"] == "USD"
    assert socle["interval"] == "monthly"
    assert socle["active"] is True

    etendu = plans[f"ETENDU-{suffixe}"]
    assert etendu["price"] == "149.00"
    assert etendu["currency"] == "CDF"
    assert etendu["active"] is False

    # Relecture : le catalogue est bien persisté.
    resp = await app_client.get("/api/v1/super-admin/billing/plans", headers=entetes)
    assert resp.status_code == 200, resp.text
    assert {p["code"] for p in resp.json()} >= {f"SOCLE_{suffixe}", f"ETENDU-{suffixe}"}


@pytest.mark.asyncio
async def test_valeurs_hors_domaine_retombent_sur_les_defauts(
    app_client: AsyncClient, super_admin_access_token: str
):
    """Une devise ou une périodicité inconnue ne doit pas entrer en base : le
    reste de la facturation ne sait traiter que USD/CDF et quatre rythmes."""
    entetes = _entete(super_admin_access_token)
    code = f"BIZARRE{uuid.uuid4().hex[:6].upper()}"

    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={
            "plans": [
                {
                    "code": code,
                    "name": "Hors domaine",
                    "price": "abc",
                    "currency": "EUR",
                    "interval": "hebdomadaire",
                }
            ]
        },
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    plan = next(p for p in resp.json() if p["code"] == code)
    assert plan["currency"] == "USD"
    assert plan["interval"] == "monthly"
    assert plan["price"] == "0.00"

    # Un plan sans code n'a pas de clé : il est refusé.
    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={"plans": [{"code": "   ", "name": "Sans code"}]},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_le_plan_d_une_organisation_doit_exister_dans_la_grille(
    app_client: AsyncClient, super_admin_access_token: str, test_organisation
):
    entetes = _entete(super_admin_access_token)
    code = f"REEL{uuid.uuid4().hex[:6].upper()}"

    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={"plans": [{"code": code, "name": "Plan réel", "price": "10"}]},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text

    # Un code absent du catalogue est refusé, avec la liste des codes valides.
    resp = await app_client.patch(
        f"/api/v1/super-admin/organisations/{test_organisation.id}",
        json={"plan_type": "PLAN_INVENTE"},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text
    assert code in resp.json()["detail"]

    # Un code du catalogue passe, et ressort normalisé.
    resp = await app_client.patch(
        f"/api/v1/super-admin/organisations/{test_organisation.id}",
        json={"plan_type": code.lower()},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_type"] == code

    # Grille vidée : le champ redevient libre, comme avant l'introduction du
    # catalogue — une installation existante n'est pas bloquée.
    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans", json={"plans": []}, headers=entetes
    )
    assert resp.status_code == 200, resp.text
    resp = await app_client.patch(
        f"/api/v1/super-admin/organisations/{test_organisation.id}",
        json={"plan_type": "STANDARD"},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_type"] == "STANDARD"


@pytest.mark.asyncio
async def test_l_essai_passe_aussi_par_la_grille(
    app_client: AsyncClient, super_admin_access_token: str, test_organisation
):
    """Accorder un essai est une écriture de plan comme une autre.

    C'est le chemin le plus tentant pour contourner le catalogue : deux clics
    dans la console, et l'organisation repart sur un code que la facturation
    ne saura pas tarifer.
    """
    entetes = _entete(super_admin_access_token)
    code = f"ESSAI{uuid.uuid4().hex[:6].upper()}"

    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={"plans": [{"code": code, "name": "Découverte", "price": "0"}]},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text

    resp = await app_client.post(
        f"/api/v1/super-admin/organisations/{test_organisation.id}/grant-trial",
        json={"plan_type": "STANDARD", "duration_days": 15},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text
    assert code in resp.json()["detail"]

    resp = await app_client.post(
        f"/api/v1/super-admin/organisations/{test_organisation.id}/grant-trial",
        json={"plan_type": code.lower(), "duration_days": 15},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_type"] == code
    assert resp.json()["status_abonnement"] == "TRIAL"

    # Grille vidée : le champ redevient libre, ici aussi.
    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans", json={"plans": []}, headers=entetes
    )
    assert resp.status_code == 200, resp.text
    resp = await app_client.post(
        f"/api/v1/super-admin/organisations/{test_organisation.id}/grant-trial",
        json={"plan_type": "STANDARD", "duration_days": 15},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_type"] == "STANDARD"


@pytest.mark.asyncio
async def test_logo_editeur_depose_relu_et_supprime(
    app_client: AsyncClient, super_admin_access_token: str
):
    entetes = _entete(super_admin_access_token)

    resp = await app_client.post(
        "/api/v1/super-admin/branding/logo",
        files={"file": ("eclectique.png", PNG_1x1, "image/png")},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    descripteur = resp.json()
    assert descripteur["present"] is True
    assert descripteur["filename"] == "eclectique.png"
    assert descripteur["size"] == len(PNG_1x1)

    resp = await app_client.get("/api/v1/super-admin/branding/logo", headers=entetes)
    assert resp.status_code == 200, resp.text
    assert resp.json()["present"] is True

    resp = await app_client.get("/api/v1/super-admin/branding/logo/file", headers=entetes)
    assert resp.status_code == 200, resp.text
    assert resp.content == PNG_1x1

    # Un format non supporté est refusé plutôt que stocké tel quel.
    resp = await app_client.post(
        "/api/v1/super-admin/branding/logo",
        files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text

    resp = await app_client.delete("/api/v1/super-admin/branding/logo", headers=entetes)
    assert resp.status_code == 200, resp.text
    assert resp.json()["present"] is False

    resp = await app_client.get("/api/v1/super-admin/branding/logo/file", headers=entetes)
    assert resp.status_code == 404, resp.text


def _png_colore(couleur: tuple[int, int, int]) -> bytes:
    """Un logo d'une seule teinte, sur fond blanc — de quoi vérifier d'où la
    facture tire sa couleur."""
    from PIL import Image

    image = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    for x in range(8, 24):
        for y in range(8, 24):
            image.putpixel((x, y), (*couleur, 255))
    tampon = io.BytesIO()
    image.save(tampon, format="PNG")
    return tampon.getvalue()


@pytest.mark.asyncio
async def test_couleur_de_facture_tiree_du_logo_puis_ajustable(
    app_client: AsyncClient, super_admin_access_token: str
):
    """La facture prend les couleurs de la marque, sans qu'on les saisisse.

    L'extraction se laisse parfois prendre par un détail coloré : la couleur
    reste donc corrigeable, et le retour en arrière ne demande pas de redéposer
    le fichier.
    """
    entetes = _entete(super_admin_access_token)

    resp = await app_client.post(
        "/api/v1/super-admin/branding/logo",
        files={"file": ("marque.png", _png_colore((16, 90, 200)), "image/png")},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accent"] == "#105AC8"
    assert resp.json()["accent_detecte"] == "#105AC8"

    # Correction à la main : seule la couleur retenue change.
    resp = await app_client.put(
        "/api/v1/super-admin/branding/accent",
        json={"accent": "#0f766e"},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accent"] == "#0F766E"
    assert resp.json()["accent_detecte"] == "#105AC8"

    # Valeur vide : on revient à ce que dit le logo.
    resp = await app_client.put(
        "/api/v1/super-admin/branding/accent", json={"accent": ""}, headers=entetes
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accent"] == "#105AC8"

    resp = await app_client.put(
        "/api/v1/super-admin/branding/accent", json={"accent": "bleu"}, headers=entetes
    )
    assert resp.status_code == 400, resp.text

    # Un logo gris n'impose aucune couleur : la facture garde la sienne.
    resp = await app_client.post(
        "/api/v1/super-admin/branding/logo",
        files={"file": ("gris.png", _png_colore((40, 40, 40)), "image/png")},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accent"] == ""

    # Sans logo, la couleur n'a plus de support.
    resp = await app_client.delete("/api/v1/super-admin/branding/logo", headers=entetes)
    assert resp.status_code == 200, resp.text
    resp = await app_client.put(
        "/api/v1/super-admin/branding/accent",
        json={"accent": "#0F766E"},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_facture_sans_ligne_se_pre_remplit_depuis_le_plan(
    app_client: AsyncClient, super_admin_access_token: str, test_organisation
):
    """Le prix facturé vient de la grille, pas d'une ressaisie.

    Retaper à la main un montant déjà écrit dans le catalogue est le meilleur
    moyen de facturer un tarif qui n'est plus le bon.
    """
    entetes = _entete(super_admin_access_token)
    code = f"ABO{uuid.uuid4().hex[:6].upper()}"

    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans",
        json={
            "plans": [
                {
                    "code": code,
                    "name": "Socle national",
                    "price": "250.50",
                    "currency": "CDF",
                    "interval": "yearly",
                }
            ]
        },
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text

    resp = await app_client.patch(
        f"/api/v1/super-admin/organisations/{test_organisation.id}",
        json={"plan_type": code},
        headers=entetes,
    )
    assert resp.status_code == 200, resp.text

    resp = await app_client.post(
        "/api/v1/super-admin/invoices",
        json={"organisation_id": test_organisation.id, "issue": False},
        headers=entetes,
    )
    assert resp.status_code == 201, resp.text
    facture = resp.json()

    assert len(facture["lines"]) == 1
    ligne = facture["lines"][0]
    assert "Socle national" in ligne["designation"]
    assert "annuel" in ligne["designation"]
    assert Decimal(str(ligne["prix_unitaire"])) == Decimal("250.50")
    assert Decimal(str(facture["amount"])) == Decimal("250.50")
    # La devise suit le plan tant que l'appelant n'en impose pas une.
    assert facture["currency"] == "CDF"

    # Une devise explicite l'emporte sur celle du plan.
    resp = await app_client.post(
        "/api/v1/super-admin/invoices",
        json={"organisation_id": test_organisation.id, "issue": False, "currency": "USD"},
        headers=entetes,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["currency"] == "USD"

    # Grille vidée : plus de plan connu, la facture sans ligne est refusée
    # avec un message qui dit quoi faire, au lieu d'un total à zéro.
    resp = await app_client.put(
        "/api/v1/super-admin/billing/plans", json={"plans": []}, headers=entetes
    )
    assert resp.status_code == 200, resp.text
    resp = await app_client.post(
        "/api/v1/super-admin/invoices",
        json={"organisation_id": test_organisation.id, "issue": False},
        headers=entetes,
    )
    assert resp.status_code == 400, resp.text
    assert "grille tarifaire" in resp.json()["detail"]
