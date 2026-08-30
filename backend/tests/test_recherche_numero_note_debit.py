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


# ---------------------------------------------------------------------------
# Les propositions : chercher sans réorganiser l'écran
# ---------------------------------------------------------------------------


async def _utilisateur(db, org, *, role="admin"):
    from app.models.user import User

    user = User(
        id=uuid.uuid4(), email=f"n{uuid.uuid4().hex[:6]}@ex.com", role=role,
        prenom="Ada", nom="Byron", organisation_id=org.id,
    )
    db.add(user)
    await db.commit()
    return user


async def _suggestions(db, org, user, saisie, limit=8):
    from app.api.v1.endpoints.encaissements import suggerer_numeros_note_debit

    return await suggerer_numeros_note_debit(
        q=saisie, limit=limit, tenant_id=org.id, user=user, db=db
    )


@pytest.mark.asyncio
async def test_les_propositions_tolerent_la_ponctuation_comme_le_filtre(db_session):
    """La liste proposée et la liste filtrée doivent obéir à la même règle.

    Sinon on propose un numéro qui, une fois retenu, ne rend rien.
    """
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    await _note(db_session, org, numero_recu=NUMERO)

    for saisie in (NUMERO, "nd 2026 000022", "ND2026000022", f"  {NUMERO}  "):
        propositions = await _suggestions(db_session, org, user, saisie)
        assert [p["numero"] for p in propositions] == [NUMERO], saisie


@pytest.mark.asyncio
async def test_une_proposition_porte_de_quoi_reconnaitre_la_note(db_session):
    """Un numéro seul ne suffit pas à choisir : il en faut le client et le montant."""
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    await _note(db_session, org, numero_recu=NUMERO)

    proposition = (await _suggestions(db_session, org, user, NUMERO))[0]
    assert proposition["numero"] == NUMERO
    assert proposition["client_nom"] == "Client"
    assert proposition["montant_total"] == "100.00"
    assert proposition["devise"] == "USD"
    assert proposition["est_proforma"] is False


@pytest.mark.asyncio
async def test_les_propositions_sont_bornees(db_session):
    """C'est un menu sous un champ, pas un écran : il ne doit jamais déborder."""
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    for rang in range(12):
        await _note(db_session, org, numero_recu=f"ND-2026-{rang:06d}")

    assert len(await _suggestions(db_session, org, user, "ND", limit=5)) == 5


@pytest.mark.asyncio
async def test_une_saisie_sans_caractere_significatif_ne_propose_rien(db_session):
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    await _note(db_session, org, numero_recu=NUMERO)

    assert await _suggestions(db_session, org, user, "---") == []


@pytest.mark.asyncio
async def test_les_propositions_respectent_la_portee_par_service(db_session):
    """Une suggestion est une lecture comme une autre.

    Sans cette restriction, un utilisateur borné à ses services devinerait
    l'existence de notes hors de son périmètre — et leurs numéros, qui suffisent
    à les demander ailleurs.
    """
    org = await _org(db_session)
    await _note(db_session, org, numero_recu=NUMERO)
    # Ni accès au menu, ni service : la liste lui rend déjà [], les
    # propositions doivent faire de même.
    borne = await _utilisateur(db_session, org, role="caissier")

    assert await _suggestions(db_session, org, borne, NUMERO) == []


# ---------------------------------------------------------------------------
# Les payeurs : proposer ce qui existe, pas ce qui pourrait exister
# ---------------------------------------------------------------------------


async def _note_client(db, org, nom: str, *, numero: str):
    enc = Encaissement(
        organisation_id=org.id, type_client="client_externe", client_nom=nom,
        libelle="Prestation", montant=Decimal("100"), montant_total=Decimal("100"),
        montant_paye=Decimal("100"), montant_percu=Decimal("100"),
        devise_perception="USD", canal="CAISSE", statut_paiement="complet",
        mode_paiement="cash", date_encaissement=datetime.now(timezone.utc),
        numero_recu=numero, est_proforma=False,
    )
    db.add(enc)
    await db.commit()
    return enc


async def _payeurs(db, org, user, saisie, limit=8):
    from app.api.v1.endpoints.encaissements import suggerer_payeurs

    return await suggerer_payeurs(q=saisie, limit=limit, tenant_id=org.id, user=user, db=db)


@pytest.mark.asyncio
async def test_un_payeur_propose_a_toujours_des_operations(db_session):
    """La propriété qui distingue ces propositions du référentiel clients.

    Un client du référentiel peut n'avoir aucune opération, ou en avoir sous un
    nom orthographié autrement : le proposer mènerait à une liste vide — le
    défaut même qu'on cherche à supprimer. Ici, le nombre annoncé est celui que
    la liste rendra.
    """
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    await _note_client(db_session, org, "Elie IWONDO", numero="ND-2026-000001")
    await _note_client(db_session, org, "Elie IWONDO", numero="ND-2026-000002")
    await _note_client(db_session, org, "Jean KABILA", numero="ND-2026-000003")

    propositions = await _payeurs(db_session, org, user, "IWONDO")
    assert [(p["libelle"], p["nb"]) for p in propositions] == [("Elie IWONDO", 2)]


@pytest.mark.asyncio
async def test_les_payeurs_sont_classes_par_volume(db_session):
    """Le plus fréquent d'abord : c'est presque toujours celui qu'on cherche."""
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    for rang in range(3):
        await _note_client(db_session, org, "Societe ALPHA", numero=f"ND-2026-10000{rang}")
    await _note_client(db_session, org, "Societe BETA", numero="ND-2026-200000")

    propositions = await _payeurs(db_session, org, user, "Societe")
    assert [p["libelle"] for p in propositions] == ["Societe ALPHA", "Societe BETA"]


@pytest.mark.asyncio
async def test_un_nom_absent_ne_propose_rien(db_session):
    org = await _org(db_session)
    user = await _utilisateur(db_session, org)
    await _note_client(db_session, org, "Elie IWONDO", numero="ND-2026-000001")

    assert await _payeurs(db_session, org, user, "PERSONNE") == []


@pytest.mark.asyncio
async def test_les_payeurs_respectent_la_portee_par_service(db_session):
    """Même exigence que les numéros : une suggestion est une lecture."""
    org = await _org(db_session)
    await _note_client(db_session, org, "Elie IWONDO", numero="ND-2026-000001")
    borne = await _utilisateur(db_session, org, role="caissier")

    assert await _payeurs(db_session, org, borne, "IWONDO") == []
