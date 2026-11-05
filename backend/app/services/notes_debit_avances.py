"""Le surplus payé sur une note de débit règle les notes suivantes du membre.

Une note actualisée à la baisse peut se retrouver payée au-delà de son total :
le membre a versé 600 sur une cotisation que la Comptabilité ramène à 450. Ces
150 ne sont pas rendus, ils règlent sa dette suivante : la plus ancienne note
qui a encore un reste dû, puis la suivante, et ainsi de suite. Sans dette, le
surplus attend sur la note et se déduit de la prochaine note émise — celle de
N+1, par exemple, au premier import qui la crée.

Comme l'identification d'une recette à identifier (`recettes_a_identifier`),
le report ne crée pas d'argent : il DÉPLACE une part d'un versement vers un
versement de la note réglée, à la même date de valeur, sur la même caisse ou
le même compte, avec le même mode. La trésorerie n'est pas touchée, et les
états qui se lisent au versement (`encaissement_flux`) ne voient jamais
l'argent deux fois. Le budget, lui, suit l'argent : la part déplacée quitte les
postes de la note d'origine pour ceux de la note réglée.

Le versement créé garde le lien vers celui d'où il vient (`avance_source_id`) :
l'annuler rend l'argent à ce versement d'origine, jamais à la caisse
(`rendre_avance`, appelé par `cancel_encaissement_payment`).

Un report ne se fait pas — et le surplus attend, avec sa raison — quand :
  - la comptabilité est intégrée automatiquement : l'écriture du versement
    d'origine devrait être scindée, ce que le moteur ne sait pas faire ;
  - le versement d'origine est rapproché d'un relevé bancaire : la ligne du
    relevé ne correspondrait plus au versement ;
  - un poste concerné appartient à un exercice clôturé ;
  - les deux notes ne sont pas toutes deux tenues en dollars.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory
from app.modules.comptabilite.services.integration_mode import get_accounting_integration_mode
from app.services.audit_service import log_action
from app.services.encaissement_repartition import repartir
from app.services.mouvements_budgetaires import (
    active_imputations_for_source,
    cancel_budget_imputations,
    create_budget_imputation,
)
from app.services.report_creances import lignes_de_recouvrement, verifier_postes_ouverts

#: En deçà, l'écart est un arrondi, pas une avance.
SEUIL = Decimal("0.01")
ACTIF = "ACTIF"
ANNULE = "ANNULE"
#: Versement entièrement déplacé : ses destinations portent l'argent (même
#: convention que `recettes_a_identifier.VERSEMENT_TRANSFERE`).
TRANSFERE = "TRANSFERE"

MESSAGE_POSTE_CLOS = (
    "L'exercice {annee} est clôturé (poste {poste}) : l'avance ne peut pas être reportée."
)


def _money(valeur: Any) -> Decimal:
    return Decimal(str(valeur or 0)).quantize(Decimal("0.01"))


def _statut_paiement(note: Encaissement) -> str:
    from app.services.encaissement_payments import _payment_status_for

    return _payment_status_for(note, _money(note.montant_paye))


def _surplus(note: Encaissement) -> Decimal:
    return max(_money(note.montant_paye) - _money(note.montant_total), Decimal("0.00"))


def _reste(note: Encaissement) -> Decimal:
    return max(_money(note.montant_total) - _money(note.montant_paye), Decimal("0.00"))


def _en_dollars(note: Encaissement) -> bool:
    from app.services.encaissement_payments import facteur_devise

    return (note.devise_perception or "USD").upper() == "USD" and facteur_devise(note) == 1


def _numero(note: Encaissement) -> str:
    return note.numero_note_externe or note.numero_recu or str(note.id)


async def _versement_rapproche(db: AsyncSession, *, organisation_id: int, versement: PaymentHistory) -> bool:
    from app.modules.comptabilite.models import ComptaReleveBancaireLigne

    if (versement.canal or "").upper() != "BANQUE":
        return False
    trouve = (
        await db.execute(
            select(ComptaReleveBancaireLigne.id)
            .where(
                ComptaReleveBancaireLigne.organisation_id == organisation_id,
                ComptaReleveBancaireLigne.operation_type == "VERSEMENT",
                ComptaReleveBancaireLigne.operation_id == str(versement.id),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return trouve is not None


async def _imputer(
    db: AsyncSession,
    *,
    organisation_id: int,
    versement: PaymentHistory,
    parts: list[tuple[int, Decimal]],
    user_id: uuid.UUID | None,
) -> None:
    from app.services.encaissement_payments import _adjust_budget

    for poste_id, part in parts:
        await _adjust_budget(db, organisation_id=organisation_id, budget_poste_id=poste_id, montant=part, direction=1)
        await create_budget_imputation(
            db,
            organisation_id=organisation_id,
            payment_history_id=versement.id,
            budget_poste_id=poste_id,
            sens="RECETTE_REALISEE",
            montant_mouvement=part,
            devise_mouvement=versement.devise or "USD",
            montant_budget=part,
            exchange_rate_snapshot=versement.taux_change_applique,
            created_by=user_id,
        )


async def _reimputer_versement(
    db: AsyncSession,
    *,
    organisation_id: int,
    versement: PaymentHistory,
    nouveau_montant: Decimal,
    poids_par_defaut: tuple[list[tuple[int | None, Decimal]], int | None] | None,
    user_id: uuid.UUID | None,
) -> None:
    """Ramène l'imputation budgétaire d'un versement à `nouveau_montant`.

    Les imputations en place sont reprises, puis le nouveau montant est réparti
    dans leurs proportions — à défaut, dans celles de `poids_par_defaut` (les
    lignes de la note). Le registre garde les deux états : les anciennes
    imputations passent ANNULEE, les nouvelles naissent ACTIVE.
    """
    anciennes = await active_imputations_for_source(
        db, organisation_id=organisation_id, payment_history_id=versement.id
    )
    poids: list[tuple[int | None, Decimal]] = [(i.budget_poste_id, _money(i.montant_budget)) for i in anciennes]
    defaut: int | None = None
    if not poids and poids_par_defaut is not None:
        poids, defaut = poids_par_defaut
    await verifier_postes_ouverts(
        db,
        organisation_id=organisation_id,
        poste_ids={p for p, _ in poids if p is not None} | ({defaut} if defaut else set()),
        message=MESSAGE_POSTE_CLOS,
    )
    if anciennes:
        await cancel_budget_imputations(
            db, organisation_id=organisation_id, payment_history_id=versement.id, user_id=user_id
        )
    if nouveau_montant > 0:
        await _imputer(
            db,
            organisation_id=organisation_id,
            versement=versement,
            parts=repartir(poids, nouveau_montant, poste_par_defaut=defaut),
            user_id=user_id,
        )


async def _deplacer(
    db: AsyncSession,
    *,
    organisation_id: int,
    source: Encaissement,
    versement: PaymentHistory,
    cible: Encaissement,
    montant: Decimal,
    mode_compta: str,
    user_id: uuid.UUID | None,
) -> PaymentHistory:
    """Déplace `montant` du versement `versement` (note `source`) vers la note `cible`."""
    lignes, defaut = await lignes_de_recouvrement(db, organisation_id=organisation_id, encaissement=cible)
    repartition = repartir(lignes, montant, poste_par_defaut=defaut)
    await verifier_postes_ouverts(
        db,
        organisation_id=organisation_id,
        poste_ids={p for p, _ in repartition},
        message=MESSAGE_POSTE_CLOS,
    )

    # Le versement d'origine ne porte plus que ce qui reste à sa note.
    reste_versement = _money(_money(versement.montant) - montant)
    await _reimputer_versement(
        db,
        organisation_id=organisation_id,
        versement=versement,
        nouveau_montant=reste_versement,
        poids_par_defaut=None,
        user_id=user_id,
    )
    if reste_versement <= 0:
        versement.statut = TRANSFERE
    else:
        versement.montant = reste_versement
    source.montant_paye = _money(_money(source.montant_paye) - montant)
    source.montant_percu = source.montant_paye
    source.statut_paiement = _statut_paiement(source)

    destination = PaymentHistory(
        organisation_id=organisation_id,
        encaissement_id=cible.id,
        montant=montant,
        devise=versement.devise or "USD",
        canal=versement.canal,
        compte_bancaire_id=versement.compte_bancaire_id,
        budget_poste_id=max(repartition, key=lambda item: item[1])[0] if repartition else cible.budget_poste_id,
        taux_change_applique=versement.taux_change_applique or Decimal("1"),
        date_paiement=versement.date_paiement,
        mode_paiement=versement.mode_paiement,
        reference=versement.reference,
        notes=f"Avance reportée depuis la note {_numero(source)}",
        created_by=user_id,
        statut=ACTIF,
        statut_comptabilisation="NON_APPLICABLE",
        avance_source_id=versement.id,
    )
    if mode_compta == "manual":
        destination.statut_comptabilisation = "EN_ATTENTE"
        destination.message_comptabilisation = (
            f"Avance reportée depuis la note {_numero(source)} : reclassement de produit à saisir, "
            "sans mouvement de trésorerie."
        )
        cible.statut_comptabilisation = "A_COMPTABILISER_MANUELLEMENT"
        cible.message_comptabilisation = destination.message_comptabilisation
    db.add(destination)
    await db.flush()
    await _imputer(db, organisation_id=organisation_id, versement=destination, parts=repartition, user_id=user_id)

    cible.montant_paye = _money(_money(cible.montant_paye) + montant)
    cible.montant_percu = cible.montant_paye
    cible.statut_paiement = _statut_paiement(cible)
    if cible.date_paiement is None:
        cible.date_paiement = versement.date_paiement

    await log_action(
        db,
        user_id=user_id,
        action="NOTE_DEBIT_AVANCE_REPORTEE",
        target_table="payment_history",
        target_id=str(destination.id),
        new_value={
            "montant": str(montant),
            "note_source": str(source.id),
            "note_cible": str(cible.id),
            "versement_source": str(versement.id),
        },
    )
    return destination


async def reporter_avances_membre(
    db: AsyncSession,
    *,
    organisation_id: int,
    expert_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Reporte tout surplus des notes du membre sur ses dettes, la plus ancienne d'abord.

    Rend ce qui a été reporté (`reportes`) et ce qui attend, avec sa raison
    (`en_attente`). N'écrit rien de plus que les reports ; l'appelant valide.
    """
    notes = list(
        (
            await db.execute(
                select(Encaissement)
                .where(
                    Encaissement.organisation_id == organisation_id,
                    Encaissement.expert_comptable_id == expert_id,
                    Encaissement.is_deleted.is_(False),
                    Encaissement.est_proforma.is_(False),
                    func.coalesce(Encaissement.statut_operation, "ACTIVE") != "ANNULEE",
                    Encaissement.type_client.in_(("expert_comptable", "sec")),
                )
                .order_by(
                    func.coalesce(Encaissement.exercice, extract("year", Encaissement.date_encaissement)),
                    Encaissement.date_encaissement,
                    Encaissement.numero_recu,
                )
                .with_for_update()
            )
        ).scalars().all()
    )
    sources = [n for n in notes if _surplus(n) > SEUIL]
    resultat: dict[str, Any] = {"reportes": [], "en_attente": []}
    if not sources:
        return resultat

    def attendre(note: Encaissement, raison: str) -> None:
        resultat["en_attente"].append(
            {"note_id": str(note.id), "numero": _numero(note), "montant": str(_surplus(note)), "raison": raison}
        )

    mode_compta = await get_accounting_integration_mode(db, organisation_id)
    if mode_compta == "automatic":
        for source in sources:
            attendre(source, "comptabilité automatique : le report se saisit à la main")
        return resultat

    for source in sources:
        if not _en_dollars(source):
            attendre(source, "note tenue en francs")
            continue
        cibles = [n for n in notes if n.id != source.id and _reste(n) > SEUIL and _en_dollars(n)]
        versements = list(
            (
                await db.execute(
                    select(PaymentHistory)
                    .where(
                        PaymentHistory.organisation_id == organisation_id,
                        PaymentHistory.encaissement_id == source.id,
                        PaymentHistory.statut == ACTIF,
                    )
                    .order_by(PaymentHistory.date_paiement.desc(), PaymentHistory.created_at.desc())
                    .with_for_update()
                )
            ).scalars().all()
        )
        raison: str | None = None
        for cible in cibles:
            a_reporter = min(_surplus(source), _reste(cible))
            while a_reporter > SEUIL and versements:
                versement = versements[0]
                if await _versement_rapproche(db, organisation_id=organisation_id, versement=versement):
                    versements.pop(0)
                    raison = "versement rapproché d'un relevé bancaire"
                    continue
                part = min(a_reporter, _money(versement.montant))
                try:
                    # Un point de sauvegarde : un poste clôturé refuse ce
                    # report-ci sans défaire ceux qui ont déjà réussi.
                    async with db.begin_nested():
                        await _deplacer(
                            db,
                            organisation_id=organisation_id,
                            source=source,
                            versement=versement,
                            cible=cible,
                            montant=part,
                            mode_compta=mode_compta,
                            user_id=user_id,
                        )
                except HTTPException as exc:
                    raison = str(exc.detail)
                    await db.refresh(source)
                    await db.refresh(cible)
                    await db.refresh(versement)
                    break
                resultat["reportes"].append(
                    {
                        "montant": str(part),
                        "depuis": {"note_id": str(source.id), "numero": _numero(source)},
                        "vers": {"note_id": str(cible.id), "numero": _numero(cible)},
                    }
                )
                a_reporter = _money(a_reporter - part)
                if versement.statut != ACTIF:
                    versements.pop(0)
            if raison is not None or _surplus(source) <= SEUIL or not versements:
                break
        if _surplus(source) > SEUIL:
            attendre(source, raison or "aucune note du membre n'a de reste dû : déduit de sa prochaine note")
    return resultat


