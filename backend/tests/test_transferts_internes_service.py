import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.sortie_fonds import SortieFonds
from app.models.cloture_caisse import ClotureCaisse
from app.models.transfert_interne import (
    STATUT_CONTREPASSE,
    STATUT_EXECUTE,
    TransfertInterne,
)
from app.models.user import User
from app.modules.comptabilite.models import ComptaCompte, ComptaEcriture
from app.schemas.transfert import TransfertInterneCreate
from app.services.transferts_internes_service import contrepasser_transfer, create_transfer
from tests.test_comptabilite_wiring import _activer_comptabilite
from tests.test_treasury_flows import _admin, _banque, _caisse, _org


def _payload(**values):
    base = dict(source_type="CAISSE", destination_type="BANQUE", destination_id=None, montant=Decimal("100"), devise="USD")
    base.update(values)
    return TransfertInterneCreate(**base)


@pytest.mark.asyncio
async def test_caisse_vers_banque_est_neutre_et_idempotent(db_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org, solde=Decimal("25"))
    user = await _admin(db_session, org)
    before = Decimal("525")
    transfer = await create_transfer(db_session, payload=_payload(destination_id=banque.id, idempotency_key="k-1"), tenant_id=org.id, user=user)
    replay = await create_transfer(db_session, payload=_payload(destination_id=banque.id, idempotency_key="k-1"), tenant_id=org.id, user=user)
    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    assert transfer.id == replay.id
    assert caisse.solde_usd == Decimal("400")
    assert banque.solde_actuel == Decimal("125")
    assert caisse.solde_usd + banque.solde_actuel == before


@pytest.mark.asyncio
async def test_banque_vers_caisse_puis_contrepassation_additive(db_session):
    """La correction ajoute une ligne inverse ; elle n'en réécrit aucune."""
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("50"))
    banque = await _banque(db_session, org, solde=Decimal("500"))
    user = await _admin(db_session, org)
    origine = await create_transfer(db_session, payload=_payload(source_type="BANQUE", source_id=banque.id, destination_type="CAISSE", montant=Decimal("100")), tenant_id=org.id, user=user)
    origine_date = origine.date_transfert
    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    assert caisse.solde_usd == Decimal("150")
    assert banque.solde_actuel == Decimal("400")

    inverse = await contrepasser_transfer(
        db_session, transfer_id=origine.id, tenant_id=org.id, user=user,
        motif="Saisie erronée",
    )
    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    await db_session.refresh(origine)

    # Les soldes sont revenus à leur position d'avant le transfert.
    assert (caisse.solde_usd, banque.solde_actuel) == (Decimal("50"), Decimal("500"))
    # L'inverse est une opération à part entière, de sens opposé, datée du jour.
    assert inverse.id != origine.id
    assert inverse.transfert_origine_id == origine.id
    assert inverse.statut == STATUT_EXECUTE
    assert (inverse.source_type, inverse.destination_type) == ("CAISSE", "BANQUE")
    assert inverse.montant == origine.montant
    assert inverse.reference != origine.reference
    assert inverse.date_transfert > origine_date
    # L'original garde son montant, sa date et sa référence ; seul son statut
    # et la trace de la décision ont changé.
    assert origine.statut == STATUT_CONTREPASSE
    assert origine.montant == Decimal("100")
    assert origine.date_transfert == origine_date
    assert origine.motif_contrepassation == "Saisie erronée"
    assert origine.contrepasse_par == user.id
    assert origine.contrepasse_le is not None


@pytest.mark.asyncio
async def test_contrepassation_reste_visible_et_neutre_dans_les_agregats(db_session):
    """L'invariant de lecture : sans filtre de statut, les totaux sont justes.

    C'est exactement ce que calculent `clotures._transf_sum` et
    `reports._sum_transferts`, qui ne filtrent pas sur `statut`.
    """
    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org, solde=Decimal("0"))
    user = await _admin(db_session, org)

    origine = await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("100")), tenant_id=org.id, user=user)
    await contrepasser_transfer(
        db_session, transfer_id=origine.id, tenant_id=org.id, user=user, motif="Erreur de compte",
    )

    async def _somme(colonne, valeur: str) -> Decimal:
        return Decimal(str(await db_session.scalar(
            select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                TransfertInterne.organisation_id == org.id,
                colonne == valeur,
                TransfertInterne.devise == "USD",
            )
        )))

    sorties_caisse = await _somme(TransfertInterne.source_type, "CAISSE")
    entrees_caisse = await _somme(TransfertInterne.destination_type, "CAISSE")
    # Les deux lignes restent comptées et se compensent : impact net nul.
    assert sorties_caisse == Decimal("100")
    assert entrees_caisse == Decimal("100")
    assert entrees_caisse - sorties_caisse == Decimal("0")

    # Les deux lignes sont bien lisibles, l'historique n'a pas été effacé.
    lignes = (await db_session.execute(
        select(TransfertInterne)
        .where(TransfertInterne.organisation_id == org.id)
        .order_by(TransfertInterne.id)
    )).scalars().all()
    assert len(lignes) == 2
    assert [ligne.statut for ligne in lignes] == [STATUT_CONTREPASSE, STATUT_EXECUTE]


