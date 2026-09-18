"""Un libellé d'encaissement peut fixer son prix, son imputation, ou les deux.

Les deux champs sont indépendants : c'est la demande, et c'est ce qui distingue
un tarif d'une simple liste de suggestions. Un tarif qui n'aurait de sens que
complet obligerait à inventer un poste pour figer un prix, ou un prix pour
figer un poste.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.api.v1.endpoints.encaissement_tarifs import (
    create_encaissement_tarif,
    delete_encaissement_tarif,
    list_encaissement_tarifs,
    update_encaissement_tarif,
)
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.encaissement_tarif import EncaissementTarif
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.schemas.encaissement_tarif import EncaissementTarifCreate, EncaissementTarifUpdate
from app.services.encaissement_tarifs import tarifs_resolus


async def _contexte(db, *, annee=2026, code="II.1.1.2", type_poste="RECETTE"):
    org = Organisation(nom="Tarifs", slug=f"tf-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    exercice = BudgetExercice(organisation_id=org.id, annee=annee, statut=StatutBudget.VOTE)
    db.add_all([user, exercice])
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=code, libelle="Cotisations",
        type=type_poste, active=True, montant_prevu=Decimal("100000"), montant_engage=0,
        montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    db.add(PrintSettings(organisation_id=org.id, fiscal_year=annee))
    await db.commit()
    return org, user, exercice, poste


async def _creer(db, org, user, **kwargs):
    payload = EncaissementTarifCreate(**kwargs)
    return await create_encaissement_tarif(payload=payload, user=user, tenant_id=org.id, db=db)


@pytest.mark.asyncio
async def test_un_tarif_peut_ne_fixer_que_le_prix(db_session):
    """Le prix est ferme, l'imputation se décide au cas par cas."""
    org, user, _exercice, _poste = await _contexte(db_session)

    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    assert tarif.montant == Decimal("50")
    assert tarif.budget_poste_code is None
    assert tarif.budget_poste_id is None


@pytest.mark.asyncio
async def test_un_tarif_peut_ne_fixer_que_le_poste(db_session):
    """Le montant varie, mais la recette tombe toujours au même endroit."""
    org, user, _exercice, poste = await _contexte(db_session)

    tarif = await _creer(db_session, org, user, libelle="Arriérés de cotisation", budget_poste_code=poste.code)

    assert tarif.montant is None
    assert tarif.budget_poste_id == poste.id
    assert tarif.budget_poste_libelle == "Cotisations"


@pytest.mark.asyncio
async def test_le_code_se_resout_au_poste_de_l_exercice_courant(db_session):
    """Le tarif suit l'exercice : c'est tout l'intérêt de retenir un code.

    Le même code existe dans deux exercices avec deux identifiants ; le tarif
    doit désigner celui de l'année sur laquelle on travaille.
    """
    org, user, exercice, poste_2026 = await _contexte(db_session)
    exercice_2027 = BudgetExercice(organisation_id=org.id, annee=2027, statut=StatutBudget.VOTE)
    db_session.add(exercice_2027)
    await db_session.flush()
    poste_2027 = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice_2027.id, code=poste_2026.code,
        libelle="Cotisations", type="RECETTE", active=True, montant_prevu=Decimal("120000"),
        montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db_session.add(poste_2027)
    await db_session.commit()

    tarif = await _creer(db_session, org, user, libelle="Cotisation cabinet", montant=Decimal("300"),
                         budget_poste_code=poste_2026.code)
    assert tarif.budget_poste_id == poste_2026.id

    # L'organisation bascule sur l'exercice suivant : le même tarif vise
    # désormais le poste 2027, sans rien ressaisir.
    settings = (
        await db_session.execute(select(PrintSettings).where(PrintSettings.organisation_id == org.id))
    ).scalar_one()
    settings.fiscal_year = 2027
    await db_session.commit()

    resolus = await tarifs_resolus(db_session, org.id)
    assert [poste.id for _tarif, poste in resolus] == [poste_2027.id]


