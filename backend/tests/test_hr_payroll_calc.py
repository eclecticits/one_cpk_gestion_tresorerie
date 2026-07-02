from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.hr_payroll_calc import (
    DEFAULT_CNSS_TAUX_SALARIE,
    PayrollParams,
    compute_cnss_salarie,
    compute_ipr,
    compute_slip_deductions,
    params_from_settings_row,
)


class TestComputeIprDefaultParams:
    def test_revenu_nul_ou_negatif(self):
        assert compute_ipr(Decimal("0")) == Decimal("0")
        assert compute_ipr(Decimal("-100")) == Decimal("0")

    def test_petit_revenu_applique_le_plancher(self):
        # 50 000 * 3% = 1 500 < plancher 2 000 -> le plancher s'applique
        assert compute_ipr(Decimal("50000")) == Decimal("2000.00")

    def test_exemple_officiel_500000_fc(self):
        # Exemple documenté (monrespro.cd) : 500 000 FC/mois -> IPR = 55 560 FC
        # tranche 1 : 162 000 * 3% = 4 860
        # tranche 2 : (500 000 - 162 000) * 15% = 50 700
        assert compute_ipr(Decimal("500000")) == Decimal("55560.00")

    def test_borne_exacte_premiere_tranche(self):
        assert compute_ipr(Decimal("162000")) == Decimal("4860.00")

    def test_borne_exacte_deuxieme_tranche(self):
        # 4 860 + (1 800 000 - 162 000) * 15% = 4 860 + 245 700
        assert compute_ipr(Decimal("1800000")) == Decimal("250560.00")

    def test_borne_exacte_troisieme_tranche(self):
        # 250 560 + (3 600 000 - 1 800 000) * 30% = 250 560 + 540 000
        assert compute_ipr(Decimal("3600000")) == Decimal("790560.00")

    def test_plafond_30_pourcent_du_revenu_imposable(self):
        revenu = Decimal("10000000")
        plafond = revenu * Decimal("0.30")
        assert compute_ipr(revenu) == plafond.quantize(Decimal("0.01"))


class TestComputeIprCustomParams:
    def test_bareme_a_deux_tranches_personnalise(self):
        params = PayrollParams(
            devise_bareme="CDF",
            ipr_brackets=[
                {"lower": Decimal("0"), "upper": Decimal("100000"), "rate": Decimal("0.10")},
                {"lower": Decimal("100000"), "upper": None, "rate": Decimal("0.20")},
            ],
            ipr_plancher=Decimal("0"),
            ipr_plafond_taux=Decimal("1"),
            cnss_taux_salarie=Decimal("0.05"),
        )
        # 100 000 * 10% + (150 000 - 100 000) * 20% = 10 000 + 10 000 = 20 000
        assert compute_ipr(Decimal("150000"), params) == Decimal("20000.00")

    def test_plancher_et_plafond_personnalises(self):
        params = PayrollParams(ipr_plancher=Decimal("500"), ipr_plafond_taux=Decimal("0.10"))
        # petit revenu -> plancher custom (500) au lieu du défaut (2000) ;
        # le plafond (10% de 10 000 = 1 000) ne contraint pas ici.
        assert compute_ipr(Decimal("10000"), params) == Decimal("500.00")
        # gros revenu -> plafond custom (10%) au lieu du défaut (30%)
        revenu = Decimal("10000000")
        assert compute_ipr(revenu, params) == (revenu * Decimal("0.10")).quantize(Decimal("0.01"))


class TestComputeCnssSalarie:
    def test_taux_par_defaut_5_pourcent(self):
        assert DEFAULT_CNSS_TAUX_SALARIE == Decimal("0.05")
        assert compute_cnss_salarie(Decimal("1000")) == Decimal("50.00")

    def test_revenu_nul(self):
        assert compute_cnss_salarie(Decimal("0")) == Decimal("0")

    def test_taux_personnalise(self):
        params = PayrollParams(cnss_taux_salarie=Decimal("0.08"))
        assert compute_cnss_salarie(Decimal("1000"), params) == Decimal("80.00")