@pytest.mark.asyncio
async def test_contrepassation_exige_un_motif_et_ne_se_repete_pas(db_session):
    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    origine = await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("40")), tenant_id=org.id, user=user)
    # Un refus déclenche un rollback, qui expire les objets de la session : les
    # identifiants sont relus depuis des variables, pas depuis les instances.
    tenant_id, origine_id = org.id, origine.id

    with pytest.raises(HTTPException) as sans_motif:
        await contrepasser_transfer(db_session, transfer_id=origine_id, tenant_id=tenant_id, user=user, motif="  ")
    assert sans_motif.value.status_code == 400

    inverse = await contrepasser_transfer(
        db_session, transfer_id=origine_id, tenant_id=tenant_id, user=user, motif="Doublon",
    )
    inverse_id = inverse.id

    # Deuxième contre-passation de l'original : refusée.
    with pytest.raises(HTTPException) as deja:
        await contrepasser_transfer(db_session, transfer_id=origine_id, tenant_id=tenant_id, user=user, motif="Encore")
    assert deja.value.status_code == 409

    # Contre-passer la contre-passation : refusée aussi, ce serait une chaîne.
    with pytest.raises(HTTPException) as chaine:
        await contrepasser_transfer(db_session, transfer_id=inverse_id, tenant_id=tenant_id, user=user, motif="Rechaîner")
    assert chaine.value.status_code == 409

    total = await db_session.scalar(
        select(func.count()).select_from(TransfertInterne).where(TransfertInterne.organisation_id == tenant_id)
    )
    assert total == 2


@pytest.mark.asyncio
async def test_periode_cloturee_refuse_creation_et_contrepassation(db_session):
    """Cohérence transfert / période : rien n'entre dans une période arrêtée."""

    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    # Le transfert d'origine appartient à une période révolue.
    avant_hier = datetime.now(timezone.utc) - timedelta(days=2)
    origine = await create_transfer(
        db_session,
        payload=_payload(destination_id=banque.id, montant=Decimal("30"), date_transfert=avant_hier),
        tenant_id=org.id, user=user,
    )
    tenant_id, origine_id, origine_date = org.id, origine.id, origine.date_transfert
    # Le refus attendu ci-dessous déclenche un rollback qui expire `user` : les
    # appels suivants passent une instance détachée portant le seul id utile.
    user_id = user.id

    # Une clôture validée hier fige la période qui contient ce transfert.
    db_session.add(ClotureCaisse(
        organisation_id=tenant_id,
        reference_numero=f"CLO-{tenant_id}",
        date_cloture=datetime.now(timezone.utc) - timedelta(days=1),
        caissier_id=user.id,
        statut="VALIDEE",
    ))
    await db_session.commit()

    # Un transfert antidaté dans la période close est refusé.
    with pytest.raises(HTTPException) as antidate:
        await create_transfer(
            db_session,
            payload=_payload(destination_id=banque.id, montant=Decimal("10"), date_transfert=origine_date),
            tenant_id=tenant_id, user=user,
        )
    assert antidate.value.status_code == 409

    # La contre-passation, elle, est datée du jour : elle entre dans la période
    # ouverte et reste donc possible sans toucher au document déjà arrêté.
    inverse = await contrepasser_transfer(
        db_session, transfer_id=origine_id, tenant_id=tenant_id, user=User(id=user_id),
        motif="Correction tardive",
    )
    assert inverse.date_transfert > origine_date
    # L'original n'a pas été re-daté : son montant et sa date restent ceux du
    # document déjà arrêté.
    await db_session.refresh(origine)
    assert origine.date_transfert == origine_date
    assert origine.montant == Decimal("30")


