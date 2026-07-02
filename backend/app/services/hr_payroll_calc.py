from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Barème IPR (Impôt Professionnel sur les Rémunérations, RDC) — mensuel, en CDF.
# Source : DGI / réforme LF 2020 (4 tranches). À reconfirmer en cas de réforme
# fiscale (une transition IPR → IRPP est annoncée pour 2026).
# Chaque tuple = (borne basse, borne haute ou None si dernière tranche, taux).
IPR_BRACKETS_CDF: list[tuple[Decimal, Decimal | None, Decimal]] = [
    (Decimal("0"), Decimal("162000"), Decimal("0.03")),
    (Decimal("162000"), Decimal("1800000"), Decimal("0.15")),
    (Decimal("1800000"), Decimal("3600000"), Decimal("0.30")),
    (Decimal("3600000"), None, Decimal("0.40")),
]
IPR_PLANCHER_CDF = Decimal("2000")
IPR_PLAFOND_TAUX = Decimal("0.30")  # l'IPR ne peut dépasser 30% du revenu imposable

# CNSS (ex-INSS), décret n°18/041 du 24/11/2018 — part salariale (branche pension).
CNSS_TAUX_SALARIE = Decimal("0.05")

_CENTS = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_ipr_cdf(revenu_imposable_cdf: Decimal) -> Decimal:
    """IPR mensuel dû sur un revenu imposable exprimé en CDF."""
    if revenu_imposable_cdf <= 0:
        return Decimal("0")

    total = Decimal("0")
    for lower, upper, rate in IPR_BRACKETS_CDF:
        if revenu_imposable_cdf <= lower:
            break
        bracket_top = upper if upper is not None else revenu_imposable_cdf
        taxable_in_bracket = min(revenu_imposable_cdf, bracket_top) - lower
        if taxable_in_bracket > 0:
            total += taxable_in_bracket * rate

    total = max(total, IPR_PLANCHER_CDF)
    plafond = revenu_imposable_cdf * IPR_PLAFOND_TAUX
    total = min(total, plafond)
    return _round(total)


def compute_cnss_salarie(revenu_brut: Decimal) -> Decimal:
    """Part salariale CNSS (5% du revenu brut), dans la devise du revenu fourni."""
    if revenu_brut <= 0:
        return Decimal("0")
    return _round(revenu_brut * CNSS_TAUX_SALARIE)


def compute_slip_deductions(
    salaire_base: Decimal,
    total_primes: Decimal,
    devise: str,
    taux_change_interne: Decimal | None,
) -> dict[str, Decimal]:
    """Calcule IPR + CNSS (part salariale) et le net à payer pour un bulletin.

    Le barème IPR est en CDF. Si le bulletin est dans une autre devise (ex. USD),
    le revenu imposable est converti en CDF via taux_change_interne (taux de
    change interne de l'organisation) pour appliquer le barème, puis l'IPR est
    reconverti dans la devise d'origine. La CNSS est un pourcentage simple,
    calculée directement dans la devise du bulletin (pas de conversion requise).

    Hypothèse retenue (à confirmer avec un fiscaliste/comptable local) : le
    revenu imposable IPR est le revenu brut (salaire de base + primes), la CNSS
    salariale n'est pas déduite de l'assiette IPR.
    """
    revenu_imposable = salaire_base + total_primes

    if devise.upper() in ("CDF", "FC"):
        ipr = compute_ipr_cdf(revenu_imposable)
    else:
        taux = taux_change_interne or Decimal("0")
        if taux <= 0:
            raise ValueError(
                f"Impossible de calculer l'IPR pour une devise {devise} sans "
                "taux de change interne configuré (organisation.taux_change_interne)."
            )
        revenu_imposable_cdf = revenu_imposable * taux
        ipr_cdf = compute_ipr_cdf(revenu_imposable_cdf)
        ipr = _round(ipr_cdf / taux)

    cnss_salarie = compute_cnss_salarie(revenu_imposable)
    total_retenues = _round(ipr + cnss_salarie)
    net_a_payer = _round(revenu_imposable - total_retenues)

    return {
        "ipr": ipr,
        "cnss_salarie": cnss_salarie,
        "total_retenues": total_retenues,
        "net_a_payer": net_a_payer,
    }