@pytest.mark.asyncio
async def test_un_code_sans_poste_de_recette_ne_vaut_pas_imputation(db_session):
    """Mieux vaut un tarif qui se dit muet qu'un tarif qui impute au hasard."""
    org, user, _exercice, poste = await _contexte(db_session, type_poste="DEPENSE")

    tarif = await _creer(db_session, org, user, libelle="Vente de formulaires", budget_poste_code=poste.code)

    assert tarif.budget_poste_code == poste.code  # le réglage est conservé
    assert tarif.budget_poste_id is None  # mais il ne désigne aucune recette


@pytest.mark.asyncio
async def test_deux_tarifs_ne_partagent_pas_un_libelle(db_session):
    """La saisie reconnaît un tarif par son libellé : deux tarifs homonymes la
    laisseraient sans réponse. La casse et les espaces ne font pas deux."""
    org, user, _exercice, _poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    with pytest.raises(HTTPException) as refus:
        await _creer(db_session, org, user, libelle="  COTISATION   stagiaire ", montant=Decimal("60"))
    assert refus.value.status_code == 409


@pytest.mark.asyncio
async def test_un_champ_se_vide_sans_emporter_l_autre(db_session):
    """Retirer le prix ne doit pas retirer l'imputation, et réciproquement."""
    org, user, _exercice, poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation cabinet",
                         montant=Decimal("300"), budget_poste_code=poste.code)

    sans_prix = await update_encaissement_tarif(
        tarif_id=tarif.id, payload=EncaissementTarifUpdate(montant=None), user=user, tenant_id=org.id, db=db_session
    )
    assert sans_prix.montant is None
    assert sans_prix.budget_poste_id == poste.id

    sans_poste = await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(montant=Decimal("320"), budget_poste_code=None),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    assert sans_poste.montant == Decimal("320")
    assert sans_poste.budget_poste_code is None


@pytest.mark.asyncio
async def test_la_liste_garde_l_ordre_regle_a_la_main(db_session):
    """L'administrateur classait déjà sa pré-liste : l'ordre est un réglage."""
    org, user, _exercice, _poste = await _contexte(db_session)
    premier = await _creer(db_session, org, user, libelle="Cotisation cabinet")
    second = await _creer(db_session, org, user, libelle="Cotisation salarié")

    await update_encaissement_tarif(
        tarif_id=second.id, payload=EncaissementTarifUpdate(position=0), user=user, tenant_id=org.id, db=db_session
    )

    liste = await list_encaissement_tarifs(actifs=False, archives=False, _user=user, tenant_id=org.id, db=db_session)
    assert [t.libelle for t in liste] == ["Cotisation salarié", "Cotisation cabinet"]

    await delete_encaissement_tarif(tarif_id=premier.id, user=user, tenant_id=org.id, db=db_session)
    reste = await list_encaissement_tarifs(actifs=False, archives=False, _user=user, tenant_id=org.id, db=db_session)
    assert [t.libelle for t in reste] == ["Cotisation salarié"]


