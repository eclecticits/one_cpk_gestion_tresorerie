"""PV de clôture : il présente toute la caisse, et son détail additionne ses totaux."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.clotures import construire_pv_cloture, create_cloture, open_caisse
from app.api.v1.endpoints.reports import rapport_cloture
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.cloture_caisse import ClotureCaisse
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.cloture import ClotureCreateRequest, OuvertureCreateRequest


async def _caisse_ouverte(db_session):
    org = Organisation(nom="PV Test", slug=f"pv-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=False, solde_usd=0, solde_cdf=0))
    user = User(
        id=uuid.uuid4(), email=f"pv-{uuid.uuid4().hex[:6]}@example.com",
        prenom="Marie", nom="KALALA", role="admin", organisation_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await open_caisse(
        payload=OuvertureCreateRequest(solde_ouverture_usd=Decimal("0"), solde_ouverture_cdf=Decimal("0")),
        request=None, user=user, db=db_session, tenant_id=org.id,
    )
    return org, user


def _encaissement(org, montant, *, canal="CAISSE", devise="USD", nom="Client A", compte_bancaire_id=None):
    return Encaissement(
        id=uuid.uuid4(), organisation_id=org.id, numero_recu=f"ND-{uuid.uuid4().hex[:6]}",
        libelle="Cotisation", type_client="autre", client_nom=nom,
        montant=montant, montant_total=montant, montant_paye=montant, montant_percu=montant,
        devise_perception=devise, taux_change_applique=Decimal("1"),
        canal=canal, compte_bancaire_id=compte_bancaire_id, mode_paiement="cash",
        statut_paiement="complet", est_proforma=False,
        date_encaissement=datetime.now(timezone.utc),
    )


def _sortie(org, montant, *, canal="CAISSE", devise="USD", type_sortie="depense", beneficiaire="Fournisseur", compte_bancaire_id=None):
    return SortieFonds(
        id=uuid.uuid4(), organisation_id=org.id, type_sortie=type_sortie, statut="VALIDE",
        canal=canal, compte_bancaire_id=compte_bancaire_id, devise=devise, montant_paye=montant, beneficiaire=beneficiaire,
        motif="Achat", mode_paiement="cash", reference_numero=f"PAY-{uuid.uuid4().hex[:6]}",
        date_paiement=datetime.now(timezone.utc),
    )


async def _cloturer(db_session, org, user, *, usd="0", cdf="0"):
    return await create_cloture(
        payload=ClotureCreateRequest(solde_physique_usd=Decimal(usd), solde_physique_cdf=Decimal(cdf)),
        request=None, user=user, db=db_session, tenant_id=org.id,
    )


def _somme(lignes, champ, devise):
    return sum((getattr(l, champ) for l in lignes if l.devise == devise), Decimal("0"))


@pytest.mark.asyncio
async def test_le_pv_detaille_entrees_et_sorties_et_additionne_ses_totaux(db_session):
    org, user = await _caisse_ouverte(db_session)
    maintenant = datetime.now(timezone.utc)
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db_session.add(banque)
    await db_session.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("0"), solde_actuel=Decimal("0"),
        is_active=True, account_type="BANK",
    )
    db_session.add(compte)
    await db_session.flush()
    db_session.add_all([
        _encaissement(org, Decimal("300")),
        _encaissement(org, Decimal("50000"), devise="CDF", nom="Client CDF"),
        # Appro : canal BANQUE, mais bien une entrée de la caisse.
        _sortie(org, Decimal("200"), canal="BANQUE", type_sortie="approvisionnement_caisse", beneficiaire="Caisse", compte_bancaire_id=compte.id),
        _sortie(org, Decimal("120")),
        _sortie(org, Decimal("10000"), devise="CDF"),
        # Hors caisse : ne doivent paraître nulle part.
        _sortie(org, Decimal("999"), canal="BANQUE", beneficiaire="Banque seule", compte_bancaire_id=compte.id),
        _encaissement(org, Decimal("888"), canal="BANQUE", nom="Virement", compte_bancaire_id=compte.id),
    ])
    await db_session.flush()
    origine = _sortie(org, Decimal("80"))
    db_session.add(origine)
    await db_session.flush()
    db_session.add(RetourCaisse(
        organisation_id=org.id, sortie_fonds_id=origine.id, montant=Decimal("15"), devise="USD",
        canal="CAISSE", statut="VALIDE", motif="Reliquat", date_retour=maintenant,
    ))
    db_session.add(TransfertInterne(
        organisation_id=org.id, source_type="CAISSE", destination_type="BANQUE", destination_id=compte.id, devise="USD",
        montant=Decimal("40"), reference=f"TRF-{uuid.uuid4().hex[:6]}", date_transfert=maintenant,
        statut="EXECUTE",
    ))
    await db_session.commit()

    out = await _cloturer(db_session, org, user, usd="275", cdf="40000")
    cloture = await db_session.get(ClotureCaisse, out.id)
    pv = await construire_pv_cloture(db_session, cloture)

    assert pv.caissier_nom == "Marie KALALA"
    # 300 encaissés + 200 d'appro + 15 de retour.
    assert _somme(pv.entrees, "montant", "USD") == cloture.total_entrees_usd == Decimal("515.00")
    assert _somme(pv.entrees, "montant", "CDF") == cloture.total_entrees_cdf == Decimal("50000.00")
    # 120 + 80 de dépenses + 40 de transfert vers la banque.
    assert _somme(pv.details, "montant_paye", "USD") == cloture.total_sorties_usd == Decimal("240.00")
    assert _somme(pv.details, "montant_paye", "CDF") == cloture.total_sorties_cdf == Decimal("10000.00")

    assert {e.nature for e in pv.entrees} == {
        "Encaissement", "Approvisionnement", "Retour en caisse",
    }
    assert "Virement" not in {e.tiers for e in pv.entrees}
    assert "Banque seule" not in {d.beneficiaire for d in pv.details}


@pytest.mark.asyncio
async def test_le_pv_ne_reprend_pas_la_periode_precedente(db_session):
    org, user = await _caisse_ouverte(db_session)
    db_session.add(_encaissement(org, Decimal("100"), nom="Periode 1"))
    await db_session.commit()
    await _cloturer(db_session, org, user, usd="100")

    await open_caisse(
        payload=OuvertureCreateRequest(solde_ouverture_usd=Decimal("100"), solde_ouverture_cdf=Decimal("0")),
        request=None, user=user, db=db_session, tenant_id=org.id,
    )
    db_session.add(_encaissement(org, Decimal("30"), nom="Periode 2"))
    await db_session.commit()
    out = await _cloturer(db_session, org, user, usd="130")

    pv = await construire_pv_cloture(db_session, await db_session.get(ClotureCaisse, out.id))
    assert [e.tiers for e in pv.entrees] == ["Periode 2"]
    assert pv.cloture.solde_initial_usd == Decimal("100.00")


@pytest.mark.asyncio
async def test_le_tableau_de_bord_recoit_le_pv_du_jour_et_rien_sans_cloture(db_session):
    org, user = await _caisse_ouverte(db_session)
    aujourd_hui = datetime.now(timezone.utc).date().isoformat()

    # Des sorties mais pas de clôture : il n'y a pas de PV à signer.
    db_session.add(_sortie(org, Decimal("10")))
    await db_session.commit()
    vide = await rapport_cloture(date_jour=aujourd_hui, user=user, db=db_session, tenant_id=org.id)
    assert vide.pv is None and vide.nombre_clotures == 0

    out = await _cloturer(db_session, org, user, usd="0")
    rapport = await rapport_cloture(date_jour=aujourd_hui, user=user, db=db_session, tenant_id=org.id)
    assert rapport.nombre_clotures == 1
    assert rapport.pv.cloture.id == out.id
    assert rapport.pv.details[0].beneficiaire == "Fournisseur"

    veille = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    autre_jour = await rapport_cloture(date_jour=veille, user=user, db=db_session, tenant_id=org.id)
    assert autre_jour.pv is None


@pytest.mark.asyncio
async def test_une_autre_organisation_ne_figure_pas_au_pv(db_session):
    org, user = await _caisse_ouverte(db_session)
    autre, _ = await _caisse_ouverte(db_session)
    db_session.add(_encaissement(autre, Decimal("777"), nom="Autre tenant"))
    db_session.add(_sortie(autre, Decimal("66"), beneficiaire="Autre tenant"))
    await db_session.commit()
    out = await _cloturer(db_session, org, user)
    pv = await construire_pv_cloture(db_session, await db_session.get(ClotureCaisse, out.id))
    assert pv.entrees == [] and pv.details == []