@pytest.mark.asyncio
async def test_caisse_fermee_bloque_transfert_et_contrepassation(db_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    origine = await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("50")), tenant_id=org.id, user=user)
    tenant_id, origine_id, bank_id = org.id, origine.id, banque.id

    caisse.est_ouverte = False
    await db_session.commit()

    with pytest.raises(HTTPException) as creation:
        await create_transfer(db_session, payload=_payload(destination_id=bank_id, montant=Decimal("10")), tenant_id=tenant_id, user=user)
    assert creation.value.status_code == 400

    with pytest.raises(HTTPException) as correction:
        await contrepasser_transfer(db_session, transfer_id=origine_id, tenant_id=tenant_id, user=user, motif="Caisse fermée")
    assert correction.value.status_code == 400


@pytest.mark.asyncio
async def test_idempotency_payload_different_et_solde_insuffisant(db_session):
    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("50"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    bank_id = banque.id
    tenant_id = org.id
    await create_transfer(db_session, payload=_payload(destination_id=bank_id, montant=Decimal("20"), idempotency_key="same"), tenant_id=tenant_id, user=user)
    with pytest.raises(HTTPException) as different:
        await create_transfer(db_session, payload=_payload(destination_id=bank_id, montant=Decimal("21"), idempotency_key="same"), tenant_id=tenant_id, user=user)
    assert different.value.status_code == 409
    with pytest.raises(HTTPException) as insufficient:
        await create_transfer(db_session, payload=_payload(destination_id=bank_id, montant=Decimal("100")), tenant_id=tenant_id, user=user)
    assert insufficient.value.status_code == 409


@pytest.mark.asyncio
async def test_cross_tenant_refuse_sans_modifier_les_soldes(db_session):
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    caisse_a = await _caisse(db_session, org_a, usd=Decimal("500"))
    banque_b = await _banque(db_session, org_b, solde=Decimal("10"))
    user_a = await _admin(db_session, org_a)
    caisse_id = caisse_a.id
    bank_id = banque_b.id
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await create_transfer(db_session, payload=_payload(destination_id=bank_id), tenant_id=org_a.id, user=user_a)
    assert exc.value.status_code == 404
    caisse_value = await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse_id))
    bank_value = await db_session.scalar(select(CompteBancaire.solde_actuel).where(CompteBancaire.id == bank_id))
    assert (caisse_value, bank_value) == (Decimal("500"), Decimal("10"))


@pytest.mark.asyncio
async def test_cross_tenant_refuse_aussi_sur_source_banque_connue(db_session):
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    caisse_a = await _caisse(db_session, org_a, usd=Decimal("100"))
    banque_b = await _banque(db_session, org_b, solde=Decimal("500"))
    user_a = await _admin(db_session, org_a)
    caisse_id = caisse_a.id
    banque_id = banque_b.id
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_transfer(
            db_session,
            payload=_payload(source_type="BANQUE", source_id=banque_id, destination_type="CAISSE", montant=Decimal("25")),
            tenant_id=org_a.id,
            user=user_a,
        )

    assert exc.value.status_code == 404
    assert await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse_id)) == Decimal("100")
    assert await db_session.scalar(select(CompteBancaire.solde_actuel).where(CompteBancaire.id == banque_id)) == Decimal("500")


@pytest.mark.asyncio
async def test_contrepassation_refusee_si_source_insuffisante_aujourdhui(db_session):
    """L'argent doit exister aujourd'hui pour repartir aujourd'hui."""
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org, solde=Decimal("0"))
    user = await _admin(db_session, org)
    transfer = await create_transfer(db_session, payload=_payload(destination_id=banque.id), tenant_id=org.id, user=user)
    banque.solde_actuel = Decimal("10")
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await contrepasser_transfer(db_session, transfer_id=transfer.id, tenant_id=org.id, user=user, motif="Trop tard")
    assert exc.value.status_code == 409
    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    await db_session.refresh(transfer)
    assert (caisse.solde_usd, banque.solde_actuel) == (Decimal("400"), Decimal("10"))
    assert transfer.statut == STATUT_EXECUTE