@pytest.mark.asyncio
async def test_un_tarif_inactif_ne_se_propose_plus(db_session):
    """Cesser de proposer un tarif n'est pas l'effacer : l'an prochain il resservira."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation 2025", montant=Decimal("40"))
    await update_encaissement_tarif(
        tarif_id=tarif.id, payload=EncaissementTarifUpdate(is_active=False), user=user, tenant_id=org.id, db=db_session
    )

    assert await list_encaissement_tarifs(actifs=True, archives=False, _user=user, tenant_id=org.id, db=db_session) == []
    assert len(await list_encaissement_tarifs(actifs=False, archives=False, _user=user, tenant_id=org.id, db=db_session)) == 1


# ---------------------------------------------------------------------------
# Le verrou vit au serveur, pas dans l'écran
# ---------------------------------------------------------------------------


async def _articles(db, org, *, libelle, prix, quantite=1, poste_id=None, forcer=False, le_jour=None):
    """Passe des articles par la règle des tarifs, comme le fait la création."""
    from app.services.encaissement_tarifs import appliquer_tarifs

    articles = [
        {
            "libelle": libelle,
            "description": None,
            "quantite": Decimal(str(quantite)),
            "prix_unitaire": Decimal(str(prix)),
            "montant": Decimal(str(prix)) * Decimal(str(quantite)),
            "budget_poste_id": poste_id,
            "sort_order": 0,
        }
    ]
    ecarts = await appliquer_tarifs(
        db, org.id, articles, peut_forcer=forcer, date_encaissement=le_jour
    )
    return articles[0], ecarts


@pytest.mark.asyncio
async def test_le_tarif_impose_son_poste_a_une_ligne_muette(db_session):
    org, user, _exercice, poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation cabinet",
                 montant=Decimal("300"), budget_poste_code=poste.code)

    article, ecarts = await _articles(db_session, org, libelle="cotisation   CABINET", prix="300")

    assert article["budget_poste_id"] == poste.id  # reconnu malgré casse et espaces
    assert ecarts == []


@pytest.mark.asyncio
async def test_un_montant_hors_tarif_est_refuse_sans_le_droit_de_forcer(db_session):
    """Sans ce refus côté serveur, contourner l'écran suffirait à contourner
    le tarif, et deux encaissements du même libellé se remettraient à différer."""
    org, user, _exercice, _poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    with pytest.raises(HTTPException) as refus:
        await _articles(db_session, org, libelle="Cotisation stagiaire", prix="40")
    assert refus.value.status_code == 400
    assert "tarifé à 50" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_forcer_un_montant_est_permis_et_rendu_a_l_appelant(db_session):
    """Un tarif mal réglé ne doit pas bloquer une recette réelle ; l'écart se
    consigne au lieu de se perdre."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    article, ecarts = await _articles(db_session, org, libelle="Cotisation stagiaire", prix="40", forcer=True)

    assert article["prix_unitaire"] == Decimal("40")
    assert ecarts == [
        {
            "libelle": "Cotisation stagiaire",
            "tarif_id": tarif.id,
            "champ": "prix_unitaire",
            "tarif": "50.00",
            "saisi": "40",
        }
    ]


@pytest.mark.asyncio
async def test_le_prix_est_ferme_mais_la_quantite_reste_libre(db_session):
    """Trois cotisations d'un coup : 3 × 50. Figer le total l'interdirait."""
    org, user, _exercice, _poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    article, ecarts = await _articles(db_session, org, libelle="Cotisation stagiaire", prix="50", quantite=3)

    assert (article["quantite"], article["montant"]) == (Decimal("3"), Decimal("150"))
    assert ecarts == []


@pytest.mark.asyncio
async def test_une_remise_glissee_dans_le_total_est_refusee(db_session):
    """Le prix tarifé accompagné d'un total réduit serait une remise que
    personne n'a décidée."""
    org, user, _exercice, _poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    from app.services.encaissement_tarifs import appliquer_tarifs

    articles = [{
        "libelle": "Cotisation stagiaire", "description": None, "quantite": Decimal("2"),
        "prix_unitaire": Decimal("50"), "montant": Decimal("60"), "budget_poste_id": None, "sort_order": 0,
    }]
    with pytest.raises(HTTPException) as refus:
        await appliquer_tarifs(db_session, org.id, articles, peut_forcer=False)
    assert "vaut 100" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_un_tarif_sans_montant_laisse_le_prix_libre(db_session):
    """Poste seul : l'imputation est ferme, le montant varie — c'est le cas des
    arriérés, dont personne ne connaît le montant d'avance."""
    org, user, _exercice, poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Arriérés de cotisation", budget_poste_code=poste.code)

    article, ecarts = await _articles(db_session, org, libelle="Arriérés de cotisation", prix="137.50")

    assert article["prix_unitaire"] == Decimal("137.50")
    assert article["budget_poste_id"] == poste.id
    assert ecarts == []


@pytest.mark.asyncio
async def test_un_tarif_inactif_ne_verrouille_plus_rien(db_session):
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation 2025", montant=Decimal("40"))
    await update_encaissement_tarif(
        tarif_id=tarif.id, payload=EncaissementTarifUpdate(is_active=False), user=user, tenant_id=org.id, db=db_session
    )

    article, ecarts = await _articles(db_session, org, libelle="Cotisation 2025", prix="55")

    assert article["prix_unitaire"] == Decimal("55")
    assert ecarts == []


