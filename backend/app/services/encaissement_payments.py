from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.payment_history import PaymentHistory
from app.modules.comptabilite.services.generation_service import (
    annuler_ecriture_operation,
    generer_ecriture_encaissement,
)
from app.modules.comptabilite.services.integration_mode import get_accounting_integration_mode
from app.services.audit_service import log_action
from app.services.encaissement_repartition import repartir
from app.services.mouvements_budgetaires import (
    cancel_budget_imputations,
    create_budget_imputation,
    encaissement_a_des_imputations,
)


PAYMENT_STATUS_ACTIVE = "ACTIF"
PAYMENT_STATUS_CANCELLED = "ANNULE"
PAYMENT_COMPTA_NON_APPLICABLE = "NON_APPLICABLE"
PAYMENT_COMPTA_PENDING = "EN_ATTENTE"
PAYMENT_COMPTA_RECORDED = "COMPTABILISE"
PAYMENT_DOUBLE_CLICK_WINDOW = timedelta(seconds=10)


def clean_money(value: Decimal | str | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _payment_status_for(encaissement: Encaissement, paid: Decimal) -> str:
    total = clean_money(encaissement.montant_total or 0)
    if paid > total:
        return "avance"
    if paid >= total and total > 0:
        return "complet"
    if paid > 0:
        return "partiel"
    return "non_paye"


async def _lock_encaissement(db: AsyncSession, *, organisation_id: int, encaissement_id: uuid.UUID) -> Encaissement:
    res = await db.execute(
        select(Encaissement)
        .where(
            Encaissement.id == encaissement_id,
            Encaissement.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    encaissement = res.scalar_one_or_none()
    if encaissement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if encaissement.est_proforma:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paiement indisponible pour une pro forma de note de débit",
        )
    if str(getattr(encaissement, "statut_operation", "ACTIVE") or "ACTIVE").upper() == "ANNULEE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Paiement impossible sur un encaissement annulé")
    return encaissement


async def _credit_treasury(
    db: AsyncSession,
    *,
    organisation_id: int,
    canal: str,
    devise: str,
    compte_bancaire_id: int | None,
    montant: Decimal,
) -> None:
    if canal == "CAISSE":
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=organisation_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.organisation_id == organisation_id)
            .limit(1)
            .with_for_update()
        )
        caisse = res.scalar_one_or_none()
        if caisse is None:
            raise HTTPException(status_code=500, detail="Caisse centrale indisponible")
        if not caisse.est_ouverte:
            raise HTTPException(status_code=400, detail="Caisse fermée : ouvrez la caisse avant d'encaisser le paiement.")
        if devise == "USD":
            caisse.solde_usd = clean_money((caisse.solde_usd or 0) + montant)
        else:
            caisse.solde_cdf = clean_money((caisse.solde_cdf or 0) + montant)
        caisse.derniere_maj = datetime.now(timezone.utc)
        return

    if compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")
    res = await db.execute(
        select(CompteBancaire)
        .where(
            CompteBancaire.id == compte_bancaire_id,
            CompteBancaire.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    compte = res.scalar_one_or_none()
    if compte is None or compte.is_active is False:
        raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if (compte.devise or "").upper() != devise:
        raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
    compte.solde_actuel = clean_money((compte.solde_actuel or 0) + montant)


async def _debit_treasury(
    db: AsyncSession,
    *,
    organisation_id: int,
    canal: str,
    devise: str,
    compte_bancaire_id: int | None,
    montant: Decimal,
) -> None:
    if canal == "CAISSE":
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.organisation_id == organisation_id)
            .limit(1)
            .with_for_update()
        )
        caisse = res.scalar_one_or_none()
        if caisse is None:
            raise HTTPException(status_code=400, detail="Caisse centrale indisponible")
        solde = clean_money((caisse.solde_usd if devise == "USD" else caisse.solde_cdf) or 0)
        if montant > solde:
            raise HTTPException(status_code=400, detail="Solde caisse insuffisant pour neutraliser exactement ce paiement.")
        if devise == "USD":
            caisse.solde_usd = solde - montant
        else:
            caisse.solde_cdf = solde - montant
        caisse.derniere_maj = datetime.now(timezone.utc)
        return

    if compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="Compte bancaire manquant pour neutraliser ce paiement")
    res = await db.execute(
        select(CompteBancaire)
        .where(
            CompteBancaire.id == compte_bancaire_id,
            CompteBancaire.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise HTTPException(status_code=400, detail="Compte bancaire introuvable pour neutraliser ce paiement")
    solde = clean_money(compte.solde_actuel or 0)
    if montant > solde:
        raise HTTPException(status_code=400, detail="Solde bancaire insuffisant pour neutraliser exactement ce paiement.")
    compte.solde_actuel = solde - montant


async def _adjust_budget(
    db: AsyncSession,
    *,
    organisation_id: int,
    budget_poste_id: int | None,
    montant: Decimal,
    direction: int,
) -> None:
    if budget_poste_id is None or montant <= 0:
        return
    res = await db.execute(
        select(BudgetPoste)
        .where(
            BudgetPoste.id == budget_poste_id,
            BudgetPoste.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    poste = res.scalar_one_or_none()
    if poste is None:
        raise HTTPException(status_code=400, detail="Poste budgétaire introuvable")
    current = clean_money(poste.montant_paye or 0)
    if direction < 0 and montant > current:
        raise HTTPException(status_code=400, detail="Exécution budgétaire insuffisante pour neutraliser exactement ce paiement.")
    poste.montant_paye = clean_money(current + (montant * direction))


async def _resolve_destination(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement: Encaissement,
    canal: str | None,
    compte_bancaire_id: int | None,
    devise: str,
) -> tuple[str, int | None]:
    """Destination de CE versement : celle demandée, sinon celle de la note.

    Un client qui a versé un acompte en caisse peut solder par virement, et
    l'inverse. Le versement porte donc sa propre destination ; l'en-tête ne sert
    plus que de défaut, pour que les appels d'avant le règlement mixte et le
    versement initial continuent de viser la caisse ou le compte de la note.
    """
    canal_entete = (encaissement.canal or "CAISSE").upper()
    canal_cible = (canal or canal_entete).upper()
    if canal_cible not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")

    compte_cible = compte_bancaire_id
    # Sans compte explicite, on ne reprend celui de la note que si le versement
    # va au même endroit : reprendre un compte bancaire pour un versement en
    # caisse (ou l'inverse) désignerait un compte qui n'a pas reçu l'argent.
    if compte_cible is None and canal_cible == canal_entete:
        compte_cible = encaissement.compte_bancaire_id

    if compte_cible is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == compte_cible,
                CompteBancaire.organisation_id == organisation_id,
            )
        )
        compte = res.scalar_one_or_none()
        if compte is None or compte.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
        type_attendu = "BANK" if canal_cible == "BANQUE" else "CASH"
        if (compte.account_type or "").upper() != type_attendu:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    elif canal_cible == "BANQUE":
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")

    return canal_cible, compte_cible


async def record_encaissement_payment(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
    montant: Decimal,
    mode_paiement: str,
    reference: str | None,
    notes: str | None,
    user_id: uuid.UUID | None,
    canal: str | None = None,
    compte_bancaire_id: int | None = None,
    date_paiement: datetime | None = None,
    ip_address: str | None = None,
    rubrique_produit_defaut: str | None = None,
) -> PaymentHistory:
    encaissement = await _lock_encaissement(db, organisation_id=organisation_id, encaissement_id=encaissement_id)
    montant = clean_money(montant)
    if montant <= 0:
        raise HTTPException(status_code=400, detail="montant invalide")

    devise = (encaissement.devise_perception or "USD").upper()
    canal, compte_bancaire_id = await _resolve_destination(
        db,
        organisation_id=organisation_id,
        encaissement=encaissement,
        canal=canal,
        compte_bancaire_id=compte_bancaire_id,
        devise=devise,
    )

    now = datetime.now(timezone.utc)
    recent_payment_res = await db.execute(
        select(PaymentHistory)
        .where(
            PaymentHistory.organisation_id == organisation_id,
            PaymentHistory.encaissement_id == encaissement.id,
            PaymentHistory.statut == PAYMENT_STATUS_ACTIVE,
        )
        .order_by(PaymentHistory.created_at.desc(), PaymentHistory.id.desc())
        .limit(1)
    )
    recent_payment = recent_payment_res.scalar_one_or_none()
    if recent_payment is not None:
        recent_created_at = recent_payment.created_at
        if recent_created_at.tzinfo is None:
            recent_created_at = recent_created_at.replace(tzinfo=timezone.utc)
        same_double_click_payment = (
            now - recent_created_at <= PAYMENT_DOUBLE_CLICK_WINDOW
            and clean_money(recent_payment.montant) == montant
            and recent_payment.mode_paiement == mode_paiement
            and recent_payment.reference == reference
            and recent_payment.notes == notes
            and recent_payment.created_by == user_id
            # Même montant vers une autre destination : c'est un second
            # versement, pas le rejeu du premier.
            and (recent_payment.canal or "CAISSE").upper() == canal
            and recent_payment.compte_bancaire_id == compte_bancaire_id
        )
        if same_double_click_payment:
            setattr(recent_payment, "_idempotent_replay", True)
            return recent_payment

    remaining = clean_money((encaissement.montant_total or 0) - (encaissement.montant_paye or 0))
    if montant - remaining > Decimal("0.01"):
        raise HTTPException(status_code=400, detail=f"Montant trop élevé. Restant dû: {remaining}")

    payment_date = date_paiement or now
    if payment_date.tzinfo is None:
        payment_date = payment_date.replace(tzinfo=timezone.utc)
    budget_poste_id = encaissement.budget_poste_id
    taux_change = Decimal(str(encaissement.taux_change_applique or 1))
    impact_budgetaire = (
        bool(encaissement.impact_budgetaire)
        if encaissement.impact_budgetaire is not None
        else budget_poste_id is not None
    )

    payment = PaymentHistory(
        organisation_id=organisation_id,
        encaissement_id=encaissement.id,
        montant=montant,
        devise=devise,
        canal=canal,
        compte_bancaire_id=compte_bancaire_id,
        budget_poste_id=budget_poste_id,
        taux_change_applique=taux_change,
        date_paiement=payment_date,
        mode_paiement=mode_paiement,
        reference=reference,
        notes=notes,
        created_by=user_id,
        statut=PAYMENT_STATUS_ACTIVE,
        statut_comptabilisation=PAYMENT_COMPTA_NON_APPLICABLE,
    )
    db.add(payment)
    await db.flush()

    previous_paid = clean_money(encaissement.montant_paye or 0)
    new_paid = clean_money(previous_paid + montant)
    encaissement.montant_paye = new_paid
    encaissement.montant_percu = new_paid
    encaissement.statut_paiement = _payment_status_for(encaissement, new_paid)
    encaissement.date_paiement = payment_date
    # Premier versement d'une note encore vierge : l'en-tête suit la destination
    # réellement utilisée. Sans cela, une note créée impayée — donc en caisse par
    # défaut — puis soldée par virement resterait classée « caisse » dans les
    # listes et les filtres.
    if recent_payment is None and previous_paid == 0:
        encaissement.canal = canal
        encaissement.compte_bancaire_id = compte_bancaire_id

    await _credit_treasury(
        db,
        organisation_id=organisation_id,
        canal=canal,
        devise=devise,
        compte_bancaire_id=compte_bancaire_id,
        montant=montant,
    )
    # Les articles portent chacun leur poste : un versement se répartit entre
    # eux au prorata. Un encaissement mono-poste — le cas courant — donne une
    # seule part, du montant exact du versement.
    articles = (
        await db.execute(
            select(EncaissementArticle.budget_poste_id, EncaissementArticle.montant).where(
                EncaissementArticle.encaissement_id == encaissement.id,
                EncaissementArticle.organisation_id == organisation_id,
            )
        )
    ).all()
    repartition = (
        repartir(
            [(ligne.budget_poste_id, Decimal(str(ligne.montant or 0))) for ligne in articles],
            montant,
            poste_par_defaut=budget_poste_id,
        )
        if impact_budgetaire
        else []
    )
    if impact_budgetaire:
        for poste_id, part in repartition:
            await _adjust_budget(
                db,
                organisation_id=organisation_id,
                budget_poste_id=poste_id,
                montant=part,
                direction=1,
            )
            await create_budget_imputation(
                db,
                organisation_id=organisation_id,
                payment_history_id=payment.id,
                budget_poste_id=poste_id,
                sens="RECETTE_REALISEE",
                montant_mouvement=part,
                devise_mouvement=devise,
                montant_budget=part,
                exchange_rate_snapshot=taux_change,
                created_by=user_id,
            )

    integration_mode = await get_accounting_integration_mode(db, organisation_id)
    if integration_mode == "manual":
        payment.statut_comptabilisation = PAYMENT_COMPTA_PENDING
        payment.message_comptabilisation = "Écriture comptable à saisir manuellement."
        encaissement.statut_comptabilisation = "A_COMPTABILISER_MANUELLEMENT"
        encaissement.message_comptabilisation = payment.message_comptabilisation
    elif integration_mode == "automatic" and impact_budgetaire:
        await generer_ecriture_encaissement(
            db,
            organisation_id=organisation_id,
            encaissement_id=str(encaissement.id),
            date_operation=payment_date.date(),
            montant=montant,
            devise=devise,
            canal=canal,  # type: ignore[arg-type]
            compte_bancaire_id=compte_bancaire_id,
            budget_poste_id=budget_poste_id,
            libelle=encaissement.libelle,
            created_by=user_id,
            type_origine="payment_history",
            objet_origine_id=str(payment.id),
            rubrique_produit_defaut=rubrique_produit_defaut,
            # Une recette répartie porte un produit par poste : l'écriture suit
            # la même répartition que le budget, sinon les deux se contrediraient.
            imputations=repartition if len(repartition) > 1 else None,
        )
        payment.statut_comptabilisation = PAYMENT_COMPTA_RECORDED
        payment.message_comptabilisation = None
        encaissement.statut_comptabilisation = "COMPTABILISEE"
        encaissement.message_comptabilisation = None
    elif integration_mode == "automatic":
        payment.statut_comptabilisation = PAYMENT_COMPTA_PENDING
        payment.message_comptabilisation = "Mouvement sans impact budgétaire: écriture comptable technique à traiter."
        encaissement.statut_comptabilisation = "A_COMPTABILISER_MANUELLEMENT"
        encaissement.message_comptabilisation = payment.message_comptabilisation
    else:
        encaissement.statut_comptabilisation = "NON_COMPTABILISEE"
        encaissement.message_comptabilisation = None

    await log_action(
        db,
        user_id=user_id,
        action="ENCAISSEMENT_PAYMENT_RECORDED",
        target_table="payment_history",
        target_id=str(payment.id),
        new_value={
            "encaissement_id": str(encaissement.id),
            "montant": str(montant),
            "devise": devise,
            "canal": canal,
            "compte_bancaire_id": compte_bancaire_id,
            "budget_poste_id": budget_poste_id,
            "statut_comptabilisation": payment.statut_comptabilisation,
        },
        ip_address=ip_address,
    )
    await db.flush()
    return payment


async def cancel_encaissement_payment(
    db: AsyncSession,
    *,
    organisation_id: int,
    payment_id: uuid.UUID,
    motif_annulation: str,
    user_id: uuid.UUID | None,
    ip_address: str | None = None,
) -> PaymentHistory:
    res = await db.execute(
        select(PaymentHistory)
        .where(
            PaymentHistory.id == payment_id,
            PaymentHistory.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    payment = res.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Paiement non trouvé")
    if payment.statut != PAYMENT_STATUS_ACTIVE:
        raise HTTPException(status_code=400, detail="Ce paiement est déjà annulé")

    encaissement = await _lock_encaissement(db, organisation_id=organisation_id, encaissement_id=payment.encaissement_id)
    montant = clean_money(payment.montant)
    # La destination du versement fait foi. Depuis le règlement mixte elle peut
    # différer de celle de la note — acompte en caisse, solde par virement — et
    # rendre l'argent ailleurs que là où il est entré creuserait un trou dans une
    # trésorerie et un excédent dans l'autre. L'en-tête ne sert plus que de repli
    # pour les lignes sans destination propre.
    canal_entete = (encaissement.canal or "CAISSE").upper()
    canal = (payment.canal or canal_entete).upper()
    devise = (payment.devise or encaissement.devise_perception or "USD").upper()
    compte_bancaire_id = payment.compte_bancaire_id
    if compte_bancaire_id is None and canal == canal_entete:
        compte_bancaire_id = encaissement.compte_bancaire_id
    # Le poste figé sur le paiement fait foi : c'est lui, et lui seul, qui dit ce
    # que CE paiement a imputé.
    budget_poste_id = payment.budget_poste_id
    if budget_poste_id is None and not await encaissement_a_des_imputations(
        db, organisation_id=organisation_id, encaissement_id=encaissement.id
    ):
        # Aucune imputation nulle part : mouvement antérieur au registre, dont la
        # seule trace budgétaire est `poste.montant_paye`. Le poste de
        # l'encaissement est alors la seule source pour la défaire.
        #
        # Ce repli se décide sur le registre, et surtout PAS sur
        # `nature_mouvement`, qui ne peut pas trancher ici : le backfill de la
        # bascule « hors budget » l'a posé à BUDGETAIRE sur tout l'historique, et
        # une régularisation l'y ramène aussi (regularisations_budgetaires.py).
        # Le tester revenait donc à supprimer ce repli pour l'historique —
        # annuler un encaissement ancien laissait son poste crédité d'un montant
        # annulé — et le retirer sans marqueur débitait deux fois un encaissement
        # régularisé, dont l'imputation est déjà reprise par ailleurs.
        budget_poste_id = encaissement.budget_poste_id
    impact_budgetaire = budget_poste_id is not None

    await _debit_treasury(
        db,
        organisation_id=organisation_id,
        canal=canal,
        devise=devise,
        compte_bancaire_id=compte_bancaire_id,
        montant=montant,
    )
    if impact_budgetaire:
        cancelled_persisted = await cancel_budget_imputations(
            db,
            organisation_id=organisation_id,
            payment_history_id=payment.id,
            user_id=user_id,
        )
        if not cancelled_persisted:
            await _adjust_budget(
                db,
                organisation_id=organisation_id,
                budget_poste_id=budget_poste_id,
                montant=montant,
                direction=-1,
            )

    await annuler_ecriture_operation(
        db,
        organisation_id=organisation_id,
        module_origine="encaissements",
        type_origine="payment_history",
        objet_origine_id=str(payment.id),
        motif=motif_annulation,
        user_id=user_id,
    )

    new_paid = clean_money((encaissement.montant_paye or 0) - montant)
    if new_paid < 0:
        raise HTTPException(status_code=400, detail="Montant payé insuffisant pour neutraliser exactement ce paiement.")
    encaissement.montant_paye = new_paid
    encaissement.montant_percu = new_paid
    encaissement.statut_paiement = _payment_status_for(encaissement, new_paid)

    now = datetime.now(timezone.utc)
    payment.statut = PAYMENT_STATUS_CANCELLED
    payment.annule_le = now
    payment.annule_par_id = user_id
    payment.motif_annulation = motif_annulation
    payment.annulation_ip = ip_address

    await log_action(
        db,
        user_id=user_id,
        action="ENCAISSEMENT_PAYMENT_CANCELLED",
        target_table="payment_history",
        target_id=str(payment.id),
        old_value={"statut": PAYMENT_STATUS_ACTIVE},
        new_value={
            "statut": PAYMENT_STATUS_CANCELLED,
            "encaissement_id": str(encaissement.id),
            "montant": str(montant),
            "devise": devise,
            "canal": canal,
            "motif_annulation": motif_annulation,
        },
        ip_address=ip_address,
    )
    await db.flush()
    return payment