@pytest.mark.asyncio
async def test_contrepassation_rollback_si_erreur_comptable(db_session, monkeypatch):
    """Trésorerie et comptabilité tombent ensemble ou pas du tout."""
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    transfer = await create_transfer(db_session, payload=_payload(destination_id=banque.id), tenant_id=org.id, user=user)
    tenant_id, transfer_id = org.id, transfer.id

    async def accounting_enabled(*args, **kwargs):
        return True

    async def fail_accounting(*args, **kwargs):
        raise RuntimeError("contre-passation comptable impossible")

    monkeypatch.setattr("app.services.transferts_internes_service.is_accounting_automatic", accounting_enabled)
    monkeypatch.setattr("app.services.transferts_internes_service.generer_ecriture_transfert_interne", fail_accounting)

    with pytest.raises(RuntimeError, match="contre-passation comptable impossible"):
        await contrepasser_transfer(db_session, transfer_id=transfer_id, tenant_id=tenant_id, user=user, motif="Test")

    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    await db_session.refresh(transfer)
    assert (caisse.solde_usd, banque.solde_actuel, transfer.statut) == (Decimal("400"), Decimal("100"), STATUT_EXECUTE)
    # Aucune ligne inverse orpheline n'a survécu au rollback.
    inverses = await db_session.scalar(
        select(func.count()).select_from(TransfertInterne).where(
            TransfertInterne.organisation_id == tenant_id,
            TransfertInterne.transfert_origine_id.is_not(None),
        )
    )
    assert inverses == 0


def test_schema_refuse_zero_negatif_et_devise_invalide():
    with pytest.raises(ValueError):
        TransfertInterneCreate(source_type="CAISSE", destination_type="BANQUE", destination_id=1, montant=0)
    with pytest.raises(ValueError):
        TransfertInterneCreate(source_type="CAISSE", destination_type="BANQUE", destination_id=1, montant=-1)
    with pytest.raises(ValueError):
        TransfertInterneCreate(source_type="CAISSE", destination_type="BANQUE", destination_id=1, montant=1, devise="EUR")


@pytest.mark.asyncio
async def test_banque_vers_banque_et_source_destination_identiques(db_session):
    org = await _org(db_session)
    source = await _banque(db_session, org, solde=Decimal("500"))
    destination = await _banque(db_session, org, solde=Decimal("10"))
    user = await _admin(db_session, org)
    transfer = await create_transfer(
        db_session,
        payload=_payload(source_type="BANQUE", source_id=source.id, destination_type="BANQUE", destination_id=destination.id, montant=Decimal("25")),
        tenant_id=org.id,
        user=user,
    )
    await db_session.refresh(source)
    await db_session.refresh(destination)
    assert transfer.reference.startswith("TRF-")
    assert (source.solde_actuel, destination.solde_actuel) == (Decimal("475"), Decimal("35"))
    with pytest.raises(HTTPException) as exc:
        await create_transfer(
            db_session,
            payload=_payload(source_type="BANQUE", source_id=source.id, destination_type="BANQUE", destination_id=source.id, montant=Decimal("1")),
            tenant_id=org.id,
            user=user,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_devise_incompatible_refusee_sans_mouvement(db_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque_cdf = await _banque(db_session, org, solde=Decimal("10"), devise="CDF")
    user = await _admin(db_session, org)
    caisse_id = caisse.id
    banque_id = banque_cdf.id
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_transfer(db_session, payload=_payload(destination_id=banque_id, devise="USD"), tenant_id=org.id, user=user)

    assert exc.value.status_code == 400
    assert await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse_id)) == Decimal("500")
    assert await db_session.scalar(select(CompteBancaire.solde_actuel).where(CompteBancaire.id == banque_id)) == Decimal("10")


@pytest.mark.asyncio
async def test_reference_dediee_unique_par_organisation(db_session):
    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("500"))
    bank_a = await _banque(db_session, org)
    bank_b = await _banque(db_session, org)
    user = await _admin(db_session, org)

    await create_transfer(db_session, payload=_payload(destination_id=bank_a.id, reference="TRF-2026-MANUAL"), tenant_id=org.id, user=user)
    with pytest.raises(HTTPException) as exc:
        await create_transfer(db_session, payload=_payload(destination_id=bank_b.id, reference="TRF-2026-MANUAL"), tenant_id=org.id, user=user)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_deux_transferts_concurrents_sur_la_meme_caisse(db_session, async_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("150"))
    bank_a = await _banque(db_session, org)
    bank_b = await _banque(db_session, org)
    user = await _admin(db_session, org)
    await db_session.commit()
    tenant_id, caisse_id, bank_a_id, bank_b_id, user_id = org.id, caisse.id, bank_a.id, bank_b.id, user.id

    async def run(bank_id: int, key: str):
        async with async_session() as session:
            result = await create_transfer(
                session,
                payload=_payload(destination_id=bank_id, montant=Decimal("100"), idempotency_key=key),
                tenant_id=tenant_id,
                user=User(id=user_id),
            )
            return result.id

    results = await asyncio.gather(run(bank_a_id, "race-a"), run(bank_b_id, "race-b"), return_exceptions=True)
    assert sum(isinstance(item, int) for item in results) == 1, repr(results)
    assert sum(isinstance(item, HTTPException) and item.status_code == 409 for item in results) == 1
    remaining = await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse_id))
    assert remaining == Decimal("50")