async def rendre_avance(
    db: AsyncSession,
    *,
    organisation_id: int,
    versement: PaymentHistory,
    user_id: uuid.UUID | None,
) -> bool:
    """Annulation d'un versement reporté : l'argent retourne au versement d'origine.

    Rend `False` si le versement d'origine n'existe plus comme tel (annulé) :
    l'argent n'a alors plus d'autre place que la trésorerie, et l'appelant
    l'en retire comme un versement ordinaire. L'imputation budgétaire du
    versement annulé est reprise par l'appelant.
    """
    if versement.avance_source_id is None:
        return False
    origine = (
        await db.execute(
            select(PaymentHistory)
            .where(PaymentHistory.id == versement.avance_source_id, PaymentHistory.organisation_id == organisation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if origine is None or origine.statut not in {ACTIF, TRANSFERE}:
        return False
    note = (
        await db.execute(
            select(Encaissement)
            .where(Encaissement.id == origine.encaissement_id, Encaissement.organisation_id == organisation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if note is None or (note.statut_operation or "ACTIVE").upper() == "ANNULEE":
        return False

    montant = _money(versement.montant)
    if origine.statut == TRANSFERE:
        origine.statut = ACTIF
        origine.montant = montant
    else:
        origine.montant = _money(_money(origine.montant) + montant)
    await _reimputer_versement(
        db,
        organisation_id=organisation_id,
        versement=origine,
        nouveau_montant=_money(origine.montant),
        poids_par_defaut=await lignes_de_recouvrement(db, organisation_id=organisation_id, encaissement=note),
        user_id=user_id,
    )
    note.montant_paye = _money(_money(note.montant_paye) + montant)
    note.montant_percu = note.montant_paye
    note.statut_paiement = _statut_paiement(note)
    await log_action(
        db,
        user_id=user_id,
        action="NOTE_DEBIT_AVANCE_RENDUE",
        target_table="payment_history",
        target_id=str(origine.id),
        new_value={"montant": str(montant), "versement_annule": str(versement.id), "note": str(note.id)},
    )
    return True
