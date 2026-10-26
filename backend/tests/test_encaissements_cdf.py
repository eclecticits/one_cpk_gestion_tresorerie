"""Notes payées en francs : la trésorerie reçoit des francs, la note des dollars.

Une note en francs est libellée en dollars (ses articles, son reste dû, son
budget) mais payée en francs. Ce que ces tests tiennent :
- la caisse ou la banque en francs est créditée des francs reçus, pas de leur
  contre-valeur (280 000 CDF entrent, pas 100) ;
- la note et le budget en reçoivent l'équivalent au taux figé sur la note ;
- un paiement partiel en francs laisse un reste dû ;
- une recette à identifier en francs s'identifie vers une nouvelle note en
  francs, en tout ou en partie, sans recréditer la banque.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.payment_history import PaymentHistory
from app.models.print_settings import PrintSettings
from app.schemas.payment import EncaissementCreate
from tests.test_recettes_a_identifier import (  # noqa: F401 (fixture)
    _FakeRequest,
    _creer,
    _flux_banque,
    _org,
    _poste,
    _saisir,
    _suffix,
    _user,
    sans_notifications,
)

TAUX = Decimal("2800")


async def _contexte(db):
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    db.add(PrintSettings(organisation_id=org.id, exchange_rate=TAUX, exchange_rate_cdf=TAUX))
    banque = CompteBancaire(
        organisation_id=org.id, intitule="Rawbank CDF", numero_compte=f"CDF-{_suffix()}",
        devise="CDF", solde_initial=Decimal("0"), solde_actuel=Decimal("0"), is_active=True, account_type="BANK",
    )
    db.add(banque)
    await db.commit()
    return org, user, poste, banque


def _note_cdf(poste, banque, *, total_usd="100", percu_cdf="280000", source=None, client="Jean Mukendi"):
    return EncaissementCreate(
        type_client="personne_physique", client_sexe="M", client_nom=client,
        libelle="Cotisation annuelle",
        montant=Decimal(total_usd), montant_total=Decimal(total_usd),
        montant_paye=Decimal(percu_cdf) / TAUX, montant_percu=Decimal(percu_cdf),
        devise_perception="CDF", taux_change_applique=TAUX,
        mode_paiement="virement", canal="BANQUE", compte_bancaire_id=banque.id,
        budget_poste_id=poste.id,
        identification_source_id=source,
    )


async def _versements(db, enc_id):
    return (
        await db.execute(
            select(PaymentHistory).where(PaymentHistory.encaissement_id == enc_id, PaymentHistory.statut == "ACTIF")
        )
    ).scalars().all()


async def test_note_en_francs_credite_les_francs_recus(db_session, sans_notifications):
    db = db_session
    org, user, poste, banque = await _contexte(db)

    out = await _creer(db, org, user, _note_cdf(poste, banque))
    enc = await db.get(Encaissement, uuid.UUID(str(out["id"] if isinstance(out, dict) else out.id)))
    await db.refresh(enc)
    await db.refresh(banque)
    await db.refresh(poste)

    assert banque.solde_actuel == Decimal("280000.00"), "la banque reçoit les francs, pas leur contre-valeur"
    assert (enc.montant_total, enc.montant_paye, enc.montant_percu) == (
        Decimal("100.00"), Decimal("100.00"), Decimal("280000.00")
    )
    assert enc.statut_paiement == "complet"
    (versement,) = await _versements(db, enc.id)
    assert (versement.montant, versement.devise) == (Decimal("280000.00"), "CDF")
    assert poste.montant_paye == Decimal("100.00"), "le budget compte en dollars"
    (imputation,) = (
        await db.execute(select(MouvementBudgetImputation).where(MouvementBudgetImputation.payment_history_id == versement.id))
    ).scalars().all()
    assert (imputation.montant_mouvement, imputation.montant_budget) == (Decimal("280000.00"), Decimal("100.00"))
    assert await _flux_banque(db, org, banque) == Decimal("280000.00")


async def test_paiement_partiel_en_francs_puis_complement_et_annulation(db_session, sans_notifications):
    from app.api.v1.endpoints.payments import cancel_payment, create_payment
    from app.schemas.payment import PaymentHistoryCancelPayload, PaymentHistoryCreate

    db = db_session
    org, user, poste, banque = await _contexte(db)

    out = await _creer(db, org, user, _note_cdf(poste, banque, percu_cdf="140000"))
    enc_id = uuid.UUID(str(out["id"] if isinstance(out, dict) else out.id))
    enc = await db.get(Encaissement, enc_id)
    await db.refresh(enc)
    assert (enc.montant_total, enc.montant_paye, enc.statut_paiement) == (Decimal("100.00"), Decimal("50.00"), "partiel")

    complement = await create_payment(
        payload=PaymentHistoryCreate(
            encaissement_id=enc_id, montant=Decimal("50"), montant_devise=Decimal("140000"), mode_paiement="virement",
            # Même montant dans les dix secondes : sans référence propre, la
            # garde anti double clic le prendrait pour le premier versement.
            reference="VIR-COMPLEMENT",
        ),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        tenant_id=org.id,
        user=user,
        db=db,
    )
    await db.refresh(enc)
    await db.refresh(banque)
    assert (enc.montant_paye, enc.statut_paiement) == (Decimal("100.00"), "complet")
    assert banque.solde_actuel == Decimal("280000.00")

    await cancel_payment(
        payment_id=str(complement["id"] if isinstance(complement, dict) else complement.id),
        payload=PaymentHistoryCancelPayload(motif_annulation="Virement rejeté par la banque"),
        request=_FakeRequest(),
        tenant_id=org.id,
        user=user,
        db=db,
    )
    await db.refresh(enc)
    await db.refresh(banque)
    await db.refresh(poste)
    assert (enc.montant_paye, enc.montant_percu) == (Decimal("50.00"), Decimal("140000.00"))
    assert banque.solde_actuel == Decimal("140000.00")
    assert poste.montant_paye == Decimal("50.00")


async def test_recette_en_francs_identifiee_par_une_nouvelle_note(db_session, sans_notifications):
    db = db_session
    org, user, poste, banque = await _contexte(db)
    source_id = await _saisir(db, org, user, banque, "280000")
    await db.refresh(banque)
    assert banque.solde_actuel == Decimal("280000.00")

    # Une partie seulement : 140 000 CDF identifiés sur une note de 50 USD.
    out = await _creer(db, org, user, _note_cdf(poste, banque, total_usd="50", percu_cdf="140000", source=source_id))
    note_id = uuid.UUID(str(out["id"] if isinstance(out, dict) else out.id))
    note = await db.get(Encaissement, note_id)
    source = await db.get(Encaissement, source_id)
    await db.refresh(note)
    await db.refresh(source)
    await db.refresh(banque)

    assert (note.montant_paye, note.statut_paiement) == (Decimal("50.00"), "complet")
    assert source.montant_paye == Decimal("140000.00"), "la recette perd les francs identifiés"
    assert source.hors_budget_status == "PARTIELLEMENT_IDENTIFIE"
    assert banque.solde_actuel == Decimal("280000.00"), "identifier ne recrédite pas la banque"
    assert await _flux_banque(db, org, banque) == Decimal("280000.00"), "l'argent n'est jamais vu deux fois"

    # Le reste, sur une seconde note d'un autre payeur : la recette est soldée.
    await _creer(
        db, org, user, _note_cdf(poste, banque, total_usd="50", percu_cdf="140000", source=source_id, client="Marie Kabila")
    )
    await db.refresh(source)
    assert source.hors_budget_status == "IDENTIFIE"
    assert await _flux_banque(db, org, banque) == Decimal("280000.00")


async def test_recette_en_francs_regle_une_note_en_francs(db_session, sans_notifications):
    from app.api.v1.endpoints.recettes_a_identifier import ReglerNotePayload, pistes, regler_note

    db = db_session
    org, user, poste, banque = await _contexte(db)
    # Note émise impayée : 100 USD dus, soit 280 000 CDF au taux de la note.
    out = await _creer(db, org, user, _note_cdf(poste, banque, percu_cdf="0"))
    note_id = uuid.UUID(str(out["id"] if isinstance(out, dict) else out.id))
    source_id = await _saisir(db, org, user, banque, "280000")

    (piste,) = await pistes(recette_id=str(source_id), q=None, tenant_id=org.id, db=db)
    assert (piste["reste_du"], piste["raison"]) == ("280000.00", "montant"), "le reste dû se lit en francs"

    await regler_note(
        recette_id=str(source_id),
        payload=ReglerNotePayload(encaissement_id=note_id, montant=Decimal("280000")),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    note = await db.get(Encaissement, note_id)
    source = await db.get(Encaissement, source_id)
    await db.refresh(note)
    await db.refresh(source)
    await db.refresh(banque)
    assert (note.montant_paye, note.statut_paiement) == (Decimal("100.00"), "complet")
    assert source.hors_budget_status == "IDENTIFIE"
    assert banque.solde_actuel == Decimal("280000.00")
