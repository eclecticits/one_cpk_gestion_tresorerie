"""Entrées de caisse qui ne sont pas des encaissements clients.

Un approvisionnement de caisse est stocké dans `sorties_fonds` (canal BANQUE,
`type_sortie = 'approvisionnement_caisse'`) : c'est une SORTIE pour le compte
bancaire, mais une ENTRÉE pour la caisse. Les écrans qui présentent la caisse
(encaissements, clôture, journal de trésorerie) doivent donc pouvoir lister ces
lignes du côté « entrées », sinon la caisse paraît se remplir toute seule.

Ce module centralise la requête pour que tous ces écrans montrent exactement les
mêmes lignes que celles agrégées dans les totaux (`clotures.py`, `reports.py`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

# `created_by` n'est pas une clé étrangère déclarée : la jointure est explicite.
Auteur = aliased(User)


def sortie_timestamp():
    """Horodatage retenu pour une sortie : même règle que les agrégats."""
    return func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)


async def list_approvisionnements_caisse(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_debut: datetime | None = None,
    date_fin: datetime | None = None,
    devise: str | None = None,
    strict_debut: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Approvisionnements banque -> caisse validés, vus comme des entrées.

    `strict_debut` reproduit la borne « > » de la balance de clôture (les
    opérations horodatées à la clôture précédente appartiennent à la période
    close, pas à la suivante).
    """
    ts = sortie_timestamp()
    query = (
        select(
            SortieFonds.id,
            ts.label("date"),
            SortieFonds.reference_numero,
            SortieFonds.reference,
            SortieFonds.motif,
            SortieFonds.montant_paye,
            SortieFonds.devise,
            SortieFonds.mode_paiement,
            SortieFonds.created_at,
            CompteBancaire.intitule,
            CompteBancaire.numero_compte,
            Banque.nom,
            Auteur.prenom,
            Auteur.nom,
            Auteur.email,
        )
        .outerjoin(CompteBancaire, SortieFonds.compte_bancaire_id == CompteBancaire.id)
        .outerjoin(Banque, CompteBancaire.banque_id == Banque.id)
        .outerjoin(Auteur, SortieFonds.created_by == Auteur.id)
        .where(
            SortieFonds.organisation_id == tenant_id,
            SortieFonds.type_sortie == "approvisionnement_caisse",
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
        )
        .order_by(ts.desc())
    )
    if devise:
        query = query.where(SortieFonds.devise == devise.upper())
    if date_debut is not None:
        query = query.where(ts > date_debut) if strict_debut else query.where(ts >= date_debut)
    if date_fin is not None:
        query = query.where(ts <= date_fin)
    if limit:
        query = query.limit(limit)

    lignes: list[dict] = []
    for row in (await db.execute(query)).all():
        (
            sortie_id,
            date_value,
            reference_numero,
            reference,
            motif,
            montant,
            devise_ligne,
            mode_paiement,
            created_at,
            compte_intitule,
            compte_numero,
            banque_nom,
            auteur_prenom,
            auteur_nom,
            auteur_email,
        ) = row
        source = " - ".join(part for part in (banque_nom, compte_intitule) if part)
        auteur = f"{auteur_prenom or ''} {auteur_nom or ''}".strip() or (auteur_email or "")
        lignes.append(
            {
                "id": str(sortie_id),
                "date": date_value,
                "created_at": created_at,
                "reference": reference_numero or reference,
                "libelle": motif or "Approvisionnement de la caisse",
                "montant": Decimal(montant or 0),
                "devise": (devise_ligne or "USD").upper(),
                "mode_paiement": mode_paiement,
                "source": source or "Banque",
                "banque": banque_nom or "",
                "compte_numero": compte_numero or "",
                "auteur": auteur,
                "type_operation": "APPROVISIONNEMENT",
                "sens": "ENTREE",
            }
        )
    return lignes


async def list_versements_banque(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_debut: datetime | None = None,
    date_fin: datetime | None = None,
    devise: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Versements caisse -> banque validés, vus comme des entrées bancaires."""
    ts = sortie_timestamp()
    query = (
        select(
            SortieFonds.id,
            ts.label("date"),
            SortieFonds.reference_numero,
            SortieFonds.reference,
            SortieFonds.motif,
            SortieFonds.montant_paye,
            SortieFonds.devise,
            SortieFonds.mode_paiement,
            SortieFonds.created_at,
            CompteBancaire.intitule,
            CompteBancaire.numero_compte,
            Banque.nom,
            Auteur.prenom,
            Auteur.nom,
            Auteur.email,
        )
        .outerjoin(CompteBancaire, SortieFonds.compte_bancaire_id == CompteBancaire.id)
        .outerjoin(Banque, CompteBancaire.banque_id == Banque.id)
        .outerjoin(Auteur, SortieFonds.created_by == Auteur.id)
        .where(
            SortieFonds.organisation_id == tenant_id,
            SortieFonds.type_sortie == "versement_banque",
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
        )
        .order_by(ts.desc())
    )
    if devise:
        query = query.where(SortieFonds.devise == devise.upper())
    if date_debut is not None:
        query = query.where(ts >= date_debut)
    if date_fin is not None:
        query = query.where(ts <= date_fin)
    if limit:
        query = query.limit(limit)

    lignes: list[dict] = []
    for row in (await db.execute(query)).all():
        (
            sortie_id,
            date_value,
            reference_numero,
            reference,
            motif,
            montant,
            devise_ligne,
            mode_paiement,
            created_at,
            compte_intitule,
            compte_numero,
            banque_nom,
            auteur_prenom,
            auteur_nom,
            auteur_email,
        ) = row
        destination = " - ".join(part for part in (banque_nom, compte_intitule) if part)
        auteur = f"{auteur_prenom or ''} {auteur_nom or ''}".strip() or (auteur_email or "")
        lignes.append(
            {
                "id": str(sortie_id),
                "date": date_value,
                "created_at": created_at,
                "reference": reference_numero or reference,
                "libelle": motif or "Versement à la banque",
                "montant": Decimal(montant or 0),
                "devise": (devise_ligne or "USD").upper(),
                "mode_paiement": mode_paiement,
                "destination": destination or "Banque",
                "banque": banque_nom or "",
                "compte_numero": compte_numero or "",
                "auteur": auteur,
                "type_operation": "VERSEMENT_BANQUE",
                "sens": "ENTREE",
            }
        )
    return lignes