# ---------------------------------------------------------------------------
# Un tarif qui a servi ne se modifie ni ne s'efface : il se clôt et se rouvre
# ---------------------------------------------------------------------------


async def _faire_servir(db, org, user, tarif_id: int, poste=None) -> Encaissement:
    """Un encaissement passé sous ce tarif. C'est ce qui donne au tarif une
    histoire, et lui interdit désormais de disparaître sans laisser de trace."""
    enc = Encaissement(
        numero_recu=f"ND-{uuid.uuid4().hex[:6]}",
        est_proforma=False,
        organisation_id=org.id,
        type_client="personne_physique",
        client_nom="Client tarifé",
        libelle="Encaissement tarifé",
        montant=Decimal("50"),
        montant_total=Decimal("50"),
        montant_paye=Decimal("50"),
        montant_percu=Decimal("50"),
        devise_perception="USD",
        taux_change_applique=Decimal("1"),
        canal="CAISSE",
        budget_poste_id=poste.id if poste else None,
        statut_paiement="complet",
        mode_paiement="cash",
        date_encaissement=datetime(2026, 9, 1, tzinfo=timezone.utc),
        date_paiement=datetime(2026, 9, 1, tzinfo=timezone.utc),
        created_by=user.id,
    )
    db.add(enc)
    await db.flush()
    db.add(
        EncaissementArticle(
            organisation_id=org.id,
            encaissement_id=enc.id,
            libelle="Cotisation stagiaire",
            quantite=Decimal("1"),
            prix_unitaire=Decimal("50"),
            montant=Decimal("50"),
            budget_poste_id=poste.id if poste else None,
            tarif_id=tarif_id,
            sort_order=0,
        )
    )
    await db.commit()
    return enc


@pytest.mark.asyncio
async def test_un_tarif_jamais_employe_s_efface_franchement(db_session):
    """Rien à préserver : le garder n'encombrerait la relecture que d'une
    version qui n'a jamais rien tarifé."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Erreur de frappe", montant=Decimal("10"))

    await delete_encaissement_tarif(tarif_id=tarif.id, user=user, tenant_id=org.id, db=db_session)

    reste = (
        await db_session.execute(
            select(EncaissementTarif).where(EncaissementTarif.organisation_id == org.id)
        )
    ).scalars().all()
    assert reste == []


@pytest.mark.asyncio
async def test_un_tarif_qui_a_servi_se_clot_au_lieu_de_disparaitre(db_session):
    """Le montant du reçu ne bougeait déjà pas. Ce qui disparaissait, c'était la
    DÉFINITION : plus moyen de dire à quel prix réglé il était sorti."""
    org, user, _exercice, poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire",
                         montant=Decimal("50"), budget_poste_code=poste.code)
    await _faire_servir(db_session, org, user, tarif.id, poste)

    await delete_encaissement_tarif(tarif_id=tarif.id, user=user, tenant_id=org.id, db=db_session)

    close = (
        await db_session.execute(select(EncaissementTarif).where(EncaissementTarif.id == tarif.id))
    ).scalar_one()
    assert close.effet_au is not None
    assert close.libelle == "Cotisation stagiaire"
    assert close.montant == Decimal("50")
    # Elle ne figure plus au catalogue, mais elle se relit.
    vivants = await list_encaissement_tarifs(
        actifs=False, archives=False, _user=user, tenant_id=org.id, db=db_session
    )
    assert vivants == []
    avec_histoire = await list_encaissement_tarifs(
        actifs=False, archives=True, _user=user, tenant_id=org.id, db=db_session
    )
    assert [t.id for t in avec_histoire] == [tarif.id]


@pytest.mark.asyncio
async def test_changer_le_prix_d_un_tarif_employe_ouvre_une_version(db_session):
    """L'ancien prix reste lisible : c'est lui que portait le reçu d'hier."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    await _faire_servir(db_session, org, user, tarif.id)

    nouvelle = await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(montant=Decimal("80")),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    assert nouvelle.id != tarif.id
    assert nouvelle.montant == Decimal("80")
    assert nouvelle.remplace_id == tarif.id
    ancienne = (
        await db_session.execute(select(EncaissementTarif).where(EncaissementTarif.id == tarif.id))
    ).scalar_one()
    assert ancienne.montant == Decimal("50")
    assert ancienne.effet_au is not None