@pytest.mark.asyncio
async def test_idempotency_concurrente_ne_cree_qu_un_transfert(db_session, async_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("150"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    await db_session.commit()
    caisse_id, banque_id, tenant_id, user_id = caisse.id, banque.id, org.id, user.id
    tenant_id, bank_id, user_id = org.id, banque.id, user.id

    async def run():
        async with async_session() as session:
            return await create_transfer(
                session,
                payload=_payload(destination_id=bank_id, montant=Decimal("100"), idempotency_key="same-race"),
                tenant_id=tenant_id,
                user=User(id=user_id),
            )

    results = await asyncio.gather(run(), run())
    assert results[0].id == results[1].id
    count = await db_session.scalar(
        select(TransfertInterne).where(
            TransfertInterne.organisation_id == tenant_id,
            TransfertInterne.idempotency_key == "same-race",
        )
    )
    assert count is not None
    rows = (await db_session.execute(
        select(TransfertInterne).where(
            TransfertInterne.organisation_id == tenant_id,
            TransfertInterne.idempotency_key == "same-race",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse.id)) == Decimal("50")


@pytest.mark.asyncio
async def test_erreur_comptable_annule_mouvements_et_transfert(db_session, monkeypatch):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    await db_session.commit()
    caisse_id, banque_id, tenant_id, user_id = caisse.id, banque.id, org.id, user.id

    async def fail_accounting(*args, **kwargs):
        raise RuntimeError("échec comptable simulé")

    monkeypatch.setattr("app.services.transferts_internes_service.generer_ecriture_transfert_interne", fail_accounting)
    async def accounting_enabled(*args, **kwargs):
        return True

    monkeypatch.setattr("app.services.transferts_internes_service.is_accounting_automatic", accounting_enabled)
    with pytest.raises(RuntimeError, match="échec comptable simulé"):
        await create_transfer(
            db_session,
            payload=_payload(destination_id=banque_id, montant=Decimal("100")),
            tenant_id=tenant_id,
            user=User(id=user_id),
        )

    assert await db_session.scalar(select(CaisseCentrale.solde_usd).where(CaisseCentrale.id == caisse_id)) == Decimal("500")
    assert await db_session.scalar(select(CompteBancaire.solde_actuel).where(CompteBancaire.id == banque_id)) == Decimal("0")
    assert (await db_session.execute(select(TransfertInterne).where(TransfertInterne.organisation_id == tenant_id))).scalars().first() is None


@pytest.mark.asyncio
async def test_transfert_ne_cree_aucune_sortie_fonds_ni_impact_budgetaire(db_session):
    org = await _org(db_session)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    depense = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code="DEP-TRF", libelle="Dépense",
        type="DEPENSE", montant_prevu=1000, montant_engage=0, montant_paye=0, active=True,
        is_deleted=False,
    )
    recette = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code="REC-TRF", libelle="Recette",
        type="RECETTE", montant_prevu=1000, montant_engage=0, montant_paye=0, active=True,
        is_deleted=False,
    )
    db_session.add_all([depense, recette])
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    before_sorties = await db_session.scalar(select(func.count()).select_from(SortieFonds).where(SortieFonds.organisation_id == org.id))

    await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("75")), tenant_id=org.id, user=user)

    after_sorties = await db_session.scalar(select(func.count()).select_from(SortieFonds).where(SortieFonds.organisation_id == org.id))
    await db_session.refresh(depense)
    await db_session.refresh(recette)
    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    assert after_sorties == before_sorties
    assert (depense.montant_engage, depense.montant_paye, recette.montant_engage, recette.montant_paye) == (0, 0, 0, 0)
    assert caisse.solde_usd + banque.solde_actuel == Decimal("500")


