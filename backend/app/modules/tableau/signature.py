"""Signature des rapports du Tableau : la Commission Tableau du conseil, puis son président.

« Président » pour un homme, « Présidente » pour une femme. Le sexe vient du compte
lié à la fiche du président, à défaut de ce que le Tableau sait de son N° d'ordre
(dossier, puis fiche des personnes physiques), à défaut d'une fonction écrite au féminin. Sans aucun des trois, « Président(e) » :
on n'accorde pas au hasard.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.commission_member import CommissionMember, CommissionRole
from app.models.service import Service

from .models import TableauDossier, TableauPersonnePhysiqueSnapshot


@dataclass(frozen=True)
class Signature:
    commission: str
    qualite: str
    nom: str | None = None

    def lignes(self) -> list[str]:
        """La commission, la qualité, puis le nom du président s'il est désigné."""
        return [self.commission, self.qualite, *([self.nom] if self.nom else [])]


def commission_du_conseil(organisation: str) -> str:
    """« Commission Tableau du Conseil Provincial de Kinshasa »."""
    nom = (organisation or "").strip()
    if not nom:
        return "Commission Tableau"
    return f"Commission Tableau {'du' if nom.casefold().startswith('conseil ') else 'de'} {nom}"


def qualite_president(sexe: str | None) -> str:
    return {"M": "Président", "F": "Présidente"}.get(sexe or "", "Président(e)")


def sexe_normalise(valeur: str | None) -> str | None:
    v = (valeur or "").strip().upper()
    if v in {"M", "H", "MASCULIN", "HOMME"}:
        return "M"
    if v in {"F", "FEMININ", "FÉMININ", "FEMME"}:
        return "F"
    return None


async def _sexe_au_tableau(db: AsyncSession, organisation_id: int, matricule: str | None) -> str | None:
    """Le sexe que le Tableau connaît pour ce N° d'ordre : son dossier, sinon sa fiche
    du fichier des personnes physiques (un membre sans dossier analysé y figure aussi)."""
    numero = "".join((matricule or "").upper().split())
    if not numero:
        return None
    for modele, recent in (
        (TableauDossier, (TableauDossier.exercice.desc(), TableauDossier.id.desc())),
        (TableauPersonnePhysiqueSnapshot, (TableauPersonnePhysiqueSnapshot.date_situation.desc(), TableauPersonnePhysiqueSnapshot.id.desc())),
    ):
        valeurs = (await db.execute(
            select(modele.sexe)
            .where(
                modele.organisation_id == organisation_id,
                func.upper(func.replace(modele.numero_ordre, " ", "")) == numero,
                func.coalesce(modele.sexe, "") != "",
            )
            .order_by(*recent)
            .limit(1)
        )).scalars().all()
        sexe = sexe_normalise(valeurs[0]) if valeurs else None
        if sexe:
            return sexe
    return None


async def signature_commission(db: AsyncSession, organisation_id: int, organisation: str) -> Signature:
    """Signature de la Commission Tableau du conseil ; sans président désigné, la commission seule."""
    membres = (await db.execute(
        select(CommissionMember)
        .join(Service, Service.id == CommissionMember.service_id)
        .where(
            Service.organisation_id == organisation_id,
            func.lower(Service.libelle).like("%tableau%"),
            CommissionMember.role_type == CommissionRole.PRESIDENT,
        )
        .options(selectinload(CommissionMember.user), selectinload(CommissionMember.function))
        .order_by(CommissionMember.id)
    )).scalars().all()
    commission = commission_du_conseil(organisation)
    if not membres:
        return Signature(commission=commission, qualite=qualite_president(None))
    president = membres[0]
    fonction = (president.function.label if president.function is not None else "") or president.custom_title or ""
    sexe = (
        sexe_normalise(getattr(president.user, "sexe", None))
        or await _sexe_au_tableau(db, organisation_id, president.matricule)
        or ("F" if "présidente" in fonction.casefold() else None)
    )
    return Signature(commission=commission, qualite=qualite_president(sexe), nom=(president.full_name or "").strip() or None)
