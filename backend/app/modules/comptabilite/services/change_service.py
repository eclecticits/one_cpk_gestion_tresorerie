"""Conversion des écritures vers la devise de tenue.

Le Grand Livre, la Balance et les états financiers agrègent tous les montants
`debit_tenue` / `credit_tenue`. Si une opération en CDF y est portée telle
quelle alors que l'exercice est tenu en USD, ces états **additionnent des
francs congolais à des dollars** : un bilan peut paraître équilibré tout en
étant arithmétiquement faux. Ce module supprime cette possibilité.

## Le taux comptable n'est pas le taux de trésorerie

Ce sont **deux taux distincts**, et c'est délibéré. La trésorerie applique le
taux du jour pour encaisser ou décaisser (`PrintSettings.exchange_rate_cdf`,
figé sur chaque opération dans `exchange_rate_snapshot`). La comptabilité
applique le taux retenu par le comptable pour la période — taux moyen, taux de
clôture, taux officiel de la banque centrale — qui ne coïncide pas
nécessairement avec lui.

**Seul `ComptaTauxChange` fait foi ici.** Le taux de trésorerie n'est jamais
repris automatiquement : il serait impossible de distinguer ensuite une
conversion voulue d'une conversion subie. L'écran de paramétrage comptable
permet de l'utiliser comme point de départ, mais c'est alors un geste
explicite qui crée un vrai taux comptable daté.

## Deux conventions d'expression, à ne pas confondre

- **Le reste de l'application** exprime ses taux en « unités de devise pour
  1 USD » (`exchange_rate_cdf` ≈ 2800). C'est la convention du frontend.
- **Le module comptable** stocke un taux orienté `devise_source →
  devise_cible` : 1 unité de source vaut `taux` unités de cible. CDF→USD vaut
  donc ≈ 0,000357, d'où le `Numeric(18, 8)`.

`taux_tresorerie_vers_comptable` convertit de la première convention vers la
seconde ; l'écran de paramétrage s'en sert pour proposer une valeur initiale.

## Échec bloquant, contrairement au budget

`_to_budget_currency` (sorties_fonds) retombe sur le montant brut quand aucun
taux n'est disponible — « best-effort, comportement historique ». En
comptabilité ce repli EST le défaut que ce module corrige : sans taux
comptable, la génération échoue, comme pour tout mapping manquant.

## Équilibre après conversion

Convertir chaque ligne puis arrondir au centime peut déséquilibrer une
écriture pourtant équilibrée à l'origine (les arrondis ne se compensent pas
toujours). Le résidu est absorbé sur la ligne la plus élevée du côté
excédentaire : une écriture doit rester équilibrée en devise de tenue, c'est
l'invariant que contrôle la validation.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.print_settings import PrintSettings
from app.modules.comptabilite.models import ComptaTauxChange

CENT = Decimal("0.01")
PRECISION_TAUX = Decimal("0.00000001")  # Numeric(18, 8)

# Devise pivot de l'application : tous ses taux sont exprimés par rapport à
# elle (« unités de devise pour 1 USD »).
DEVISE_PIVOT = "USD"

# Colonnes de PrintSettings portant un taux, par devise.
COLONNES_TAUX_PIVOT = {
    "CDF": "exchange_rate_cdf",
    "EUR": "exchange_rate_eur",
    "XOF": "exchange_rate_xof",
}


class TauxIntrouvable(Exception):
    """Aucun taux ne permet de convertir vers la devise de tenue."""


def _q2(montant: Decimal) -> Decimal:
    return Decimal(montant or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _q8(taux: Decimal) -> Decimal:
    return Decimal(taux).quantize(PRECISION_TAUX, rounding=ROUND_HALF_UP)


async def _taux_referentiel(
    db: AsyncSession, organisation_id: int, source: str, cible: str, date_operation: date
) -> Decimal | None:
    """Taux le plus récent du référentiel, à la date de l'opération ou avant.

    Le sens inverse est accepté et retourné inversé : saisir un seul des deux
    sens suffit à l'organisation.
    """
    for devise_a, devise_b, inverser in ((source, cible, False), (cible, source, True)):
        res = await db.execute(
            select(ComptaTauxChange.taux)
            .where(
                ComptaTauxChange.organisation_id == organisation_id,
                ComptaTauxChange.devise_source == devise_a,
                ComptaTauxChange.devise_cible == devise_b,
                ComptaTauxChange.date_taux <= date_operation,
            )
            .order_by(ComptaTauxChange.date_taux.desc())
            .limit(1)
        )
        taux = res.scalar_one_or_none()
        if taux and Decimal(taux) > 0:
            return _q8(Decimal(1) / Decimal(taux)) if inverser else _q8(Decimal(taux))
    return None


async def taux_tresorerie_vers_comptable(
    db: AsyncSession, organisation_id: int, source: str, cible: str
) -> Decimal | None:
    """Traduit les taux de trésorerie dans la convention comptable.

    Sert **uniquement** à proposer une valeur de départ dans l'écran de
    paramétrage : le comptable reste libre de retenir un autre taux. Cette
    fonction n'est jamais appelée par le moteur de génération.

    Les réglages d'impression sont exprimés par rapport à l'USD ; le taux entre
    deux devises non pivot se déduit du rapport de leurs deux taux.
    """
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1)
    )
    reglages = res.scalar_one_or_none()
    if reglages is None:
        return None

    def par_usd(devise: str) -> Decimal | None:
        if devise == DEVISE_PIVOT:
            return Decimal(1)
        colonne = COLONNES_TAUX_PIVOT.get(devise)
        if colonne is None:
            return None
        brut = getattr(reglages, colonne, None)
        try:
            valeur = Decimal(str(brut or 0))
        except (ArithmeticError, ValueError):
            return None
        return valeur if valeur > 0 else None

    taux_source = par_usd(source.upper())
    taux_cible = par_usd(cible.upper())
    if taux_source is None or taux_cible is None:
        return None
    # 1 source = (1 / taux_source) USD = (taux_cible / taux_source) cible.
    return _q8(taux_cible / taux_source)


async def resoudre_taux(
    db: AsyncSession,
    *,
    organisation_id: int,
    devise_source: str,
    devise_cible: str,
    date_operation: date,
) -> Decimal:
    """Taux COMPTABLE orienté `devise_source → devise_cible`, à la date donnée.

    Seul le référentiel `ComptaTauxChange` est consulté : le taux appliqué par
    la trésorerie à l'opération n'est jamais repris automatiquement, puisqu'il
    ne coïncide pas nécessairement avec le taux retenu en comptabilité.

    Sans taux comptable à cette date, l'appelant reçoit `TauxIntrouvable` :
    aucune conversion approximative n'est tentée.
    """
    source = (devise_source or DEVISE_PIVOT).upper()
    cible = (devise_cible or DEVISE_PIVOT).upper()
    if source == cible:
        return Decimal(1)

    taux = await _taux_referentiel(db, organisation_id, source, cible, date_operation)
    if taux is not None and taux > 0:
        return taux

    raise TauxIntrouvable(
        f"Aucun taux de change comptable {source} → {cible} au {date_operation}. "
        "Renseignez-le dans Comptabilité → Paramétrage → Taux de change avant de "
        f"comptabiliser une opération en {source}."
    )


def convertir_lignes(
    lignes: list[tuple[Decimal, Decimal]], taux: Decimal
) -> list[tuple[Decimal, Decimal]]:
    """Convertit des couples (débit, crédit) vers la devise de tenue.

    Le même taux s'applique à toutes les lignes d'une écriture — c'est ce qui
    rend la conversion vérifiable. Si l'écriture est équilibrée à l'origine,
    elle l'est encore après conversion : le résidu d'arrondi éventuel est
    absorbé sur la plus grosse ligne du côté excédentaire.

    Une écriture DÉJÀ déséquilibrée à l'origine n'est pas « réparée » : elle
    est convertie telle quelle et la validation la refusera, comme elle doit.
    """
    if taux == 1:
        return [(_q2(d), _q2(c)) for d, c in lignes]

    convertis = [(_q2(Decimal(d or 0) * taux), _q2(Decimal(c or 0) * taux)) for d, c in lignes]

    origine_debit = sum((Decimal(d or 0) for d, _ in lignes), Decimal("0"))
    origine_credit = sum((Decimal(c or 0) for _, c in lignes), Decimal("0"))
    if origine_debit != origine_credit:
        return convertis

    ecart = sum((d for d, _ in convertis), Decimal("0")) - sum(
        (c for _, c in convertis), Decimal("0")
    )
    if ecart == 0:
        return convertis

    # Le résidu est AJOUTÉ à la plus grosse ligne du côté déficitaire, jamais
    # retranché du côté excédentaire. Deux raisons :
    # - aucune ligne ne peut devenir négative, ce qu'interdit la contrainte
    #   `ck_compta_ligne_montants_positifs` ;
    # - le total de l'écriture s'aligne sur la conversion de son côté le plus
    #   fidèle, plutôt que de rogner un montant déjà juste.
    manque = abs(ecart)
    cote_deficitaire_est_credit = ecart > 0
    index_cible, _ = max(
        (
            (i, (credit if cote_deficitaire_est_credit else debit))
            for i, (debit, credit) in enumerate(convertis)
        ),
        key=lambda item: item[1],
    )
    debit, credit = convertis[index_cible]
    if cote_deficitaire_est_credit:
        convertis[index_cible] = (debit, credit + manque)
    else:
        convertis[index_cible] = (debit + manque, credit)
    return convertis
