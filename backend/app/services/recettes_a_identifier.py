"""Recettes à identifier : l'argent est en banque, le payeur reste à trouver.

Un virement arrive avec un libellé bancaire qui ne dit pas qui a payé, ni pour
quoi. On ne peut ni l'imputer au budget ni délivrer de reçu, mais on ne peut
pas non plus l'ignorer : la banque l'a crédité. Il entre donc tout de suite en
trésorerie, sous la nature `A_IDENTIFIER`, et en comptabilité au crédit du
compte d'attente (rubrique `RECETTE_A_IDENTIFIER`).

L'identifier ne crée pas d'argent : elle DÉPLACE tout ou partie du versement
vers sa vraie destination — une nouvelle recette avec son reçu, ou le
règlement d'une note de débit déjà émise. Le versement d'origine diminue
d'autant, le versement de destination porte la même date de valeur, le même
compte et la même trésorerie. Les états de trésorerie, qui se lisent au
versement (`encaissement_flux`), ne voient donc jamais l'argent deux fois.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.payment_history import PaymentHistory
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.services.audit_service import log_action
from app.services.document_sequences import generate_document_number


NATURE_A_IDENTIFIER = "A_IDENTIFIER"
STATUT_A_IDENTIFIER = "A_IDENTIFIER"
STATUT_PARTIELLEMENT_IDENTIFIE = "PARTIELLEMENT_IDENTIFIE"
STATUT_IDENTIFIE = "IDENTIFIE"
#: Entièrement rendu à qui l'avait versé, sans rien identifier.
STATUT_REMBOURSEE = "REMBOURSEE"

#: Réquisition « remboursement de recette à identifier ». Elle désigne une
#: recette et retient sur elle son montant tant qu'elle n'est pas close.
NATURE_REQUISITION = "RECETTE_A_IDENTIFIER"
STATUTS_REQUISITION_CLOS = ("PAYEE", "REJETEE", "ANNULEE")

VERSEMENT_ACTIF = "ACTIF"
#: Versement d'origine entièrement déplacé vers ses destinations. Il ne pèse
#: plus en trésorerie — ses destinations portent l'argent — mais reste lisible.
VERSEMENT_TRANSFERE = "TRANSFERE"

#: Tolérance d'arrondi : une recette en francs congolais est convertie au taux
#: de sa réception, et le formulaire refait la conversion de son côté.
TOLERANCE = Decimal("0.01")

#: Tranches d'ancienneté du suivi, en jours depuis la date de valeur.
TRANCHES: tuple[tuple[str, int | None], ...] = (
    ("0-30", 30),
    ("31-90", 90),
    ("+90", None),
)


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def est_recette_a_identifier(encaissement: Encaissement) -> bool:
    return (encaissement.nature_mouvement or "").upper() == NATURE_A_IDENTIFIER


def tranche_anciennete(age_jours: int) -> str:
    for libelle, borne in TRANCHES:
        if borne is None or age_jours <= borne:
            return libelle
    return TRANCHES[-1][0]


async def _taux_cdf(db: AsyncSession, organisation_id: int) -> Decimal:
    """Taux du paramétrage, comme à la saisie d'un encaissement en francs."""
    ps = (
        await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1))
    ).scalar_one_or_none()
    taux = _money((ps.exchange_rate_cdf or ps.exchange_rate) if ps else 0)
    if taux <= 0:
        raise HTTPException(status_code=400, detail="Taux de change invalide (paramètres)")
    return taux