@pytest.mark.asyncio
async def test_reordonner_un_tarif_employe_ne_cree_pas_de_version(db_session):
    """`position` règle ce que la caisse se voit proposer, non ce qu'un
    encaissement devait. Le verser dans l'histoire la noierait dans son bruit."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    await _faire_servir(db_session, org, user, tarif.id)

    meme = await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(position=3, is_active=False),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    assert meme.id == tarif.id
    assert meme.position == 3
    assert meme.is_active is False
    total = (
        await db_session.execute(
            select(func.count()).select_from(EncaissementTarif).where(
                EncaissementTarif.organisation_id == org.id
            )
        )
    ).scalar_one()
    assert total == 1


@pytest.mark.asyncio
async def test_renommer_ne_rend_pas_l_ancien_libelle_libre(db_session):
    """Le libellé est la CLÉ d'application. Le renommer libérerait l'ancien nom :
    le caissier qui le retape ne serait plus verrouillé du tout, et rien ne le
    signalerait. Le verrou se retournerait en son contraire, en silence."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    await _faire_servir(db_session, org, user, tarif.id)

    await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(libelle="Cotisation stagiaire 2027"),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    with pytest.raises(HTTPException) as refus:
        await _articles(db_session, org, libelle="Cotisation stagiaire", prix="12")
    assert refus.value.status_code == 400
    assert "Cotisation stagiaire 2027" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_un_tarif_retire_rend_bien_son_libelle_libre(db_session):
    """Retirer, ce n'est pas renommer : l'administrateur a voulu que ce libellé
    redevienne libre, et le refuser le contredirait."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    await _faire_servir(db_session, org, user, tarif.id)
    await delete_encaissement_tarif(tarif_id=tarif.id, user=user, tenant_id=org.id, db=db_session)

    article, ecarts = await _articles(db_session, org, libelle="Cotisation stagiaire", prix="12")

    assert article["prix_unitaire"] == Decimal("12")
    assert ecarts == []


@pytest.mark.asyncio
async def test_un_encaissement_antidate_prend_le_tarif_de_sa_date(db_session):
    """Sans cela, un changement de prix réécrirait le passé au moment même où
    l'on tente de le rattraper."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))
    await _faire_servir(db_session, org, user, tarif.id)
    # Le tarif court depuis un mois : c'est cette version que le reçu d'hier
    # portait, et c'est elle qu'il doit retrouver.
    await db_session.execute(
        update(EncaissementTarif)
        .where(EncaissementTarif.id == tarif.id)
        .values(effet_du=date.today() - timedelta(days=30))
    )
    await db_session.commit()
    await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(montant=Decimal("80")),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    hier = date.today() - timedelta(days=1)
    ancien, ecarts = await _articles(
        db_session, org, libelle="Cotisation stagiaire", prix="50", le_jour=hier
    )
    assert ancien["tarif_id"] == tarif.id
    assert ecarts == []

    # Aujourd'hui, c'est l'autre prix qui vaut.
    with pytest.raises(HTTPException) as refus:
        await _articles(db_session, org, libelle="Cotisation stagiaire", prix="50")
    assert "tarifé à 80" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_la_ligne_garde_le_tarif_et_dit_si_le_prix_fut_force(db_session):
    """Le libellé et le montant restent la photo qui fait foi ; ce lien dit en
    plus sous quelle définition réglée la ligne est passée."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    conforme, _ = await _articles(db_session, org, libelle="Cotisation stagiaire", prix="50")
    assert conforme["tarif_id"] == tarif.id
    assert conforme["tarif_force"] is False

    forcee, ecarts = await _articles(
        db_session, org, libelle="Cotisation stagiaire", prix="35", forcer=True
    )
    assert forcee["tarif_id"] == tarif.id
    assert forcee["tarif_force"] is True
    assert ecarts and ecarts[0]["champ"] == "prix_unitaire"
