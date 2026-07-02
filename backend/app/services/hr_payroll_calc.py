from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_CENTS = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


# Valeurs par défaut (RDC) utilisées tant qu'une organisation n'a pas
# personnalisé ses paramètres de paie dans hr_payroll_settings.
# Source : DGI (barème IPR mensuel, réforme LF 2020, 4 tranches) + décret
# CNSS n°18/041 du 24/11/2018 (part salariale). À reconfirmer avec un
# fiscaliste — une réforme IPR → IRPP est annoncée pour 2026.
DEFAULT_DEVISE_BAREME = "CDF"
DEFAULT_IPR_BRACKETS_CDF: list[dict[str, Decimal | None]] = [
    {"lower": Decimal("0"), "upper": Decimal("162000"), "rate": Decimal("0.03")},
    {"lower": Decimal("162000"), "upper": Decimal("1800000"), "rate": Decimal("0.15")},
    {"lower": Decimal("1800000"), "upper": Decimal("3600000"), "rate": Decimal("0.30")},
    {"lower": Decimal("3600000"), "upper": None, "rate": Decimal("0.40")},
]
DEFAULT_IPR_PLANCHER = Decimal("2000")
DEFAULT_IPR_PLAFOND_TAUX = Decimal("0.30")
DEFAULT_CNSS_TAUX_SALARIE = Decimal("0.05")


@dataclass(frozen=True)
class PayrollParams:
    devise_bareme: str = DEFAULT_DEVISE_BAREME
    ipr_brackets: list[dict[str, Decimal | None]] = field(default_factory=lambda: list(DEFAULT_IPR_BRACKETS_CDF))
    ipr_plancher: Decimal = DEFAULT_IPR_PLANCHER
    ipr_plafond_taux: Decimal = DEFAULT_IPR_PLAFOND_TAUX
    cnss_taux_salarie: Decimal = DEFAULT_CNSS_TAUX_SALARIE


def params_from_settings_row(row: Any | None) -> PayrollParams:
    """Construit un PayrollParams à partir d'un HRPayrollSettings, ou renvoie
    les valeurs par défaut si l'organisation n'a rien personnalisé (row=None)."""
    if row is None:
        return PayrollParams()
    brackets = [
        {
            "lower": _dec(b["lower"]),
            "upper": _dec(b["upper"]) if b.get("upper") is not None else None,
            "rate": _dec(b["rate"]),
        }
        for b in row.ipr_brackets
    ]
    return PayrollParams(
        devise_bareme=row.devise_bareme,
        ipr_brackets=brackets,
        ipr_plancher=_dec(row.ipr_plancher),
        ipr_plafond_taux=_dec(row.ipr_plafond_taux),
        cnss_taux_salarie=_dec(row.cnss_taux_salarie),
    )


def compute_ipr(revenu_imposable: Decimal, params: PayrollParams | None = None) -> Decimal:
    """IPR (ou équivalent) dû sur un revenu imposable, dans la devise du barème."""
    params = params or PayrollParams()
    if revenu_imposable <= 0:
        return Decimal("0")

    total = Decimal("0")
    for bracket in params.ipr_brackets:
        lower = _dec(bracket["lower"])
        upper = bracket.get("upper")
        rate = _dec(bracket["rate"])
        if revenu_imposable <= lower:
            break
        bracket_top = _dec(upper) if upper is not None else revenu_imposable
        taxable_in_bracket = min(revenu_imposable, bracket_top) - lower
        if taxable_in_bracket > 0:
            total += taxable_in_bracket * rate

    total = max(total, params.ipr_plancher)
    plafond = revenu_imposable * params.ipr_plafond_taux
    total = min(total, plafond)
    return _round(total)


def compute_cnss_salarie(revenu_brut: Decimal, params: PayrollParams | None = None) -> Decimal:
    """Part salariale des cotisations sociales (pourcentage simple, pas de conversion)."""
    params = params or PayrollParams()
    if revenu_brut <= 0:
        return Decimal("0")
    return _round(revenu_brut * params.cnss_taux_salarie)


def compute_slip_deductions(
    salaire_base: Decimal,
    total_primes: Decimal,
    devise: str,
    taux_change_interne: Decimal | None,
    params: PayrollParams | None = None,
) -> dict[str, Decimal]:
    """Calcule l'impôt sur salaire + cotisation sociale (part salariale) et le
    net à payer pour un bulletin.

    Le barème d'impôt (params.ipr_brackets) est dans la devise
    params.devise_bareme. Si le bulletin est dans une autre devise, le revenu
    imposable est converti via taux_change_interne (taux de change interne de
    l'organisation) pour appliquer le barème, puis le montant est reconverti
    dans la devise d'origine. La cotisation sociale est un pourcentage simple,
    calculée directement dans la devise du bulletin (pas de conversion).

    Hypothèse retenue (à confirmer avec un fiscaliste/comptable local) : le
    revenu imposable est le revenu brut (salaire de base + primes) ; la
    cotisation sociale salariale n'est pas déduite de l'assiette imposable.
    """
    params = params or PayrollParams()
    revenu_imposable = salaire_base + total_primes

    if devise.upper() == params.devise_bareme.upper():
        ipr = compute_ipr(revenu_imposable, params)
    else:
        taux = taux_change_interne or Decimal("0")
        if taux <= 0:
            raise ValueError(
                f"Impossible de calculer l'impôt pour une devise {devise} sans "
                "taux de change interne configuré (organisation.taux_change_interne)."
            )
        revenu_imposable_bareme = revenu_imposable * taux
        ipr_bareme = compute_ipr(revenu_imposable_bareme, params)
        ipr = _round(ipr_bareme / taux)

    cnss_salarie = compute_cnss_salarie(revenu_imposable, params)
    total_retenues = _round(ipr + cnss_salarie)
    net_a_payer = _round(revenu_imposable - total_retenues)

    return {
        "ipr": ipr,
        "cnss_salarie": cnss_salarie,
        "total_retenues": total_retenues,
        "net_a_payer": net_a_payer,
    }
