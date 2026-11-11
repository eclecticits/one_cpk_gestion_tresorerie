"""Balance âgée des tiers.

Ce qui reste dû sur chaque compte de tiers, rangé par ancienneté. Elle
s'appuie sur le lettrage : une ligne lettrée est soldée, seules les lignes
sans lettre comptent. Sans lettrage à jour, elle vieillit des créances déjà
réglées — d'où le rappel du nombre de lignes non lettrées par compte.

L'âge se compte depuis l'échéance de la ligne quand elle en porte une (la
créance d'une note de débit reprend l'échéance de la note), sinon depuis la
date de l'écriture. Une ligne dont l'échéance n'est pas atteinte est « non
échue ».

Une ligne lettrée APRÈS la date d'arrêt compte encore : à cette date, elle
n'était pas soldée. C'est ce qui permet de rééditer la balance d'une fin de
mois passée.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import ComptaCompte, ComptaEcriture, ComptaLigneEcriture
from app.modules.comptabilite.services.lettrage_service import STATUTS_LETTRABLES

ZERO = Decimal("0")
#: Bornes hautes des tranches, en jours de retard ; la dernière est ouverte.
BORNES = (30, 60, 90)
TRANCHES = ("non_echu", "j0_30", "j31_60", "j61_90", "plus_90")


def tranche(jours: int) -> str:
    """La tranche d'une ligne en retard de `jours` (négatif : pas encore échue)."""
    if jours < 0:
        return "non_echu"
    for borne, nom in zip(BORNES, TRANCHES[1:]):
        if jours <= borne:
            return nom
    return "plus_90"


@dataclass
class LigneBalanceAgee:
    compte_id: int
    compte_numero: str
    compte_libelle: str
    lignes: int = 0
    tranches: dict[str, Decimal] = field(default_factory=lambda: {t: ZERO for t in TRANCHES})
    plus_ancienne: date | None = None

    @property
    def solde(self) -> Decimal:
        return sum(self.tranches.values(), ZERO)


@dataclass
class BalanceAgee:
    date_arret: date
    sens: str
    lignes: list[LigneBalanceAgee]

    @property
    def totaux(self) -> dict[str, Decimal]:
        return {t: sum((l.tranches[t] for l in self.lignes), ZERO) for t in TRANCHES}

    @property
    def total(self) -> Decimal:
        return sum((l.solde for l in self.lignes), ZERO)


async def balance_agee(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_arret: date,
    sens: str = "CREANCES",
    prefixe: str | None = None,
) -> BalanceAgee:
    """Reste dû par compte de tiers à `date_arret`, par tranche d'ancienneté.

    `sens` : CREANCES ne garde que les comptes débiteurs (ce qu'on nous doit),
    montants positifs au débit ; DETTES ne garde que les créditeurs (ce que
    l'on doit), montants positifs au crédit. Un tiers créditeur ne vient donc
    jamais en déduction des créances des autres.
    """
    stmt = (
        select(
            ComptaCompte.id,
            ComptaCompte.numero,
            ComptaCompte.libelle,
            ComptaLigneEcriture.debit_tenue,
            ComptaLigneEcriture.credit_tenue,
            ComptaLigneEcriture.date_echeance,
            ComptaEcriture.date_ecriture,
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaCompte, ComptaCompte.id == ComptaLigneEcriture.compte_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaEcriture.organisation_id == organisation_id,
            ComptaCompte.organisation_id == organisation_id,
            ComptaCompte.lettrable.is_(True),
            ComptaEcriture.statut.in_(STATUTS_LETTRABLES),
            ComptaEcriture.date_ecriture <= date_arret,
            or_(
                ComptaLigneEcriture.lettrage.is_(None),
                ComptaLigneEcriture.date_lettrage > date_arret,
            ),
        )
        .order_by(ComptaCompte.numero)
    )
    if prefixe:
        stmt = stmt.where(ComptaCompte.numero.like(f"{prefixe}%"))

    signe = Decimal("1") if sens == "CREANCES" else Decimal("-1")
    par_compte: dict[int, LigneBalanceAgee] = {}
    for row in (await db.execute(stmt)).all():
        ligne = par_compte.get(row.id)
        if ligne is None:
            ligne = par_compte[row.id] = LigneBalanceAgee(
                compte_id=row.id, compte_numero=row.numero, compte_libelle=row.libelle
            )
        reference = row.date_echeance or row.date_ecriture
        montant = (Decimal(row.debit_tenue) - Decimal(row.credit_tenue)) * signe
        ligne.tranches[tranche((date_arret - reference).days)] += montant
        ligne.lignes += 1
        if ligne.plus_ancienne is None or row.date_ecriture < ligne.plus_ancienne:
            ligne.plus_ancienne = row.date_ecriture

    return BalanceAgee(
        date_arret=date_arret,
        sens=sens,
        lignes=[l for l in par_compte.values() if l.solde > 0],
    )
