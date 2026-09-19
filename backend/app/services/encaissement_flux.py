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

from sqlalchemy import case, func, or_, select, union_all

from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory


PAYMENT_STATUS_ACTIVE = "ACTIF"


def _encaissements_retenus(organisation_id: int):
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

    Colonnes : `encaissement_id`, `canal`, `compte_bancaire_id`, `devise`,
    `montant` (dans la devise de perception) et `date_flux` (la date à laquelle
    l'argent est entré, pas celle de la note).
    """
    versements = (
        select(
            PaymentHistory.encaissement_id.label("encaissement_id"),
            PaymentHistory.canal.label("canal"),
            PaymentHistory.compte_bancaire_id.label("compte_bancaire_id"),
            PaymentHistory.devise.label("devise"),
            PaymentHistory.montant.label("montant"),
            func.coalesce(PaymentHistory.date_paiement, PaymentHistory.created_at).label("date_flux"),
        )
        .join(Encaissement, Encaissement.id == PaymentHistory.encaissement_id)
        .where(
            PaymentHistory.organisation_id == organisation_id,
            PaymentHistory.statut == PAYMENT_STATUS_ACTIVE,
            *_encaissements_retenus(organisation_id),
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
        func.coalesce(Encaissement.canal, "CAISSE").label("canal"),
        Encaissement.compte_bancaire_id.label("compte_bancaire_id"),
        func.coalesce(Encaissement.devise_perception, "USD").label("devise"),
        case(
            (
                Encaissement.devise_perception == "CDF",
                func.coalesce(Encaissement.montant_percu, 0),
            ),
            else_=func.coalesce(Encaissement.montant_paye, 0),
        ).label("montant"),
        Encaissement.date_encaissement.label("date_flux"),
    ).where(
        *_encaissements_retenus(organisation_id),
        sans_versement,
        or_(
            func.coalesce(Encaissement.montant_paye, 0) > 0,
            func.coalesce(Encaissement.montant_percu, 0) > 0,
        ),
    )

    return union_all(versements, entetes).subquery("flux_encaissements")