@pytest.mark.asyncio
async def test_ecriture_comptable_transfert_est_equilibree_et_sans_resultat(db_session):
    org = await _org(db_session)
    caisse = await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    await _activer_comptabilite(db_session, org)

    transfer = await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("125")), tenant_id=org.id, user=user)

    ecriture = await db_session.scalar(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.organisation_id == org.id,
            ComptaEcriture.module_origine == "transferts",
            ComptaEcriture.type_origine == "transfert_interne",
            ComptaEcriture.objet_origine_id == str(transfer.id),
        )
    )
    assert ecriture is not None
    assert sum((line.debit for line in ecriture.lignes), Decimal("0")) == sum((line.credit for line in ecriture.lignes), Decimal("0"))
    comptes = (
        await db_session.execute(
            select(ComptaCompte).where(ComptaCompte.id.in_([line.compte_id for line in ecriture.lignes]))
        )
    ).scalars().all()
    assert {compte.nature for compte in comptes} == {"ACTIF"}
    assert all(not compte.numero.startswith(("6", "7")) for compte in comptes)


@pytest.mark.asyncio
async def test_contrepassation_ecriture_dediee_et_ecriture_origine_intacte(db_session):
    """Cohérence transfert / écriture : une ligne, une écriture, même période.

    La contre-passation ne modifie ni n'annule l'écriture d'origine : elle en
    produit une nouvelle, à son propre identifiant d'objet et à la date du jour,
    exactement comme la ligne de trésorerie qu'elle traduit.
    """
    org = await _org(db_session)
    await _caisse(db_session, org, usd=Decimal("500"))
    banque = await _banque(db_session, org)
    user = await _admin(db_session, org)
    await _activer_comptabilite(db_session, org)

    origine = await create_transfer(db_session, payload=_payload(destination_id=banque.id, montant=Decimal("125")), tenant_id=org.id, user=user)
    inverse = await contrepasser_transfer(
        db_session, transfer_id=origine.id, tenant_id=org.id, user=user, motif="Compte erroné",
    )

    async def _ecriture(objet_id: str):
        return await db_session.scalar(
            select(ComptaEcriture)
            .options(selectinload(ComptaEcriture.lignes))
            .where(
                ComptaEcriture.organisation_id == org.id,
                ComptaEcriture.module_origine == "transferts",
                ComptaEcriture.type_origine == "transfert_interne",
                ComptaEcriture.objet_origine_id == objet_id,
            )
        )

    ecriture_origine = await _ecriture(str(origine.id))
    ecriture_inverse = await _ecriture(str(inverse.id))

    # Deux écritures distinctes, chacune rattachée à sa propre ligne : la clé
    # d'origine reste « l'identifiant de l'objet », sans suffixe synthétique.
    assert ecriture_origine is not None
    assert ecriture_inverse is not None
    assert ecriture_origine.id != ecriture_inverse.id

    # L'écriture d'origine n'a pas été annulée : elle est compensée.
    assert (ecriture_origine.statut or "").upper() != "ANNULEE"
    assert ecriture_origine.motif_annulation is None

    # L'écriture de correction est équilibrée, datée du jour, et de sens opposé.
    debits = sum((ligne.debit for ligne in ecriture_inverse.lignes), Decimal("0"))
    credits = sum((ligne.credit for ligne in ecriture_inverse.lignes), Decimal("0"))
    assert debits == credits
    assert ecriture_inverse.date_ecriture == inverse.date_transfert.date()

    # Un transfert n'est pas une dépense : ni charge ni produit, des deux côtés.
    comptes = (await db_session.execute(
        select(ComptaCompte).where(
            ComptaCompte.id.in_([ligne.compte_id for ligne in ecriture_inverse.lignes])
        )
    )).scalars().all()
    assert {compte.nature for compte in comptes} == {"ACTIF"}
    assert all(not compte.numero.startswith(("6", "7")) for compte in comptes)

    # Le débit de la correction porte sur le compte qui était crédité à
    # l'origine : les deux écritures se neutralisent au bilan.
    debit_origine = {ligne.compte_id for ligne in ecriture_origine.lignes if ligne.debit}
    credit_inverse = {ligne.compte_id for ligne in ecriture_inverse.lignes if ligne.credit}
    assert debit_origine == credit_inverse
