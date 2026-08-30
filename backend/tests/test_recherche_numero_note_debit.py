"""Chercher une note de débit par son numéro, tel qu'un humain le tape.

Le champ « N° Note de débit » comparait le numéro littéralement. Un numéro
collé depuis un courriel arrive avec des espaces, recopié à la main il arrive
souvent sans ses tirets : dans les deux cas l'écran se vidait, et
l'utilisateur — qui avait le document sous les yeux — en concluait que la note
n'existait pas.

Mesuré avant correction sur `ND-2026-000022` :

    'ND-2026-000022'        -> 3   'ND2026000022'      -> 0
    'nd-2026-000022'        -> 3   'ND 2026 000022'    -> 0
    '000022'                -> 3   '  ND-2026-000022 ' -> 0

La règle retenue compare ce qui porte l'information — lettres et chiffres — et
ignore la ponctuation de présentation des deux côtés.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.services.recherche_documents import condition_numero, normaliser_numero

NUMERO = "ND-2026-000022"


async def _org(db):
    org = Organisation(nom="Recherche", slug=f"rc-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _note(db, org, *, numero_recu=None, numero_proforma=None, est_proforma=False):
    enc = Encaissement(
        organisation_id=org.id, type_client="client_externe", client_nom="Client",
        libelle="Prestation", montant=Decimal("100"), montant_total=Decimal("100"),
        montant_paye=Decimal("100"), montant_percu=Decimal("100"),
        devise_perception="USD", canal="CAISSE", statut_paiement="complet",
        mode_paiement="cash", date_encaissement=datetime.now(timezone.utc),
        numero_recu=numero_recu, numero_proforma=numero_proforma,
        est_proforma=est_proforma,
    )
    db.add(enc)
    await db.commit()
    return enc


async def _trouve(db, org, saisie: str) -> int:
    condition = condition_numero(
        saisie, Encaissement.numero_recu, Encaissement.numero_proforma
    )
    if condition is None:
        return -1  # le filtre est ignoré : ce n'est pas « zéro résultat »
    return int(await db.scalar(
        select(func.count()).select_from(Encaissement)
        .where(Encaissement.organisation_id == org.id, condition)
    ) or 0)


def test_la_normalisation_ne_garde_que_ce_qui_identifie():
    assert normaliser_numero("ND-2026-000022") == "ND2026000022"
    assert normaliser_numero("  nd 2026 000022  ") == "ND2026000022"
    assert normaliser_numero("ND.2026/000022") == "ND2026000022"
    # Elle ne devine rien : un chiffre absent le reste.
    assert normaliser_numero("ND-2026-00002") != "ND2026000022"
    assert normaliser_numero("   ") == ""
    assert normaliser_numero(None) == ""


@pytest.mark.parametrize("saisie", [
    "ND-2026-000022",       # tel qu'imprimé
    "nd-2026-000022",       # en minuscules
    "ND2026000022",         # recopié sans les tirets
    "ND 2026 000022",       # tirets remplacés par des espaces
    "  ND-2026-000022  ",   # collé depuis un courriel
    "nd 2026 000022",       # les deux à la fois
    "000022",               # le seul rang, comme avant
])
@pytest.mark.asyncio
async def test_toutes_les_facons_de_taper_le_numero_trouvent_la_note(db_session, saisie):
    org = await _org(db_session)
    await _note(db_session, org, numero_recu=NUMERO)

    assert await _trouve(db_session, org, saisie) == 1, saisie


@pytest.mark.parametrize("saisie", ["   ", "---", "", "  -- / .. "])
@pytest.mark.asyncio
async def test_une_saisie_sans_caractere_significatif_ne_filtre_pas(db_session, saisie):
    """Vider l'écran sur une frappe accidentelle serait pire que ne rien faire.

    Un champ qu'on vient d'effacer, ou où le doigt a glissé sur un tiret, doit
    rendre l'écran intact — pas « aucun résultat ».
    """
    org = await _org(db_session)
    await _note(db_session, org, numero_recu=NUMERO)

    assert await _trouve(db_session, org, saisie) == -1, saisie


@pytest.mark.asyncio
async def test_un_numero_absent_ne_trouve_toujours_rien(db_session):
    """Le contre-test : normaliser n'est pas deviner.

    Sans lui, une règle qui rendrait tout passerait les tests ci-dessus.
    """
    org = await _org(db_session)
    await _note(db_session, org, numero_recu=NUMERO)

    assert await _trouve(db_session, org, "ND-2026-000099") == 0
    assert await _trouve(db_session, org, "XX-2026-000022") == 0


@pytest.mark.asyncio
async def test_le_numero_d_une_pro_forma_est_cherchable(db_session):
    """Elle s'appelle « pro forma de note de débit » et s'affiche sur le même
    écran : son numéro doit répondre au même champ."""
    org = await _org(db_session)
    await _note(db_session, org, numero_proforma="PF-2026-000007", est_proforma=True)

    assert await _trouve(db_session, org, "PF-2026-000007") == 1
    assert await _trouve(db_session, org, "pf2026000007") == 1


@pytest.mark.asyncio
async def test_l_ecran_et_le_classeur_cherchent_pareil(db_session):
    """Un export qui ne rend pas ce que la liste a montré est un faux.

    Les deux passent par la même condition ; ce test le vérifie sur le
    résultat, pas sur l'intention.
    """
    from app.api.v1.endpoints.exports import construire_classeur_encaissements

    org = await _org(db_session)
    await _note(db_session, org, numero_recu=NUMERO)
    await _note(db_session, org, numero_recu="ND-2026-000099")

    classeur, _ = await construire_classeur_encaissements(
        db_session, org.id, numero_recu="  nd 2026 000022  "
    )
    numeros = {
        cellule
        for ligne in classeur["Encaissements"].iter_rows(values_only=True)
        for cellule in ligne
        if isinstance(cellule, str) and cellule.startswith("ND-")
    }
    assert numeros == {NUMERO}