async def creer_recette_a_identifier(
    db: AsyncSession,
    *,
    organisation_id: int,
    compte_bancaire_id: int,
    montant: Decimal,
    date_valeur: datetime,
    libelle: str,
    reference: str | None,
    mode_paiement: str,
    user_id: uuid.UUID | None,
    ip_address: str | None = None,
) -> Encaissement:
    """Enregistre un versement reçu en banque dont le payeur est inconnu.

    Banque uniquement : un paiement en espèces a toujours quelqu'un devant le
    guichet, qu'il suffit de nommer.
    """
    # Import local : encaissement_payments importe ce module.
    from app.services.encaissement_payments import record_encaissement_payment

    libelle = " ".join((libelle or "").split())
    if not libelle:
        raise HTTPException(status_code=400, detail="Le libellé bancaire est requis")
    montant_saisi = _money(montant)
    if montant_saisi <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")

    compte = (
        await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == compte_bancaire_id,
                CompteBancaire.organisation_id == organisation_id,
            )
        )
    ).scalar_one_or_none()
    if compte is None or compte.is_active is False or (compte.account_type or "").upper() != "BANK":
        raise HTTPException(status_code=400, detail="Compte bancaire invalide : une recette à identifier arrive en banque")
    devise = (compte.devise or "USD").upper()

    # Tenue dans la devise du compte, comme un versement : c'est ce montant que
    # la banque a crédité, et c'est lui qu'un remboursement — une sortie de
    # fonds, tenue elle aussi dans sa devise — viendra diminuer. Le taux n'est
    # gardé que pour mémoire.
    taux = await _taux_cdf(db, organisation_id) if devise == "CDF" else Decimal("1")
    montant_note = montant_saisi

    if date_valeur.tzinfo is None:
        date_valeur = date_valeur.replace(tzinfo=timezone.utc)
    reference = (reference or "").strip() or None

    # Deux virements du même montant le même jour sont banals ; deux lignes au
    # même libellé ET à la même référence, sur le même compte, sont une double
    # saisie du même relevé.
    if reference:
        debut = date_valeur.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = date_valeur.replace(hour=23, minute=59, second=59, microsecond=999999)
        doublon = (
            await db.execute(
                select(Encaissement.numero_recu).where(
                    Encaissement.organisation_id == organisation_id,
                    Encaissement.nature_mouvement == NATURE_A_IDENTIFIER,
                    Encaissement.is_deleted.is_(False),
                    Encaissement.statut_operation == "ACTIVE",
                    Encaissement.compte_bancaire_id == compte.id,
                    Encaissement.reference == reference,
                    Encaissement.libelle == libelle,
                    Encaissement.date_encaissement >= debut,
                    Encaissement.date_encaissement <= fin,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if doublon is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Ce versement est déjà enregistré ({doublon}) : même compte, même libellé, même référence.",
            )

    recette = Encaissement(
        numero_recu=await generate_document_number(db, doc_type="ATT", tenant_id=organisation_id),
        est_proforma=False,
        organisation_id=organisation_id,
        type_client="autre",
        client_nom=None,
        libelle=libelle,
        montant=montant_note,
        montant_total=montant_note,
        montant_paye=Decimal("0.00"),
        montant_percu=Decimal("0.00"),
        devise_perception=devise,
        taux_change_applique=taux,
        budget_poste_id=None,
        statut_paiement="non_paye",
        mode_paiement=mode_paiement,
        nature_mouvement=NATURE_A_IDENTIFIER,
        impact_budgetaire=False,
        hors_budget_status=STATUT_A_IDENTIFIER,
        reference=reference,
        canal="BANQUE",
        compte_bancaire_id=compte.id,
        date_encaissement=date_valeur,
        created_by=user_id,
    )
    db.add(recette)
    await db.flush()
    await record_encaissement_payment(
        db,
        organisation_id=organisation_id,
        encaissement_id=recette.id,
        montant=montant_note,
        mode_paiement=mode_paiement,
        reference=reference,
        notes=None,
        user_id=user_id,
        canal="BANQUE",
        compte_bancaire_id=compte.id,
        date_paiement=date_valeur,
        ip_address=ip_address,
    )
    return recette


async def verrouiller_recette(
    db: AsyncSession,
    *,
    organisation_id: int,
    source_id: uuid.UUID,
    devise: str,
) -> tuple[Encaissement, PaymentHistory | None, Decimal]:
    """La recette d'origine, son versement et ce qui n'est pas à prendre.

    Le troisième terme est la part déjà rendue ou promise au remboursement :
    elle reste sur la recette mais ne s'identifie plus.
    """
    source = (
        await db.execute(
            select(Encaissement)
            .where(Encaissement.id == source_id, Encaissement.organisation_id == organisation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if source is None or source.is_deleted:
        raise HTTPException(status_code=404, detail="Recette à identifier introuvable")
    if not est_recette_a_identifier(source):
        raise HTTPException(status_code=400, detail="Cet encaissement n'est pas une recette à identifier")
    if (source.statut_operation or "ACTIVE").upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="Cette recette à identifier est annulée")
    if (source.devise_perception or "USD").upper() != devise:
        raise HTTPException(
            status_code=400,
            detail=f"Devise incompatible : la recette à identifier est en {source.devise_perception}",
        )
    versement = (
        await db.execute(
            select(PaymentHistory)
            .where(
                PaymentHistory.encaissement_id == source.id,
                PaymentHistory.organisation_id == organisation_id,
                PaymentHistory.identification_source_id.is_(None),
                PaymentHistory.statut.in_((VERSEMENT_ACTIF, VERSEMENT_TRANSFERE)),
            )
            .order_by(PaymentHistory.created_at.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    engagement = (await engagements_recettes(db, organisation_id=organisation_id, source_ids=[source.id])).get(source.id)
    bloque = engagement.bloque if engagement else Decimal("0.00")
    return source, versement, bloque


def prelever(
    source: Encaissement,
    versement: PaymentHistory | None,
    montant: Decimal,
    bloque: Decimal = Decimal("0.00"),
) -> Decimal:
    """Retire `montant` de la recette d'origine ; rend le montant réellement prélevé.

    Le statut se recalcule ensuite (`recalculer_statut`), une fois le versement
    de destination écrit.
    """
    montant_recette = _money(source.montant_paye)
    libre = _money(montant_recette - bloque)
    if versement is None or versement.statut != VERSEMENT_ACTIF or libre <= 0:
        raise HTTPException(status_code=400, detail="Cette recette n'a plus rien à identifier")
    if montant - libre > TOLERANCE:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au reste à identifier : {libre}")
    # Un écart d'arrondi ne doit pas laisser un centime orphelin en attente.
    if montant > libre or libre - montant <= TOLERANCE:
        montant = libre

    nouveau_montant = _money(montant_recette - montant)
    if nouveau_montant <= 0:
        versement.statut = VERSEMENT_TRANSFERE
    else:
        versement.montant = _money(_money(versement.montant) - montant)
    for champ in ("montant", "montant_total", "montant_paye", "montant_percu"):
        setattr(source, champ, max(Decimal("0.00"), _money(_money(getattr(source, champ)) - montant)))
    source.statut_paiement = "complet" if nouveau_montant > 0 else "non_paye"
    return montant


async def restituer(
    db: AsyncSession,
    *,
    organisation_id: int,
    source_id: uuid.UUID,
    montant: Decimal,
    versement_annule_id: uuid.UUID,
) -> bool:
    """Rend à la recette d'origine le montant d'une identification annulée.

    Rend `False` si la recette d'origine n'existe plus comme telle (annulée) :
    l'argent n'a alors plus d'endroit où attendre, et l'appelant le traite comme
    un versement ordinaire qu'on retire de la banque.
    """
    source = (
        await db.execute(
            select(Encaissement)
            .where(Encaissement.id == source_id, Encaissement.organisation_id == organisation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if source is None or source.is_deleted or (source.statut_operation or "ACTIVE").upper() != "ACTIVE":
        return False
    versement = (
        await db.execute(
            select(PaymentHistory)
            .where(
                PaymentHistory.encaissement_id == source.id,
                PaymentHistory.organisation_id == organisation_id,
                PaymentHistory.identification_source_id.is_(None),
                PaymentHistory.statut.in_((VERSEMENT_ACTIF, VERSEMENT_TRANSFERE)),
            )
            .order_by(PaymentHistory.created_at.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if versement is None:
        return False

    montant = _money(montant)
    if versement.statut == VERSEMENT_TRANSFERE:
        versement.statut = VERSEMENT_ACTIF
        versement.montant = montant
    else:
        versement.montant = _money(_money(versement.montant) + montant)
    for champ in ("montant", "montant_total", "montant_paye", "montant_percu"):
        setattr(source, champ, _money(_money(getattr(source, champ)) + montant))
    source.statut_paiement = "complet"
    await recalculer_statut(db, organisation_id=organisation_id, source=source, versement_exclu_id=versement_annule_id)
    return True


@dataclass
class Engagements:
    """Ce qui, sur une recette, est rendu ou promis au remboursement."""

    rembourse: Decimal = Decimal("0.00")
    reserve: Decimal = Decimal("0.00")
    remboursements: list[dict[str, Any]] = field(default_factory=list)
    reservations: list[str] = field(default_factory=list)

    @property
    def bloque(self) -> Decimal:
        return _money(self.rembourse + self.reserve)


async def engagements_recettes(
    db: AsyncSession,
    *,
    organisation_id: int,
    source_ids: list[uuid.UUID],
    exclure_requisition_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, Engagements]:
    """Remboursements payés et réservés, recette par recette.

    Rendu : les sorties de fonds valides qui la remboursent. L'argent est sorti
    de la banque par elles ; la recette garde son montant — il est bien entré —
    mais ce montant n'est plus à identifier.

    Réservé : ce qu'une réquisition non close autorise encore à rembourser, sa
    part moins ce que ses sorties ont déjà payé. Même règle que les fonds de
    tiers : une promesse en cours de validation ne s'identifie pas ailleurs.
    """
    resultat: dict[uuid.UUID, Engagements] = {}
    if not source_ids:
        return resultat
    sorties = (
        await db.execute(
            select(SortieFonds).where(
                SortieFonds.organisation_id == organisation_id,
                SortieFonds.recette_a_identifier_id.in_(source_ids),
                SortieFonds.statut == "VALIDE",
            ).order_by(SortieFonds.date_paiement.asc())
        )
    ).scalars().all()
    paye_par_requisition: dict[uuid.UUID, Decimal] = {}
    for sortie in sorties:
        eng = resultat.setdefault(sortie.recette_a_identifier_id, Engagements())
        eng.rembourse = _money(eng.rembourse + _money(sortie.montant_paye))
        eng.remboursements.append(
            {
                "sortie_id": str(sortie.id),
                "reference_numero": sortie.reference_numero,
                "beneficiaire": sortie.beneficiaire,
                "montant": str(_money(sortie.montant_paye)),
                "date": sortie.date_paiement.isoformat() if sortie.date_paiement else None,
            }
        )
        if sortie.requisition_id is not None:
            paye_par_requisition[sortie.requisition_id] = _money(
                paye_par_requisition.get(sortie.requisition_id, Decimal("0")) + _money(sortie.montant_paye)
            )

    query = select(Requisition).where(
        Requisition.organisation_id == organisation_id,
        Requisition.recette_a_identifier_id.in_(source_ids),
        Requisition.is_deleted.is_(False),
        func.upper(func.coalesce(Requisition.status, "")).notin_(STATUTS_REQUISITION_CLOS),
    )
    if exclure_requisition_id is not None:
        query = query.where(Requisition.id != exclure_requisition_id)
    for req in (await db.execute(query)).scalars().all():
        reste = _money(_money(req.montant_total) - paye_par_requisition.get(req.id, Decimal("0")))
        if reste <= 0:
            continue
        eng = resultat.setdefault(req.recette_a_identifier_id, Engagements())
        eng.reserve = _money(eng.reserve + reste)
        eng.reservations.append(req.numero_requisition or str(req.id))
    return resultat


async def recalculer_statut(
    db: AsyncSession,
    *,
    organisation_id: int,
    source: Encaissement,
    versement_exclu_id: uuid.UUID | None = None,
) -> None:
    """Statut d'une recette d'après ce qui en reste, en est identifié ou rendu."""
    query = select(func.count(PaymentHistory.id)).where(
        PaymentHistory.organisation_id == organisation_id,
        PaymentHistory.identification_source_id == source.id,
        PaymentHistory.statut == VERSEMENT_ACTIF,
    )
    if versement_exclu_id is not None:
        query = query.where(PaymentHistory.id != versement_exclu_id)
    identifie = (await db.execute(query)).scalar_one() > 0
    engagement = (await engagements_recettes(db, organisation_id=organisation_id, source_ids=[source.id])).get(source.id)
    rembourse = engagement.rembourse if engagement else Decimal("0.00")
    reste = _money(_money(source.montant_paye) - rembourse)
    if reste > 0:
        source.hors_budget_status = (
            STATUT_PARTIELLEMENT_IDENTIFIE if identifie or rembourse > 0 else STATUT_A_IDENTIFIER
        )
    else:
        source.hors_budget_status = STATUT_IDENTIFIE if identifie else STATUT_REMBOURSEE


async def verifier_remboursement(
    db: AsyncSession,
    *,
    organisation_id: int,
    recette_id: uuid.UUID,
    devise: str,
    montant: Decimal,
    exclure_requisition_id: uuid.UUID | None = None,
    verrouiller: bool = False,
) -> Encaissement:
    """Un remboursement de `montant` est-il possible sur cette recette ?

    À la réquisition, qui réserve ; à la sortie, qui paie (sous verrou, la
    réquisition payée étant alors exclue de sa propre réservation).
    """
    query = select(Encaissement).where(
        Encaissement.id == recette_id, Encaissement.organisation_id == organisation_id
    )
    if verrouiller:
        query = query.with_for_update()
    source = (await db.execute(query)).scalar_one_or_none()
    if source is None or source.is_deleted or not est_recette_a_identifier(source):
        raise HTTPException(status_code=404, detail="Recette à identifier introuvable")
    if (source.statut_operation or "ACTIVE").upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="Cette recette à identifier est annulée")
    if (source.devise_perception or "USD").upper() != (devise or "USD").upper():
        raise HTTPException(
            status_code=400,
            detail=f"Devise incompatible : la recette à identifier est en {source.devise_perception}",
        )
    engagement = (
        await engagements_recettes(
            db, organisation_id=organisation_id, source_ids=[source.id], exclure_requisition_id=exclure_requisition_id
        )
    ).get(source.id) or Engagements()
    libre = _money(_money(source.montant_paye) - engagement.bloque)
    montant = _money(montant)
    if montant <= 0:
        raise HTTPException(status_code=400, detail="Montant de remboursement invalide")
    if montant - libre > TOLERANCE:
        detail = f"Montant supérieur à ce qui reste sur la recette {source.numero_recu} : {libre}"
        if engagement.reservations:
            detail += f" (déjà promis par {', '.join(engagement.reservations)})"
        raise HTTPException(status_code=400, detail=detail)
    return source


def _nom_client(enc: Encaissement, experts: dict[uuid.UUID, str]) -> str | None:
    if enc.expert_comptable_id is not None:
        return experts.get(enc.expert_comptable_id)
    return enc.client_nom


async def _noms_experts(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(ExpertComptable.id, ExpertComptable.nom_denomination).where(ExpertComptable.id.in_(ids))
    )
    return {row[0]: row[1] for row in rows.all()}


async def lister_recettes_a_identifier(
    db: AsyncSession,
    *,
    organisation_id: int,
    ouvertes_seulement: bool = True,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    aujourd_hui = aujourd_hui or datetime.now(timezone.utc).date()
    query = select(Encaissement).where(
        Encaissement.organisation_id == organisation_id,
        Encaissement.nature_mouvement == NATURE_A_IDENTIFIER,
        Encaissement.is_deleted.is_(False),
    )
    if ouvertes_seulement:
        query = query.where(
            Encaissement.statut_operation == "ACTIVE",
            Encaissement.hors_budget_status.in_((STATUT_A_IDENTIFIER, STATUT_PARTIELLEMENT_IDENTIFIE)),
        )
    recettes = (await db.execute(query.order_by(Encaissement.date_encaissement.asc()))).scalars().all()

    identifications: dict[uuid.UUID, list[tuple[PaymentHistory, Encaissement]]] = {}
    if recettes:
        rows = await db.execute(
            select(PaymentHistory, Encaissement)
            .join(Encaissement, Encaissement.id == PaymentHistory.encaissement_id)
            .where(
                PaymentHistory.organisation_id == organisation_id,
                PaymentHistory.identification_source_id.in_([r.id for r in recettes]),
                PaymentHistory.statut == VERSEMENT_ACTIF,
            )
            .order_by(PaymentHistory.created_at.asc())
        )
        for versement, destination in rows.all():
            identifications.setdefault(versement.identification_source_id, []).append((versement, destination))
    experts = await _noms_experts(
        db,
        {dest.expert_comptable_id for lignes in identifications.values() for _v, dest in lignes if dest.expert_comptable_id},
    )
    engagements = await engagements_recettes(
        db, organisation_id=organisation_id, source_ids=[r.id for r in recettes]
    )
    comptes = {}
    compte_ids = {r.compte_bancaire_id for r in recettes if r.compte_bancaire_id}
    if compte_ids:
        rows = await db.execute(select(CompteBancaire).where(CompteBancaire.id.in_(compte_ids)))
        comptes = {c.id: f"{c.intitule} — {c.numero_compte}" for c in rows.scalars().all()}

    items: list[dict[str, Any]] = []
    totaux: dict[str, dict[str, Decimal]] = {}
    for recette in recettes:
        lignes = identifications.get(recette.id, [])
        identifie = _money(sum((_money(v.montant) for v, _d in lignes), Decimal("0")))
        engagement = engagements.get(recette.id) or Engagements()
        active = (recette.statut_operation or "ACTIVE") == "ACTIVE"
        # Reste : ce qui n'est ni identifié ni rendu. La part réservée par une
        # réquisition en cours en fait encore partie — elle n'est pas sortie —
        # mais ne s'identifie plus : `disponible` la retranche.
        reste = _money(_money(recette.montant_paye) - engagement.rembourse) if active else Decimal("0.00")
        disponible = max(Decimal("0.00"), _money(reste - engagement.reserve))
        date_valeur = recette.date_encaissement.date() if recette.date_encaissement else aujourd_hui
        age = max(0, (aujourd_hui - date_valeur).days)
        tranche = tranche_anciennete(age)
        devise = (recette.devise_perception or "USD").upper()
        if reste > 0:
            par_tranche = totaux.setdefault(devise, {libelle: Decimal("0.00") for libelle, _b in TRANCHES})
            par_tranche[tranche] = _money(par_tranche[tranche] + reste)
        items.append(
            {
                "id": str(recette.id),
                "numero": recette.numero_recu,
                "date_valeur": date_valeur.isoformat(),
                "libelle": recette.libelle,
                "reference": recette.reference,
                "compte_bancaire_id": recette.compte_bancaire_id,
                "compte_bancaire": comptes.get(recette.compte_bancaire_id),
                "devise": devise,
                "mode_paiement": recette.mode_paiement,
                "taux_change_applique": str(recette.taux_change_applique or 1),
                "montant_initial": str(_money(_money(recette.montant_paye) + identifie)),
                "montant_identifie": str(identifie),
                "montant_rembourse": str(engagement.rembourse),
                "montant_reserve": str(engagement.reserve),
                "reste": str(reste),
                "disponible": str(disponible),
                "reservations": engagement.reservations,
                "remboursements": engagement.remboursements,
                "age_jours": age,
                "tranche": tranche,
                "statut": recette.hors_budget_status,
                "statut_operation": recette.statut_operation,
                "identifications": [
                    {
                        "versement_id": str(v.id),
                        "encaissement_id": str(d.id),
                        "numero_recu": d.numero_recu,
                        "client": _nom_client(d, experts),
                        "libelle": d.libelle,
                        "nature_mouvement": d.nature_mouvement,
                        "montant": str(_money(v.montant)),
                        "identifie_le": v.created_at.isoformat() if v.created_at else None,
                    }
                    for v, d in lignes
                ],
            }
        )
    return {
        "items": items,
        "totaux": [
            {
                "devise": devise,
                "par_tranche": {k: str(v) for k, v in par_tranche.items()},
                "total": str(_money(sum(par_tranche.values(), Decimal("0")))),
            }
            for devise, par_tranche in sorted(totaux.items())
        ],
    }


def _mots_significatifs(libelle: str | None) -> list[str]:
    """Les mots d'un libellé bancaire susceptibles de nommer le payeur."""
    bruit = {"VIREMENT", "VIRT", "VIR", "RECU", "FAVEUR", "ORDRE", "PAIEMENT", "DEPOT", "REF", "CPTE", "COMPTE", "ONEC"}
    mots = []
    for mot in "".join(c if c.isalnum() else " " for c in (libelle or "").upper()).split():
        if len(mot) >= 4 and not mot.isdigit() and mot not in bruit and mot not in mots:
            mots.append(mot)
    return mots[:6]


async def pistes_identification(
    db: AsyncSession,
    *,
    organisation_id: int,
    source_id: uuid.UUID,
    recherche: str | None = None,
    limite: int = 15,
) -> list[dict[str, Any]]:
    """Notes de débit qui pourraient être celles que ce versement règle.

    Trois indices, du plus fort au plus faible : une recherche saisie
    (numéro de note ou nom), un reste dû égal au montant à identifier, un nom
    du libellé bancaire retrouvé chez le client de la note.
    """
    source = (
        await db.execute(
            select(Encaissement).where(Encaissement.id == source_id, Encaissement.organisation_id == organisation_id)
        )
    ).scalar_one_or_none()
    if source is None or not est_recette_a_identifier(source):
        raise HTTPException(status_code=404, detail="Recette à identifier introuvable")
    engagement = (await engagements_recettes(db, organisation_id=organisation_id, source_ids=[source.id])).get(source.id)
    reste_source = _money(_money(source.montant_paye) - (engagement.bloque if engagement else Decimal("0")))
    reste_du = Encaissement.montant_total - Encaissement.montant_paye

    base = (
        select(Encaissement)
        .outerjoin(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
        .where(
            Encaissement.organisation_id == organisation_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
            Encaissement.statut_operation == "ACTIVE",
            Encaissement.nature_mouvement == "BUDGETAIRE",
            Encaissement.devise_perception == source.devise_perception,
            reste_du > 0,
        )
    )

    trouvees: dict[uuid.UUID, tuple[Encaissement, str]] = {}

    async def ajouter(query, raison: str) -> None:
        for enc in (await db.execute(query.limit(limite))).scalars().unique().all():
            trouvees.setdefault(enc.id, (enc, raison))

    saisie = (recherche or "").strip()
    if saisie:
        motif = f"%{saisie}%"
        await ajouter(
            base.where(
                or_(
                    Encaissement.numero_recu.ilike(motif),
                    Encaissement.numero_note_externe.ilike(motif),
                    Encaissement.client_nom.ilike(motif),
                    ExpertComptable.nom_denomination.ilike(motif),
                )
            ).order_by(Encaissement.date_encaissement.desc()),
            "recherche",
        )
    else:
        await ajouter(
            base.where(func.abs(reste_du - reste_source) <= TOLERANCE).order_by(Encaissement.date_encaissement.desc()),
            "montant",
        )
        mots = _mots_significatifs(source.libelle)
        if mots:
            await ajouter(
                base.where(
                    or_(
                        *[Encaissement.client_nom.ilike(f"%{m}%") for m in mots],
                        *[ExpertComptable.nom_denomination.ilike(f"%{m}%") for m in mots],
                    )
                ).order_by(Encaissement.date_encaissement.desc()),
                "nom",
            )

    experts = await _noms_experts(db, {e.expert_comptable_id for e, _r in trouvees.values() if e.expert_comptable_id})
    return [
        {
            "encaissement_id": str(enc.id),
            "numero_recu": enc.numero_recu,
            "numero_note_externe": enc.numero_note_externe,
            "client": _nom_client(enc, experts),
            "libelle": enc.libelle,
            "date": enc.date_encaissement.date().isoformat() if enc.date_encaissement else None,
            "montant_total": str(_money(enc.montant_total)),
            "reste_du": str(_money(_money(enc.montant_total) - _money(enc.montant_paye))),
            "devise": enc.devise_perception,
            "raison": raison,
        }
        for enc, raison in list(trouvees.values())[:limite]
    ]


async def journaliser_identification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    source: Encaissement,
    destination_id: uuid.UUID,
    versement_id: uuid.UUID,
    montant: Decimal,
    ip_address: str | None,
) -> None:
    await log_action(
        db,
        user_id=user_id,
        action="RECETTE_A_IDENTIFIER_IDENTIFIEE",
        target_table="encaissements",
        target_id=str(source.id),
        new_value={
            "destination_encaissement_id": str(destination_id),
            "versement_id": str(versement_id),
            "montant": str(montant),
            "reste": str(_money(source.montant_paye)),
            "statut": source.hors_budget_status,
        },
        ip_address=ip_address,
    )
