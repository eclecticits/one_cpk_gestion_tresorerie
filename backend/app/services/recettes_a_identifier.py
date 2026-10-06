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
from app.services.audit_service import log_action
from app.services.document_sequences import generate_document_number


NATURE_A_IDENTIFIER = "A_IDENTIFIER"
STATUT_A_IDENTIFIER = "A_IDENTIFIER"
STATUT_PARTIELLEMENT_IDENTIFIE = "PARTIELLEMENT_IDENTIFIE"
STATUT_IDENTIFIE = "IDENTIFIE"

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

    # Même conversion qu'un encaissement saisi en francs : les montants de la
    # note sont tenus en dollars, au taux du jour de la réception.
    if devise == "CDF":
        taux = await _taux_cdf(db, organisation_id)
        montant_note = _money(montant_saisi / taux)
    else:
        taux = Decimal("1")
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
) -> tuple[Encaissement, PaymentHistory | None]:
    """La recette d'origine et son versement, verrouillés pour être prélevés."""
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
    return source, versement


def prelever(source: Encaissement, versement: PaymentHistory | None, montant: Decimal) -> Decimal:
    """Retire `montant` de la recette d'origine ; rend le montant réellement prélevé."""
    reste = _money(source.montant_paye)
    if versement is None or versement.statut != VERSEMENT_ACTIF or reste <= 0:
        raise HTTPException(status_code=400, detail="Cette recette est déjà entièrement identifiée")
    if montant - reste > TOLERANCE:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au reste à identifier : {reste}")
    # Un écart d'arrondi ne doit pas laisser un centime orphelin en attente.
    if montant > reste or reste - montant <= TOLERANCE:
        montant = reste

    nouveau_reste = _money(reste - montant)
    if nouveau_reste <= 0:
        versement.statut = VERSEMENT_TRANSFERE
    else:
        versement.montant = _money(_money(versement.montant) - montant)
    for champ in ("montant", "montant_total", "montant_paye", "montant_percu"):
        setattr(source, champ, max(Decimal("0.00"), _money(_money(getattr(source, champ)) - montant)))
    source.statut_paiement = "complet" if nouveau_reste > 0 else "non_paye"
    source.hors_budget_status = STATUT_IDENTIFIE if nouveau_reste <= 0 else STATUT_PARTIELLEMENT_IDENTIFIE
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

    encore_identifie = (
        await db.execute(
            select(func.count(PaymentHistory.id)).where(
                PaymentHistory.organisation_id == organisation_id,
                PaymentHistory.identification_source_id == source.id,
                PaymentHistory.statut == VERSEMENT_ACTIF,
                PaymentHistory.id != versement_annule_id,
            )
        )
    ).scalar_one()
    source.hors_budget_status = STATUT_PARTIELLEMENT_IDENTIFIE if encore_identifie else STATUT_A_IDENTIFIER
    return True


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
        reste = _money(recette.montant_paye) if (recette.statut_operation or "ACTIVE") == "ACTIVE" else Decimal("0.00")
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
                "montant_initial": str(_money(reste + identifie)),
                "montant_identifie": str(identifie),
                "reste": str(reste),
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
    reste_source = _money(source.montant_paye)
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