class TestComputeSlipDeductions:
    def test_devise_cdf_pas_de_conversion(self):
        result = compute_slip_deductions(
            salaire_base=Decimal("500000"),
            total_primes=Decimal("0"),
            devise="CDF",
            taux_change_interne=None,
        )
        assert result["ipr"] == Decimal("55560.00")
        assert result["cnss_salarie"] == Decimal("25000.00")
        assert result["total_retenues"] == Decimal("80560.00")
        assert result["net_a_payer"] == Decimal("419440.00")

    def test_devise_usd_convertit_via_taux_change_interne(self):
        result = compute_slip_deductions(
            salaire_base=Decimal("300"),
            total_primes=Decimal("0"),
            devise="USD",
            taux_change_interne=Decimal("2500"),
        )
        # revenu en CDF = 300 * 2500 = 750 000
        # IPR CDF = 4 860 + (750 000 - 162 000) * 15% = 4 860 + 88 200 = 93 060
        # IPR USD = 93 060 / 2500 = 37.224 -> 37.22
        assert result["ipr"] == Decimal("37.22")
        assert result["cnss_salarie"] == Decimal("15.00")
        assert result["total_retenues"] == Decimal("52.22")
        assert result["net_a_payer"] == Decimal("247.78")

    def test_devise_usd_sans_taux_change_leve_une_erreur(self):
        with pytest.raises(ValueError):
            compute_slip_deductions(
                salaire_base=Decimal("300"),
                total_primes=Decimal("0"),
                devise="USD",
                taux_change_interne=None,
            )
        with pytest.raises(ValueError):
            compute_slip_deductions(
                salaire_base=Decimal("300"),
                total_primes=Decimal("0"),
                devise="USD",
                taux_change_interne=Decimal("0"),
            )

    def test_primes_augmentent_le_revenu_imposable(self):
        sans_primes = compute_slip_deductions(
            salaire_base=Decimal("500000"), total_primes=Decimal("0"), devise="CDF", taux_change_interne=None
        )
        avec_primes = compute_slip_deductions(
            salaire_base=Decimal("500000"), total_primes=Decimal("100000"), devise="CDF", taux_change_interne=None
        )
        assert avec_primes["ipr"] > sans_primes["ipr"]
        assert avec_primes["cnss_salarie"] > sans_primes["cnss_salarie"]

    def test_params_personnalises_sont_utilises(self):
        params = PayrollParams(
            devise_bareme="CDF",
            ipr_brackets=[{"lower": Decimal("0"), "upper": None, "rate": Decimal("0.10")}],
            ipr_plancher=Decimal("0"),
            ipr_plafond_taux=Decimal("1"),
            cnss_taux_salarie=Decimal("0.03"),
        )
        result = compute_slip_deductions(
            salaire_base=Decimal("100000"),
            total_primes=Decimal("0"),
            devise="CDF",
            taux_change_interne=None,
            params=params,
        )
        assert result["ipr"] == Decimal("10000.00")
        assert result["cnss_salarie"] == Decimal("3000.00")


class TestParamsFromSettingsRow:
    def test_row_none_renvoie_les_defauts(self):
        params = params_from_settings_row(None)
        assert params == PayrollParams()

    def test_row_est_converti_correctement(self):
        row = type(
            "Row",
            (),
            {
                "devise_bareme": "CDF",
                "ipr_brackets": [
                    {"lower": "0", "upper": "100000", "rate": "0.10"},
                    {"lower": "100000", "upper": None, "rate": "0.20"},
                ],
                "ipr_plancher": "500",
                "ipr_plafond_taux": "0.25",
                "cnss_taux_salarie": "0.06",
            },
        )()
        params = params_from_settings_row(row)
        assert params.devise_bareme == "CDF"
        assert params.ipr_plancher == Decimal("500")
        assert params.ipr_plafond_taux == Decimal("0.25")
        assert params.cnss_taux_salarie == Decimal("0.06")
        assert params.ipr_brackets[0]["rate"] == Decimal("0.10")
        assert params.ipr_brackets[1]["upper"] is None
