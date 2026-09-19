"""Ce qu'un payeur doit encore, annoncé au moment où on le saisit.

Une créance vit aujourd'hui note de débit par note de débit : un même client
avec trois règlements partiels apparaît trois fois, et aucun écran n'en fait la
somme. Le caissier qui encaisse ne peut donc pas savoir que la personne devant
lui doit encore quelque chose — il le découvrira dans un rapport, le mois
suivant, quand elle sera repartie.

`suggestions-client` est appelé à chaque frappe : c'est là que l'information a
de la valeur, et nulle part ailleurs. Ces tests verrouillent ce qu'elle annonce.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.encaissements import suggerer_payeurs
from app.models.expert_comptable import ExpertComptable

from test_encaissements import _enc_org, _enc_user, _encaissement_row, _suffix


async def _devoir(db_session, org, user, *, nom, total, paye, est_proforma=False):
    """Une note de débit dont il reste quelque chose à payer."""
    enc = await _encaissement_row(db_session, org, user, montant_paye=Decimal(str(paye)))
    enc.client_nom = nom
    enc.montant = Decimal(str(total))
    enc.montant_total = Decimal(str(total))
    enc.est_proforma = est_proforma
    enc.statut_paiement = "partiel" if Decimal(str(paye)) > 0 else "non_paye"
    await db_session.flush()
    return enc


async def _proposer(db_session, user, terme):
    return await suggerer_payeurs(
        q=terme, limit=8, tenant_id=user.organisation_id, user=user, db=db_session
    )


@pytest.mark.asyncio
async def test_la_dette_d_un_payeur_est_annoncee_pendant_la_frappe(db_session):
    """Deux notes partielles d'un même nom : la proposition en donne la somme."""
    org = await _enc_org(db_session, name=f"Creances {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Mabiala {_suffix()}"
    await _devoir(db_session, org, user, nom=nom, total=1000, paye=400)
    await _devoir(db_session, org, user, nom=nom, total=500, paye=0)

    (proposition,) = [p for p in await _proposer(db_session, user, nom) if p["valeur"] == nom]

    assert proposition["reste_du"] == pytest.approx(1100.0)
    assert proposition["nb_impayes"] == 2
    assert proposition["nb"] == 2


@pytest.mark.asyncio
async def test_un_payeur_a_jour_n_annonce_aucune_dette(db_session):
    """Le signalement ne doit pas crier au loup : soldé, il se tait."""
    org = await _enc_org(db_session, name=f"Creances {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Solde {_suffix()}"
    await _devoir(db_session, org, user, nom=nom, total=500, paye=500)

    (proposition,) = [p for p in await _proposer(db_session, user, nom) if p["valeur"] == nom]

    assert proposition["reste_du"] == 0
    assert proposition["nb_impayes"] == 0


@pytest.mark.asyncio
async def test_une_proforma_impayee_n_est_pas_une_creance(db_session):
    """Un devis n'est pas une dette : rien n'est dû tant qu'il n'est pas converti."""
    org = await _enc_org(db_session, name=f"Creances {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Devis {_suffix()}"
    await _devoir(db_session, org, user, nom=nom, total=900, paye=0, est_proforma=True)

    (proposition,) = [p for p in await _proposer(db_session, user, nom) if p["valeur"] == nom]

    assert proposition["reste_du"] == 0, "une proforma ne doit rien réclamer"
    assert proposition["nb_impayes"] == 0


@pytest.mark.asyncio
async def test_le_debiteur_passe_devant_le_payeur_a_jour(db_session):
    """Le tri sert le geste : celui qui doit de l'argent ne doit pas se noyer.

    Le payeur à jour a plus d'opérations — c'est lui qui remontait avant. Ce
    qu'on veut voir en premier, c'est celui qui doit encore quelque chose.
    """
    org = await _enc_org(db_session, name=f"Creances {_suffix()}")
    user = await _enc_user(db_session, org)
    souche = f"Ngoy{_suffix()}"
    a_jour, debiteur = f"{souche} Paye", f"{souche} Doit"
    for _ in range(3):
        await _devoir(db_session, org, user, nom=a_jour, total=100, paye=100)
    await _devoir(db_session, org, user, nom=debiteur, total=800, paye=100)

    propositions = [p for p in await _proposer(db_session, user, souche) if p["valeur"] in (a_jour, debiteur)]

    assert propositions[0]["valeur"] == debiteur
    assert propositions[0]["reste_du"] == pytest.approx(700.0)


@pytest.mark.asyncio
async def test_l_expert_est_identifie_surement_le_payeur_libre_non(db_session):
    """La dette d'un expert est complète ; celle d'un nom saisi est un minimum.

    Le numéro d'ordre est unique, donc rien ne peut manquer. Un payeur en texte
    libre n'est groupé que sur son nom : une autre orthographe porterait une
    seconde dette, invisible ici. L'écran doit pouvoir faire la différence.
    """
    org = await _enc_org(db_session, name=f"Creances {_suffix()}")
    user = await _enc_user(db_session, org)
    numero = f"EC/{_suffix()[:5]}"
    # Le référentiel des experts est global : le numéro d'ordre y est unique,
    # sans organisation. Le cadrage par tenant se fait sur l'encaissement.
    expert = ExpertComptable(
        id=uuid.uuid4(),
        numero_ordre=numero,
        nom_denomination=f"Cabinet {_suffix()}",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.flush()

    enc = await _devoir(db_session, org, user, nom=f"Libre {_suffix()}", total=300, paye=0)
    libre = enc.client_nom
    note = await _devoir(db_session, org, user, nom=expert.nom_denomination, total=700, paye=200)
    note.type_client = "expert_comptable"
    note.expert_comptable_id = expert.id
    note.client_nom = None
    await db_session.flush()

    par_expert = [p for p in await _proposer(db_session, user, numero) if p["type"] == "expert"]
    assert par_expert and par_expert[0]["identite_sure"] is True
    assert par_expert[0]["reste_du"] == pytest.approx(500.0)

    par_nom = [p for p in await _proposer(db_session, user, libre) if p["valeur"] == libre]
    assert par_nom and par_nom[0]["identite_sure"] is False


# ---------------------------------------------------------------------------
# La liste agrégée : qui nous doit, et depuis quand
# ---------------------------------------------------------------------------


async def _lister(db_session, user, **kwargs):
    from app.api.v1.endpoints.encaissements import lister_debiteurs
    params = {"q": None, "type_client": None, "anciennete_min": 0, "limit": 50, "offset": 0}
    params.update(kwargs)
    return await lister_debiteurs(
        tenant_id=user.organisation_id, user=user, db=db_session, **params
    )


@pytest.mark.asyncio
async def test_les_notes_d_un_meme_payeur_ne_font_qu_une_ardoise(db_session):
    """Trois règlements partiels d'un même nom : une ligne, pas trois."""
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Kabeya {_suffix()}"
    for total, paye in ((1000, 400), (500, 0), (300, 100)):
        await _devoir(db_session, org, user, nom=nom, total=total, paye=paye)

    res = await _lister(db_session, user)
    (ligne,) = [d for d in res["debiteurs"] if d["libelle"] == nom]

    assert ligne["nb_notes"] == 3
    assert ligne["reste_du"] == pytest.approx(1300.0)
    assert res["total_du"] == pytest.approx(1300.0)
    assert res["nb_debiteurs"] == 1


@pytest.mark.asyncio
async def test_deux_orthographes_d_un_meme_nom_se_rejoignent(db_session):
    """« ALAIN  LUKA » et « alain luka » sont le même débiteur, et c'est annoncé.

    Le rapprochement par le nom est presque toujours juste, et parfois faux :
    l'écran doit pouvoir le dire, d'où `identite_sure` à faux.
    """
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    souche = f"Luka{_suffix()}"
    await _devoir(db_session, org, user, nom=f"  {souche.upper()}  ", total=600, paye=100)
    await _devoir(db_session, org, user, nom=souche.lower(), total=400, paye=0)

    res = await _lister(db_session, user)

    assert res["nb_debiteurs"] == 1
    (ligne,) = res["debiteurs"]
    assert ligne["nb_notes"] == 2
    assert ligne["reste_du"] == pytest.approx(900.0)
    assert ligne["identite_sure"] is False


@pytest.mark.asyncio
async def test_l_anciennete_ordonne_la_liste_et_situe_la_creance(db_session):
    """Le plus vieux débiteur passe devant : c'est lui qu'il faut relancer."""
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    recent, ancien = f"Recent {_suffix()}", f"Ancien {_suffix()}"
    jeune = await _devoir(db_session, org, user, nom=recent, total=900, paye=0)
    jeune.date_encaissement = datetime.now(timezone.utc) - timedelta(days=10)
    vieux = await _devoir(db_session, org, user, nom=ancien, total=100, paye=0)
    vieux.date_encaissement = datetime.now(timezone.utc) - timedelta(days=120)
    await db_session.flush()

    res = await _lister(db_session, user)

    assert res["debiteurs"][0]["libelle"] == ancien, "le plus ancien d'abord, pas le plus gros"
    assert res["debiteurs"][0]["tranche"] == "plus_90"
    assert res["debiteurs"][0]["jours"] >= 119
    assert res["debiteurs"][1]["tranche"] == "moins_30"


@pytest.mark.asyncio
async def test_le_filtre_d_anciennete_ecarte_les_creances_fraiches(db_session):
    """Relancer à 10 jours n'a pas de sens : on veut pouvoir borner."""
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    recent, ancien = f"Frais {_suffix()}", f"Vieux {_suffix()}"
    jeune = await _devoir(db_session, org, user, nom=recent, total=900, paye=0)
    jeune.date_encaissement = datetime.now(timezone.utc) - timedelta(days=5)
    vieux = await _devoir(db_session, org, user, nom=ancien, total=100, paye=0)
    vieux.date_encaissement = datetime.now(timezone.utc) - timedelta(days=100)
    await db_session.flush()

    res = await _lister(db_session, user, anciennete_min=60)

    assert res["nb_debiteurs"] == 1
    assert res["debiteurs"][0]["libelle"] == ancien
    assert res["total_du"] == pytest.approx(100.0), "le total suit le filtre, pas la page"


@pytest.mark.asyncio
async def test_un_expert_est_regroupe_sur_son_identite_pas_sur_son_nom(db_session):
    """Deux notes saisies sous des libellés différents, un seul expert.

    C'est tout l'intérêt d'une identité sûre : le regroupement ne dépend plus de
    ce que la caisse a tapé ce jour-là.
    """
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    numero = f"EC/{_suffix()[:5]}"
    expert = ExpertComptable(
        id=uuid.uuid4(),
        numero_ordre=numero,
        nom_denomination=f"Cabinet {_suffix()}",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.flush()

    for libelle, total, paye in ((f"Cabinet {_suffix()}", 800, 300), (f"CAB. {_suffix()}", 200, 0)):
        note = await _devoir(db_session, org, user, nom=libelle, total=total, paye=paye)
        note.type_client = "expert_comptable"
        note.expert_comptable_id = expert.id
    await db_session.flush()

    res = await _lister(db_session, user)

    assert res["nb_debiteurs"] == 1
    (ligne,) = res["debiteurs"]
    assert ligne["identite_sure"] is True
    assert ligne["libelle"] == expert.nom_denomination, "le référentiel fait foi, pas la saisie"
    assert ligne["detail"] == numero
    assert ligne["reste_du"] == pytest.approx(700.0)


@pytest.mark.asyncio
async def test_les_relances_deja_envoyees_sont_reportees(db_session):
    """La donnée existe et n'était affichée nulle part : en relancer une de plus,
    c'est perdre son temps sur un refus que le backend opposera de toute façon."""
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Relance {_suffix()}"
    envoyee_le = datetime.now(timezone.utc) - timedelta(days=2)
    note = await _devoir(db_session, org, user, nom=nom, total=500, paye=100)
    note.relance_count = 2
    note.derniere_relance_le = envoyee_le
    autre = await _devoir(db_session, org, user, nom=nom, total=300, paye=0)
    autre.relance_count = 1
    await db_session.flush()

    res = await _lister(db_session, user)
    (ligne,) = [d for d in res["debiteurs"] if d["libelle"] == nom]

    assert ligne["relances"] == 3
    assert ligne["derniere_relance_le"] is not None


@pytest.mark.asyncio
async def test_une_proforma_n_entre_pas_dans_l_ardoise(db_session):
    """Même règle que le signalement : un devis n'est pas une dette."""
    org = await _enc_org(db_session, name=f"Debiteurs {_suffix()}")
    user = await _enc_user(db_session, org)
    await _devoir(db_session, org, user, nom=f"Devis {_suffix()}", total=900, paye=0, est_proforma=True)

    res = await _lister(db_session, user)

    assert res["nb_debiteurs"] == 0
    assert res["total_du"] == 0


# ---------------------------------------------------------------------------
# Sur quoi il doit : les notes à solder, depuis la saisie
# ---------------------------------------------------------------------------
#
# La liste des débiteurs dit QUI doit ; celle-ci dit SUR QUOI. Sans elle, le
# caissier averti pendant la frappe n'a aucun chemin vers la note à compléter :
# il encaisse « ici », une seconde note naît, et la première reste ouverte pour
# toujours. L'argent rentre, la créance demeure.


async def _notes_impayees(db_session, user, **kwargs):
    from app.api.v1.endpoints.encaissements import lister_notes_impayees
    params = {"client_id": None, "expert_comptable_id": None, "nom": None, "limit": 20}
    params.update(kwargs)
    return await lister_notes_impayees(
        tenant_id=user.organisation_id, user=user, db=db_session, **params
    )


async def _client_du_referentiel(db_session, org, nom):
    from app.models.client import Client
    client = Client(id=uuid.uuid4(), organisation_id=org.id, nom=nom, active=True)
    db_session.add(client)
    await db_session.flush()
    return client


@pytest.mark.asyncio
async def test_les_notes_d_un_client_se_listent_de_la_plus_ancienne(db_session):
    """L'ordre sert le geste : on solde d'abord la note qu'on relance."""
    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)
    client = await _client_du_referentiel(db_session, org, f"Mwamba {_suffix()}")

    recente = await _devoir(db_session, org, user, nom=client.nom, total=500, paye=0)
    recente.client_id = client.id
    recente.date_encaissement = datetime.now(timezone.utc) - timedelta(days=5)
    ancienne = await _devoir(db_session, org, user, nom=client.nom, total=1000, paye=400)
    ancienne.client_id = client.id
    ancienne.date_encaissement = datetime.now(timezone.utc) - timedelta(days=95)
    await db_session.flush()

    res = await _notes_impayees(db_session, user, client_id=str(client.id))

    assert res["nb_notes"] == 2
    assert res["total_du"] == pytest.approx(1100.0)
    assert res["identite_sure"] is True
    assert [n["id"] for n in res["notes"]] == [str(ancienne.id), str(recente.id)]
    assert res["notes"][0]["reste_du"] == pytest.approx(600.0)
    assert res["notes"][0]["tranche"] == "plus_90"


@pytest.mark.asyncio
async def test_une_note_soldee_ou_une_proforma_ne_se_liste_pas(db_session):
    """Même règle que partout ailleurs : le montant fait foi, pas le statut, et
    un devis n'est pas une dette."""
    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)
    client = await _client_du_referentiel(db_session, org, f"Soldeur {_suffix()}")

    for total, paye, proforma in ((500, 500, False), (300, 0, True)):
        note = await _devoir(
            db_session, org, user, nom=client.nom, total=total, paye=paye, est_proforma=proforma
        )
        note.client_id = client.id
    # Un statut resté en arrière ne doit ni ajouter ni retirer une note.
    due = await _devoir(db_session, org, user, nom=client.nom, total=200, paye=50)
    due.client_id = client.id
    due.statut_paiement = "complet"
    await db_session.flush()

    res = await _notes_impayees(db_session, user, client_id=str(client.id))

    assert res["nb_notes"] == 1
    assert res["notes"][0]["id"] == str(due.id)
    assert res["total_du"] == pytest.approx(150.0)


@pytest.mark.asyncio
async def test_un_client_du_referentiel_n_est_rapproche_que_sur_son_identifiant(db_session):
    """La bannière annonce la dette comptée par identifiant : la liste qui
    prétend la détailler doit compter pareil.

    Une note au même nom mais sans fiche liée appartient peut-être à un
    homonyme : l'ajouter ici ferait deux totaux différents pour le même client,
    au même instant, sur le même écran.
    """
    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)
    client = await _client_du_referentiel(db_session, org, f"Homonyme {_suffix()}")

    liee = await _devoir(db_session, org, user, nom=client.nom, total=400, paye=0)
    liee.client_id = client.id
    await _devoir(db_session, org, user, nom=client.nom, total=900, paye=0)  # saisie libre
    await db_session.flush()

    res = await _notes_impayees(db_session, user, client_id=str(client.id))

    assert [n["id"] for n in res["notes"]] == [str(liee.id)]
    assert res["total_du"] == pytest.approx(400.0)


@pytest.mark.asyncio
async def test_un_payeur_saisi_a_la_main_se_retrouve_sur_son_nom_normalise(db_session):
    """Sans fiche, il reste le nom — et la réserve qui va avec."""
    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)
    nom = f"Alain Luka {_suffix()}"
    await _devoir(db_session, org, user, nom=f"  {nom.upper()}  ", total=600, paye=100)
    await _devoir(db_session, org, user, nom=nom.lower(), total=400, paye=0)
    await db_session.flush()

    res = await _notes_impayees(db_session, user, nom=f"{nom}  ")

    assert res["nb_notes"] == 2
    assert res["total_du"] == pytest.approx(900.0)
    assert res["identite_sure"] is False


@pytest.mark.asyncio
async def test_les_notes_d_un_expert_suivent_son_identifiant(db_session):
    """Un expert doit comme un client, et par un numéro d'ordre unique : ce que
    la caisse a tapé ce jour-là n'entre pas dans le rapprochement."""
    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)
    expert = ExpertComptable(
        id=uuid.uuid4(),
        numero_ordre=f"EC/{_suffix()[:5]}",
        nom_denomination=f"Cabinet {_suffix()}",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.flush()
    for libelle, total, paye in ((f"Cabinet {_suffix()}", 800, 300), (f"CAB. {_suffix()}", 200, 0)):
        note = await _devoir(db_session, org, user, nom=libelle, total=total, paye=paye)
        note.type_client = "expert_comptable"
        note.expert_comptable_id = expert.id
    await db_session.flush()

    res = await _notes_impayees(db_session, user, expert_comptable_id=str(expert.id))

    assert res["nb_notes"] == 2
    assert res["total_du"] == pytest.approx(700.0)
    assert res["identite_sure"] is True


@pytest.mark.asyncio
async def test_sans_payeur_designe_la_liste_refuse_de_repondre(db_session):
    """Une liste de notes sans payeur, ce sont les notes de tout le monde : le
    panneau afficherait la dette d'autrui sous le nom qu'on est en train de
    taper."""
    from fastapi import HTTPException

    org = await _enc_org(db_session, name=f"Notes {_suffix()}")
    user = await _enc_user(db_session, org)

    with pytest.raises(HTTPException) as refus:
        await _notes_impayees(db_session, user)
    assert refus.value.status_code == 400


@pytest.mark.asyncio
async def test_une_note_annulee_n_est_plus_une_creance(db_session):
    """Annulée, la note ne réclame plus rien — même à qui a le droit de la voir.

    Seul l'utilisateur privé des opérations annulées les voyait disparaître :
    celui qui peut les lire les retrouvait parmi les créances, avec un
    « Compléter » menant à un règlement que l'annulation interdit.
    """
    org = await _enc_org(db_session, name=f"Annulee {_suffix()}")
    user = await _enc_user(db_session, org)
    client = await _client_du_referentiel(db_session, org, f"Annule {_suffix()}")
    annulee = await _devoir(db_session, org, user, nom=client.nom, total=3989, paye=0)
    annulee.client_id = client.id
    annulee.statut_operation = "ANNULEE"
    due = await _devoir(db_session, org, user, nom=client.nom, total=200, paye=0)
    due.client_id = client.id
    await db_session.flush()

    notes = await _notes_impayees(db_session, user, client_id=str(client.id))
    assert [n["id"] for n in notes["notes"]] == [str(due.id)]
    assert notes["total_du"] == pytest.approx(200.0)

    debiteurs = await _lister(db_session, user)
    assert debiteurs["total_du"] == pytest.approx(200.0)

    (proposition,) = [p for p in await _proposer(db_session, user, client.nom) if p["valeur"] == client.nom]
    assert proposition["reste_du"] == pytest.approx(200.0)
    assert proposition["nb_impayes"] == 1
