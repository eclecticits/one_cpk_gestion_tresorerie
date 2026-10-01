"""Flux de trésorerie des encaissements : la destination se lit au versement.

Un encaissement porte une destination d'en-tête (canal + compte bancaire), mais
c'est chaque versement qui entre réellement en caisse ou en banque : un acompte
peut tomber en caisse et le solde arriver par virement. Sommer `montant_paye`
en filtrant `Encaissement.canal` compte alors tout du même côté et fait diverger
la clôture et le rapprochement du solde réel, que `_credit_treasury` a déjà
crédité versement par versement.

`flux_encaissements()` donne cette vue par versement. Elle replie sur l'en-tête
les encaissements sans aucune ligne de versement active — ceux d'avant
`payment_history`, dont le montant payé ne vit que sur l'encaissement : sans ce
repli, ils disparaîtraient des états.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, null, or_, select, union_all
from sqlalchemy.dialects.postgresql import UUID

from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory


PAYMENT_STATUS_ACTIVE = "ACTIF"


def encaissements_retenus(organisation_id: int):
    """Encaissements qui pèsent en trésorerie : ni pro forma, ni annulés, ni supprimés."""
    return (
        Encaissement.organisation_id == organisation_id,
        Encaissement.est_proforma.is_(False),
        Encaissement.is_deleted.is_(False),
        or_(
            Encaissement.statut_operation.is_(None),
            Encaissement.statut_operation == "ACTIVE",
        ),
    )


def flux_encaissements(organisation_id: int):
    """Sous-requête des entrées d'argent, une ligne par versement encaissé.

    Colonnes : `encaissement_id`, `versement_id` (nul pour un repli d'en-tête),
    `canal`, `compte_bancaire_id`, `devise`, `mode_paiement`, `reference`,
    `montant` (dans la devise de perception) et `date_flux` (la date à laquelle
    l'argent est entré, pas celle de la note).
    """
    versements = (
        select(
            PaymentHistory.encaissement_id.label("encaissement_id"),
            PaymentHistory.id.label("versement_id"),
            PaymentHistory.canal.label("canal"),
            PaymentHistory.compte_bancaire_id.label("compte_bancaire_id"),
            PaymentHistory.devise.label("devise"),
            PaymentHistory.mode_paiement.label("mode_paiement"),
            PaymentHistory.reference.label("reference"),
            PaymentHistory.montant.label("montant"),
            func.coalesce(PaymentHistory.date_paiement, PaymentHistory.created_at).label("date_flux"),
        )
        .join(Encaissement, Encaissement.id == PaymentHistory.encaissement_id)
        .where(
            PaymentHistory.organisation_id == organisation_id,
            PaymentHistory.statut == PAYMENT_STATUS_ACTIVE,
            *encaissements_retenus(organisation_id),
        )
    )

    sans_versement = (
        ~select(PaymentHistory.id)
        .where(
            PaymentHistory.encaissement_id == Encaissement.id,
            PaymentHistory.statut == PAYMENT_STATUS_ACTIVE,
        )
        .exists()
    )

    # Repli : l'en-tête fait foi tant qu'aucun versement ne le détaille. La date
    # reste `date_encaissement`, seule date connue de ces lignes.
    entetes = select(
        Encaissement.id.label("encaissement_id"),
        null().cast(UUID(as_uuid=True)).label("versement_id"),
        func.coalesce(Encaissement.canal, "CAISSE").label("canal"),
        Encaissement.compte_bancaire_id.label("compte_bancaire_id"),
        func.coalesce(Encaissement.devise_perception, "USD").label("devise"),
        Encaissement.mode_paiement.label("mode_paiement"),
        Encaissement.reference.label("reference"),
        case(
            (
                Encaissement.devise_perception == "CDF",
                func.coalesce(Encaissement.montant_percu, 0),
            ),
            else_=func.coalesce(Encaissement.montant_paye, 0),
        ).label("montant"),
        Encaissement.date_encaissement.label("date_flux"),
    ).where(
        *encaissements_retenus(organisation_id),
        sans_versement,
        or_(
            func.coalesce(Encaissement.montant_paye, 0) > 0,
            func.coalesce(Encaissement.montant_percu, 0) > 0,
        ),
    )

    return union_all(versements, entetes).subquery("flux_encaissements")


def versements_numerotes(organisation_id: int):
    """`flux_encaissements()` enrichi du rang de chaque versement dans sa note.

    Colonnes ajoutées : `rang` (1 = premier versement), `nombre` (versements
    actifs de la note) et `cumul` (payé sur la note APRÈS ce versement). La
    numérotation porte sur toute l'histoire de la note : filtrer la période
    AUTOUR de cette sous-requête, jamais dedans, sans quoi un complément
    versé dans la période se verrait numéroté « 1 » et pris pour un acompte.
    """
    flux = flux_encaissements(organisation_id)
    fenetre = {
        "partition_by": flux.c.encaissement_id,
        "order_by": (flux.c.date_flux, flux.c.versement_id),
    }
    return select(
        *flux.c,
        func.row_number().over(**fenetre).label("rang"),
        func.count().over(partition_by=flux.c.encaissement_id).label("nombre"),
        func.sum(flux.c.montant).over(**fenetre).label("cumul"),
    ).subquery("versements_numerotes")


def nature_versement(rang: int, montant_total: Decimal, cumul: Decimal) -> str:
    """Nomme un versement : ce qu'il représente pour la note à sa date.

    Le reste s'apprécie APRÈS ce versement, pas aujourd'hui : un acompte
    complété depuis reste un acompte dans le rapport de son jour.
    """
    solde = Decimal(cumul or 0) >= Decimal(montant_total or 0) - Decimal("0.01")
    if rang <= 1:
        return "Paiement intégral" if solde else "Acompte"
    return "Solde" if solde else "Complément"
