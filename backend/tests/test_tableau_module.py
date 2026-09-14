"""Tests du module Tableau (secrétariat).

Couvre :
  - detect_anomalies / compute_analyse_stats (règles à jour : seuil 120h,
    critères par catégorie)
  - verdict.evaluer : INSCRIT / NON INSCRIT / À DÉLIBÉRER par section,
    exemptions (nouveau membre, âge) et réglages configurables
  - excel_import.parse_excel_bytes : multi-feuilles, en-tête décalé, mapping
  - exporter.build_workbook : sortie par section, numérotation, sociétés
    sans colonne formation
  - comparison.compare_exercices
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from datetime import date
import uuid

import openpyxl
import pytest
from sqlalchemy import select

from sqlalchemy import event, text

from fastapi import HTTPException

from app.models.organisation import Organisation
from app.modules.secretariat.tableau import verdict as V
from app.modules.secretariat.tableau.analyzer import (
    HEURES_FORCO_MIN,
    compute_analyse_stats,
    detect_anomalies,
)
from app.modules.secretariat.tableau.comparison import compare_exercices
from app.modules.secretariat.tableau.excel_import import parse_excel_bytes
from app.modules.secretariat.tableau.exporter import build_workbook
from app.modules.secretariat.tableau.models import TableauAnalyse, TableauDossier
from app.modules.secretariat.tableau import router as tableau_router
from app.modules.secretariat.tableau.repository import get_stats, list_anomalies
from app.modules.secretariat.tableau.schemas import (
    TableauDecisionCreate,
    TableauDossierCorrection,
    TableauPVCreate,
)
from app.modules.secretariat.tableau.models import TableauDecision
from app.modules.secretariat.tableau.report_generator import generate_pv
from app.modules.secretariat.tableau.service import (
    _appliquer_decisions,
    _cle_decision,
    _normaliser_correction,
    _norm_numero_ordre,
    _valider_lignes,
    corriger_dossier,
    create_decision,
    create_pv,
    export_tableau,
    get_base_tableau,
    import_excel,
    run_analyse,
    run_analyse_base,
    valider_date_situation,
)


def _dossier(**overrides) -> dict:
    base = {
        "id": 1,
        "numero_ordre": "EC/16.00001",
        "nom": "Dupont",
        "prenom": "Jean",
        "categorie": "EC Cabinet",
        "cotisation_payee": True,
        "heures_forco": 120.0,
        "assurance": True,
        "chiffre_affaires": True,
        "anciennete": "Ancien",
        "age": 45,
    }
    base.update(overrides)
    return base


class TestDetectAnomalies:
    def test_dossier_complet_ne_genere_aucune_anomalie(self):
        assert detect_anomalies([_dossier()]) == []

    def test_doublon_nom_prenom_insensible_a_la_casse(self):
        dossiers = [
            _dossier(id=1, nom="Dupont", prenom="Jean"),
            _dossier(id=2, nom="DUPONT", prenom="jean"),
        ]
        doublons = [a for a in detect_anomalies(dossiers) if a["type_anomalie"] == "doublon"]
        assert len(doublons) == 1
        assert doublons[0]["dossier_id"] == 2

    def test_nom_manquant_signale_dossier_incomplet(self):
        types = {a["type_anomalie"] for a in detect_anomalies([_dossier(nom="")])}
        assert "dossier_incomplet" in types

    def test_categorie_inconnue(self):
        anomalies = detect_anomalies([_dossier(categorie="Autre")])
        assert any(a["type_anomalie"] == "categorie_inconnue" for a in anomalies)

    def test_cotisation_non_payee(self):
        anomalies = detect_anomalies([_dossier(cotisation_payee=False)])
        assert any(a["type_anomalie"] == "cotisation_non_payee" and a["gravite"] == "high" for a in anomalies)

    def test_heures_insuffisantes_sous_120(self):
        anomalies = detect_anomalies([_dossier(heures_forco=50.0)])
        assert any(a["type_anomalie"] == "heures_forco_insuffisantes" for a in anomalies)

    def test_heures_au_seuil_120_pas_anomalie(self):
        anomalies = detect_anomalies([_dossier(heures_forco=HEURES_FORCO_MIN)])
        assert not any(a["type_anomalie"] == "heures_forco_insuffisantes" for a in anomalies)

    def test_nouveau_membre_exempte_de_formation(self):
        # 0h mais nouveau -> pas d'anomalie de formation
        anomalies = detect_anomalies([_dossier(heures_forco=0.0, anciennete="Nouveau")])
        assert not any("heures_forco" in a["type_anomalie"] for a in anomalies)

    def test_assurance_requise_seulement_pour_independant(self):
        # Cabinet sans assurance : pas d'anomalie assurance
        cab = detect_anomalies([_dossier(categorie="EC Cabinet", assurance=False)])
        assert not any("assurance" in a["type_anomalie"] for a in cab)
        # Indépendant sans assurance : anomalie
        indep = detect_anomalies([_dossier(categorie="EC Indépendant", assurance=False)])
        assert any(a["type_anomalie"] == "assurance_manquante" for a in indep)

    def test_chiffre_affaires_non_declare_independant(self):
        anomalies = detect_anomalies([_dossier(categorie="EC Indépendant", chiffre_affaires=False)])
        assert any(a["type_anomalie"] == "chiffre_affaires_non_declare" for a in anomalies)


class TestVerdict:
    def test_cabinet_inscrit(self):
        assert V.evaluer(_dossier())["conclusion"] == V.INSCRIT

    def test_cabinet_non_inscrit_formation(self):
        assert V.evaluer(_dossier(heures_forco=50.0))["conclusion"] == V.NON_INSCRIT

    def test_cotisation_impayee_non_inscrit(self):
        assert V.evaluer(_dossier(cotisation_payee=False))["conclusion"] == V.NON_INSCRIT

    def test_independant_tous_criteres(self):
        d = _dossier(categorie="EC Indépendant")
        assert V.evaluer(d)["conclusion"] == V.INSCRIT
        assert V.evaluer({**d, "chiffre_affaires": False})["conclusion"] == V.NON_INSCRIT

    def test_societe_sans_formation(self):
        # société : pas de critère formation, 0h ne bloque pas
        d = _dossier(categorie="Société", heures_forco=0.0, chiffre_affaires=True, assurance=True)
        assert V.evaluer(d)["conclusion"] == V.INSCRIT

    def test_nouveau_membre_par_numero_ordre(self):
        # exercice 2026, ordre 2025 -> nouveau -> exempté formation
        d = _dossier(numero_ordre="EC/25.00604", anciennete="Ancien", heures_forco=0.0)
        assert V.evaluer(d, 2026)["conclusion"] == V.INSCRIT

    def test_stagiaire_non_applicable(self):
        assert V.evaluer(_dossier(categorie="Stagiaire"))["conclusion"] == V.NON_APPLICABLE

    def test_age_action_a_deliberer(self):
        d = _dossier(heures_forco=0.0, age=65)
        assert V.evaluer(d, 2026)["conclusion"] == V.A_DELIBERER

    def test_age_action_inscrit_direct(self):
        d = _dossier(heures_forco=0.0, age=65)
        reg = V.TableauReglages(age_action="inscrit")
        assert V.evaluer(d, 2026, reg)["conclusion"] == V.INSCRIT

    def test_age_seuil_configurable(self):
        # seuil 99 : un membre de 65 ans n'est plus exempté
        d = _dossier(heures_forco=0.0, age=65)
        reg = V.TableauReglages(age_seuil=99)
        assert V.evaluer(d, 2026, reg)["conclusion"] == V.NON_INSCRIT

    def test_seuil_heures_configurable(self):
        d = _dossier(heures_forco=80.0)
        reg = V.TableauReglages(heures_formation_min=60)
        assert V.evaluer(d, 2026, reg)["conclusion"] == V.INSCRIT


def _make_workbook_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EC EN CABINET 25"
    ws.append([None] * 3)
    ws.append([None, "CONSEIL PROVINCIAL DE KINSHASA"])
    ws.append([None, "SECTION A1 : EXPERTS-COMPTABLES EN CABINET"])
    ws.append([None, "N°", "N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Sexe",
               "N° TELEPHONE", "E-MAIL", "CABINET D'ATTACHE", "Ancienneté",
               "Cotisation", "H.Formation", "Conclusion", "NHV"])
    ws.append([None, 1, "EC/16.00001", "ABEDI ASSAD", "M", "(+243)895873021",
               "a@b.cd", "FICADEX", "Ancien", "OUI", "OUI", "INSCRIT", 120])
    ws.append([None, 2, "EC/18.00003", "ADRUPIAKO Emmanuel", "M", "(+243)818112782",
               "e@d.cd", "AUDIGEC", "Ancien", "OUI", "NON", "NON INSCRIT", 0])

    ws2 = wb.create_sheet("EC Indépendant 25")
    ws2.append([None] * 3)
    ws2.append([None, "CONSEIL PROVINCIAL"])
    ws2.append([None, "SECTION A2"])
    ws2.append([None, "N°", "N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Sexe",
                "N° TELEPHONE", "E-MAIL", "NIF", "Ancienneté", "Cotisation",
                "Assurance Valide", "H.Formation", "C d'affaire", "Conclusion", "NHV"])
    ws2.append([None, 1, "EC/17.00002", "ABISA Lydie", "F", "(+243)859437431",
                "l@m.cd", "A1810696X", "Ancien", "OUI", "OUI", "OUI", "OUI", "INSCRIT", 122])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_import_bytes(*rows: dict, sheet_title: str = "EC EN CABINET 26") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(["N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Sexe", "N° TELEPHONE", "E-MAIL",
               "CABINET D'ATTACHE", "Ancienneté", "Cotisation", "NHV", "Assurance Valide",
               "C d'affaire", "NIF"])
    for row in rows:
        ws.append([
            row.get("numero_ordre"),
            row.get("nom", "KABAMBA Jean"),
            row.get("sexe", "M"),
            row.get("telephone"),
            row.get("email"),
            row.get("cabinet", "CABINET ALPHA"),
            row.get("anciennete", "Ancien"),
            row.get("cotisation", "NON"),
            row.get("heures", 60),
            row.get("assurance", "OUI"),
            row.get("chiffre_affaires", "OUI"),
            row.get("nif"),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _CompteurRequetes:
    """Compte les allers-retours SQL réellement émis pendant un bloc."""

    def __init__(self, session):
        self.engine = session.bind.sync_engine
        self.total = 0

    def _on_execute(self, *_args, **_kwargs):
        self.total += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._on_execute)
        return False


class TestExcelImport:
    def test_parse_multi_feuilles_et_categorie_par_feuille(self):
        rows, errors = parse_excel_bytes(_make_workbook_bytes(), "2026")
        assert errors == []
        assert len(rows) == 3
        cats = {r["categorie"] for r in rows}
        assert cats == {"EC Cabinet", "EC Indépendant"}

    def test_mapping_colonnes(self):
        rows, _ = parse_excel_bytes(_make_workbook_bytes(), "2026")
        r0 = next(r for r in rows if r["numero_ordre"] == "EC/16.00001")
        assert r0["nom"] == "ABEDI ASSAD"
        assert r0["cotisation_payee"] is True
        assert r0["heures_forco"] == 120
        assert r0["cabinet"] == "FICADEX"

    def test_champs_delibération_en_colonnes(self):
        rows, _ = parse_excel_bytes(_make_workbook_bytes(), "2026")
        indep = next(r for r in rows if r["categorie"] == "EC Indépendant")
        assert indep["assurance"] is True
        assert indep["chiffre_affaires"] is True
        assert indep["nif"] == "A1810696X"


class TestExporter:
    def test_export_par_section_avec_numerotation(self):
        rows, _ = parse_excel_bytes(_make_workbook_bytes(), "2026")
        content = build_workbook(rows, "2026", V.TableauReglages(), 2026)
        wb = openpyxl.load_workbook(io.BytesIO(content))
        assert "EC EN CABINET" in wb.sheetnames
        ws = wb["EC EN CABINET"]
        # en-tête en ligne 5, première donnée ligne 6, N° séquentiel = 1
        assert ws.cell(5, 1).value == "N°"
        assert ws.cell(6, 1).value == 1

    def test_societe_sans_colonne_formation(self):
        wb = openpyxl.Workbook()
        content = build_workbook(
            [{"categorie": "Société", "numero_ordre": "SEC/18.00001", "nom": "ABN SAS",
              "cotisation_payee": True, "assurance": True,
              "raw_data": {"chiffre_affaires": True, "gerant": "X"}}],
            "2026", V.TableauReglages(), 2026,
        )
        wb = openpyxl.load_workbook(io.BytesIO(content))
        ws = wb["SOCIETES"]
        headers = [ws.cell(5, c).value for c in range(1, ws.max_column + 1)]
        assert not any(h and "formation" in str(h).lower() for h in headers)
        assert "Chiffre d'affaires" in headers


class TestImportValidation:
    def test_ligne_valide_sans_avertissement(self):
        rows = [{"numero_ordre": "EC/16.00001", "nom": "Dupont", "categorie": "EC Cabinet"}]
        assert _valider_lignes(rows) == []

    def test_numero_ordre_manquant(self):
        rows = [{"numero_ordre": None, "nom": "Dupont", "categorie": "EC Cabinet"}]
        errs = _valider_lignes(rows)
        assert any(e["champ"] == "numero_ordre" for e in errs)

    def test_categorie_inconnue(self):
        rows = [{"numero_ordre": "EC/16.00001", "nom": "Dupont", "categorie": "Inconnu"}]
        errs = _valider_lignes(rows)
        assert any(e["champ"] == "categorie" for e in errs)


class TestComputeAnalyseStats:
    def test_stats_sur_dossiers_complets(self):
        dossiers = [_dossier(id=1), _dossier(id=2, nom="Martin", prenom="Alice")]
        stats = compute_analyse_stats(dossiers, detect_anomalies(dossiers))
        assert stats["total_dossiers"] == 2
        assert stats["anomalies_count"] == 0

    def test_stats_conclusions_dans_stats_json(self):
        dossiers = [_dossier(id=1), _dossier(id=2, nom="M", cotisation_payee=False)]
        verdicts = {d["id"]: V.evaluer(d, 2026) for d in dossiers}
        stats = compute_analyse_stats(dossiers, detect_anomalies(dossiers), verdicts)
        concl = stats["stats_json"]["conclusions"]
        assert concl["inscrits"] == 1
        assert concl["non_inscrits"] == 1

    def test_stagiaire_et_societe_n_exigent_pas_de_formation(self):
        dossiers = [
            _dossier(id=1, categorie="Stagiaire", cotisation_payee=None, heures_forco=None, assurance=None),
            _dossier(id=2, categorie="Société", nom="Cabinet", heures_forco=None),
        ]
        anomalies = detect_anomalies(dossiers)
        stats = compute_analyse_stats(dossiers, anomalies)

        assert stats["dossiers_incomplets"] == 0

    def test_champ_requis_non_renseigne_compte_une_seule_fois(self):
        dossier = _dossier(
            id=1,
            categorie="EC Indépendant",
            cotisation_payee=None,
            heures_forco=None,
            assurance=None,
            chiffre_affaires=None,
        )
        stats = compute_analyse_stats([dossier], detect_anomalies([dossier]))

        assert stats["dossiers_incomplets"] == 1
        assert stats["dossiers_complets"] == 0


class TestCompareExercices:
    def test_dossiers_identiques_sont_en_commun(self):
        dossiers = [_dossier(id=1)]
        result = compare_exercices(dossiers, dossiers, "2025", "2026")
        assert result["dossiers_en_commun"] == 1
        assert result["nouveaux_dans_b"] == 0

    def test_nouveau_dossier_dans_exercice_b(self):
        a = [_dossier(id=1, nom="Dupont", prenom="Jean")]
        b = [
            _dossier(id=1, nom="Dupont", prenom="Jean"),
            _dossier(id=2, numero_ordre="EC/20.00002", nom="Martin", prenom="Alice"),
        ]
        result = compare_exercices(a, b, "2025", "2026")
        assert result["nouveaux_dans_b"] == 1

    def test_changement_de_categorie_est_detecte(self):
        a = [_dossier(id=1, nom="Dupont", prenom="Jean", categorie="EC Salarié")]
        b = [_dossier(id=1, nom="Dupont", prenom="Jean", categorie="EC Indépendant")]
        result = compare_exercices(a, b, "2025", "2026")
        assert result["changements_categorie"] == 1

    def test_matching_ignore_casse_et_espaces(self):
        a = [_dossier(id=1, numero_ordre=None, nom="  Dupont ", prenom=" Jean")]
        b = [_dossier(id=1, numero_ordre=None, nom="DUPONT", prenom="jean")]
        result = compare_exercices(a, b, "2025", "2026")
        assert result["dossiers_en_commun"] == 1

    def test_details_ne_sont_pas_tronques(self):
        result = compare_exercices(
            [],
            [_dossier(id=i, numero_ordre=f"EC/26.{i:05d}") for i in range(125)],
            "2025",
            "2026",
        )

        assert result["nouveaux_dans_b"] == 125
        assert len(result["details"]) == 125


class TestTableauSituationCourante:
    """Le Tableau garde tous les imports, mais une seule situation fait foi par membre."""

    @pytest.mark.asyncio
    async def test_premier_import_constitue_la_base_et_calcule_l_anciennete(self, db_session, test_admin_user):
        numero = "EC/18.00062"
        outcome = await import_excel(
            db_session,
            test_admin_user,
            test_admin_user.organisation_id,
            "tableau-initial.xlsx",
            _make_import_bytes({"numero_ordre": numero, "heures": 60}),
            "2026",
        )
        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert outcome.imp.date_situation is not None
        assert dossier.annee_inscription == 2018
        assert dossier.anciennete_annees == 8
        assert dossier.raw_data["situation"]["courante"] is True

    @pytest.mark.asyncio
    async def test_numero_d_ordre_normalise_sans_deformer_sa_structure(self, db_session, test_admin_user):
        outcome = await import_excel(
            db_session,
            test_admin_user,
            test_admin_user.organisation_id,
            "numero-sale.xlsx",
            _make_import_bytes({"numero_ordre": "  ec/18.00063 "}),
            "2026",
        )
        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert dossier.numero_ordre == "EC/18.00063"

    @pytest.mark.asyncio
    async def test_import_suivant_actualise_sans_sommer_ni_dupliquer(self, db_session, test_admin_user):
        numero = "EC/18.00064"
        await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "formation-1.xlsx",
            _make_import_bytes({"numero_ordre": numero, "heures": 60, "cotisation": "NON"}), "2026",
            date_situation=date(2026, 1, 5),
        )
        await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "formation-2.xlsx",
            _make_import_bytes({"numero_ordre": numero, "heures": 90, "cotisation": "OUI"}), "2026",
            date_situation=date(2026, 3, 15),
        )
        dossiers = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.numero_ordre == numero)
        )).scalars().all()
        courantes = [d for d in dossiers if d.raw_data["situation"]["courante"]]

        # Les deux situations sont conservées, une seule fait foi, et rien n'est cumulé.
        assert len(dossiers) == 2
        assert len(courantes) == 1
        assert float(courantes[0].heures_forco) == 90
        assert courantes[0].cotisation_payee is True

    @pytest.mark.asyncio
    async def test_trois_imports_successifs_designent_le_plus_recent(self, db_session, test_admin_user):
        numero = "EC/18.00070"
        for file_name, situation_date, heures in [
            ("formation-jan.xlsx", date(2026, 1, 5), 60),
            ("formation-mar.xlsx", date(2026, 3, 15), 90),
            ("formation-jun.xlsx", date(2026, 6, 20), 120),
        ]:
            await import_excel(
                db_session, test_admin_user, test_admin_user.organisation_id, file_name,
                _make_import_bytes({"numero_ordre": numero, "heures": heures}), "2026",
                date_situation=situation_date,
            )
        dossiers = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.numero_ordre == numero)
        )).scalars().all()
        courantes = [d for d in dossiers if d.raw_data["situation"]["courante"]]

        assert len(dossiers) == 3
        assert len(courantes) == 1
        assert float(courantes[0].heures_forco) == 120

    @pytest.mark.asyncio
    async def test_reimport_d_un_ancien_fichier_ne_retrograde_pas_la_situation(self, db_session, test_admin_user):
        numero = "EC/18.00071"
        await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "formation-jun.xlsx",
            _make_import_bytes({"numero_ordre": numero, "heures": 120}), "2026",
            date_situation=date(2026, 6, 20),
        )
        ancien = await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "formation-mar-reimport.xlsx",
            _make_import_bytes({"numero_ordre": numero, "heures": 90}), "2026",
            date_situation=date(2026, 3, 15),
        )
        dossiers = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.numero_ordre == numero)
        )).scalars().all()
        courantes = [d for d in dossiers if d.raw_data["situation"]["courante"]]
        dossier_ancien = next(d for d in dossiers if d.import_id == ancien.imp.id)

        # Téléversé en dernier, mais plus ancien au sens métier : il ne prend pas la main.
        assert len(dossiers) == 2
        assert float(courantes[0].heures_forco) == 120
        assert dossier_ancien.raw_data["situation"]["courante"] is False

    @pytest.mark.asyncio
    async def test_reimport_ancienne_cotisation_non_ne_retrograde_pas(self, db_session, test_admin_user):
        numero = "EC/18.00072"
        await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "cotisation-recente.xlsx",
            _make_import_bytes({"numero_ordre": numero, "cotisation": "OUI"}), "2026",
            date_situation=date(2026, 6, 20),
        )
        await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "cotisation-ancienne.xlsx",
            _make_import_bytes({"numero_ordre": numero, "cotisation": "NON"}), "2026",
            date_situation=date(2026, 3, 15),
        )
        courantes = [
            d for d in (await db_session.execute(
                select(TableauDossier).where(TableauDossier.numero_ordre == numero)
            )).scalars().all()
            if d.raw_data["situation"]["courante"]
        ]

        assert len(courantes) == 1
        assert courantes[0].cotisation_payee is True

    @pytest.mark.asyncio
    async def test_deux_lignes_du_meme_membre_designent_la_derniere(self, db_session, test_admin_user):
        numero = "EC/18.00073"
        outcome = await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "doublon-interne.xlsx",
            _make_import_bytes(
                {"numero_ordre": numero, "heures": 40},
                {"numero_ordre": numero, "heures": 95},
            ),
            "2026",
        )
        dossiers = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalars().all()
        courantes = [d for d in dossiers if d.raw_data["situation"]["courante"]]

        assert len(dossiers) == 2
        assert len(courantes) == 1
        assert float(courantes[0].heures_forco) == 95

    @pytest.mark.asyncio
    async def test_ligne_sans_numero_d_ordre_reste_importee_mais_non_rattachee(self, db_session, test_admin_user):
        outcome = await import_excel(
            db_session, test_admin_user, test_admin_user.organisation_id, "sans-numero.xlsx",
            _make_import_bytes({"numero_ordre": None, "nom": "MUKENDI Paul"}), "2026",
        )
        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        # L'Agent Tableau doit pouvoir corriger la ligne, donc elle n'est pas rejetée.
        assert dossier.nom == "MUKENDI Paul"
        assert dossier.raw_data["situation"]["courante"] is False

    @pytest.mark.asyncio
    async def test_le_cout_sql_ne_croit_pas_avec_le_nombre_de_lignes(self, db_session, test_admin_user):
        """Un import de 200 lignes ne doit pas coûter 200 allers-retours SQL."""
        def _fichier(debut: int, nombre: int) -> bytes:
            return _make_import_bytes(*[
                {"numero_ordre": f"EC/17.{debut + i:05d}", "heures": 60}
                for i in range(nombre)
            ])

        with _CompteurRequetes(db_session) as petit:
            await import_excel(db_session, test_admin_user, test_admin_user.organisation_id,
                               "cout-2.xlsx", _fichier(100, 2), "2026")
        with _CompteurRequetes(db_session) as grand:
            await import_excel(db_session, test_admin_user, test_admin_user.organisation_id,
                               "cout-20.xlsx", _fichier(200, 20), "2026")

        assert grand.total - petit.total < 18


class TestBaseTableauConsolidee:
    """La base du Tableau : une situation par membre, tous imports de l'exercice confondus."""

    async def _importer(self, db, user, org_id, fichier, situation, **kw):
        return await import_excel(db, user, org_id, fichier,
                                  _make_import_bytes(*kw["rows"]), kw.get("exercice", "2026"),
                                  date_situation=situation)

    @pytest.mark.asyncio
    async def test_la_base_retient_la_situation_la_plus_recente_de_chaque_membre(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "jan.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10001", "nom": "ALPHA Jean", "heures": 60},
            {"numero_ordre": "EC/18.10002", "nom": "BETA Marie", "heures": 20},
        ), "2031", date_situation=date(2031, 1, 5))
        await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10001", "nom": "ALPHA Jean", "heures": 120},
        ), "2031", date_situation=date(2031, 6, 20))

        base = await get_base_tableau(db_session, [org], exercice="2031")
        par_numero = {d.numero_ordre: d for d in base["dossiers"]}

        # Un seul ALPHA malgré deux imports, et c'est la situation de juin.
        assert base["total_membres"] == 2
        assert float(par_numero["EC/18.10001"].heures_forco) == 120
        assert float(par_numero["EC/18.10002"].heures_forco) == 20
        assert base["imports_couverts"] == sorted(base["imports_couverts"])

    @pytest.mark.asyncio
    async def test_un_reimport_plus_ancien_ne_fait_pas_reculer_la_base(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10010", "heures": 120},
        ), "2032", date_situation=date(2032, 6, 20))
        await import_excel(db_session, test_admin_user, org, "mars-reimport.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10010", "heures": 90},
        ), "2032", date_situation=date(2032, 3, 15))

        base = await get_base_tableau(db_session, [org], exercice="2032")

        assert base["total_membres"] == 1
        assert float(base["dossiers"][0].heures_forco) == 120

    @pytest.mark.asyncio
    async def test_la_base_concorde_avec_le_marqueur_pose_a_l_import(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        for situation, heures in [(date(2033, 1, 5), 60), (date(2033, 3, 15), 90), (date(2033, 6, 20), 120)]:
            await import_excel(db_session, test_admin_user, org, f"f{heures}.xlsx", _make_import_bytes(
                {"numero_ordre": "EC/18.10020", "heures": heures},
            ), "2033", date_situation=situation)

        base = await get_base_tableau(db_session, [org], exercice="2033")
        marques = [
            d for d in (await db_session.execute(
                select(TableauDossier).where(TableauDossier.exercice == "2033")
            )).scalars().all()
            if d.raw_data["situation"]["courante"]
        ]

        # Les deux mécanismes doivent désigner exactement la même ligne.
        assert [d.id for d in base["dossiers"]] == [d.id for d in marques]

    @pytest.mark.asyncio
    async def test_les_lignes_sans_numero_d_ordre_restent_toutes_presentes(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "sans-numero.xlsx", _make_import_bytes(
            {"numero_ordre": None, "nom": "MUKENDI Paul"},
            {"numero_ordre": None, "nom": "NGOY Sarah"},
            {"numero_ordre": "EC/18.10030", "nom": "ALPHA Jean"},
        ), "2034")

        base = await get_base_tableau(db_session, [org], exercice="2034")

        # Faute de n° d'ordre, rien ne permet de les rapprocher : elles restent à corriger.
        assert base["total_membres"] == 3
        assert base["membres_sans_numero"] == 2

    @pytest.mark.asyncio
    async def test_la_base_d_un_conseil_ignore_celle_d_un_autre(self, db_session, test_admin_user, test_organisation):
        org = test_admin_user.organisation_id
        autre = Organisation(nom="Conseil Provincial Test", slug=f"cp-test-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        await import_excel(db_session, test_admin_user, org, "conseil-a.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10040", "nom": "ALPHA Jean"},
        ), "2035")
        await import_excel(db_session, test_admin_user, autre.id, "conseil-b.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10041", "nom": "BETA Marie"},
        ), "2035")

        base_a = await get_base_tableau(db_session, [org], exercice="2035")
        base_nationale = await get_base_tableau(db_session, [org, autre.id], exercice="2035", national=True)

        assert [d.numero_ordre for d in base_a["dossiers"]] == ["EC/18.10040"]
        assert base_nationale["total_membres"] == 2
        assert sorted(base_nationale["organisations"]) == sorted([org, autre.id])

    @pytest.mark.asyncio
    async def test_un_meme_numero_dans_deux_conseils_reste_deux_lignes(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        autre = Organisation(nom="Conseil Provincial Bis", slug=f"cp-bis-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        for organisation_id, heures in [(org, 60), (autre.id, 100)]:
            await import_excel(db_session, test_admin_user, organisation_id, "double.xlsx", _make_import_bytes(
                {"numero_ordre": "EC/18.10050", "nom": "ALPHA Jean", "heures": heures},
            ), "2036")

        nationale = await get_base_tableau(db_session, [org, autre.id], exercice="2036", national=True)

        # Chaque conseil est indépendant : la consolidation n'écrase pas l'un par l'autre.
        assert nationale["total_membres"] == 2
        assert sorted(float(d.heures_forco) for d in nationale["dossiers"]) == [60.0, 100.0]

    @pytest.mark.asyncio
    async def test_sans_exercice_precise_la_base_prend_le_dernier_import(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "vieux.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10060"},
        ), "2037")
        await import_excel(db_session, test_admin_user, org, "recent.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.10061"},
        ), "2038")

        base = await get_base_tableau(db_session, [org])

        assert base["exercice"] == "2038"
        assert [d.numero_ordre for d in base["dossiers"]] == ["EC/18.10061"]

    @pytest.mark.asyncio
    async def test_base_vide_quand_aucun_import(self, db_session, test_admin_user):
        autre = Organisation(nom="Conseil Sans Import", slug=f"cp-vide-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        base = await get_base_tableau(db_session, [autre.id])

        assert base["exercice"] == ""
        assert base["dossiers"] == []


class TestReprisesEntreImports:
    """Une actualisation dit ce qui change ; ce qu'elle tait ne doit pas disparaître."""

    @pytest.mark.asyncio
    async def test_cellule_vide_reprend_la_derniere_valeur_connue(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20001", "telephone": "+243899000001", "email": "jean@onec.cd", "nif": "A12345"},
        ), "2040", date_situation=date(2040, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20001", "telephone": None, "email": None, "nif": None},
        ), "2040", date_situation=date(2040, 6, 20))

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert dossier.telephone == "+243899000001"
        assert dossier.email == "jean@onec.cd"
        assert dossier.nif == "A12345"
        assert outcome.reprises == 3
        assert {r["champ"] for r in dossier.raw_data["situation"]["reprises"]} == {"telephone", "email", "nif"}

    @pytest.mark.asyncio
    async def test_un_non_explicite_n_est_pas_une_cellule_vide(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20002", "cotisation": "OUI", "assurance": "OUI"},
        ), "2041", date_situation=date(2041, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20002", "cotisation": "NON", "assurance": "NON"},
        ), "2041", date_situation=date(2041, 6, 20))

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        # « NON » infirme la valeur précédente : il ne doit jamais être écrasé par elle.
        assert dossier.cotisation_payee is False
        assert dossier.assurance is False
        assert outcome.reprises == 0

    @pytest.mark.asyncio
    async def test_zero_heure_explicite_n_est_pas_une_cellule_vide(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20003", "heures": 90},
        ), "2042", date_situation=date(2042, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20003", "heures": 0},
        ), "2042", date_situation=date(2042, 6, 20))

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert float(dossier.heures_forco) == 0

    @pytest.mark.asyncio
    async def test_cellule_vide_reprend_les_heures_et_la_cotisation(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20004", "heures": 90, "cotisation": "OUI"},
        ), "2043", date_situation=date(2043, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20004", "heures": None, "cotisation": None},
        ), "2043", date_situation=date(2043, 6, 20))

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert float(dossier.heures_forco) == 90
        assert dossier.cotisation_payee is True

    @pytest.mark.asyncio
    async def test_un_reimport_ancien_ne_reprend_pas_une_information_posterieure(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "jan.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20005", "telephone": "+243800000001"},
        ), "2044", date_situation=date(2044, 1, 5))
        await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20005", "telephone": "+243899999999"},
        ), "2044", date_situation=date(2044, 6, 20))
        mars = await import_excel(db_session, test_admin_user, org, "mars-reimport.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20005", "telephone": None},
        ), "2044", date_situation=date(2044, 3, 15))

        dossier_mars = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == mars.imp.id)
        )).scalar_one()
        base = await get_base_tableau(db_session, [org], exercice="2044")

        # Mars reprend janvier, pas juin : on ne fait pas remonter le futur dans le passé.
        assert dossier_mars.telephone == "+243800000001"
        # Et la base continue de présenter juin, la situation la plus récente.
        assert base["dossiers"][0].telephone == "+243899999999"

    @pytest.mark.asyncio
    async def test_le_premier_import_ne_reprend_rien(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(db_session, test_admin_user, org, "initial.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20006", "telephone": None},
        ), "2045")

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert outcome.reprises == 0
        assert dossier.telephone is None
        assert "reprises" not in dossier.raw_data.get("situation", {})

    @pytest.mark.asyncio
    async def test_la_reprise_ne_traverse_pas_les_conseils(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        autre = Organisation(nom="Conseil Reprise", slug=f"cp-rep-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        await import_excel(db_session, test_admin_user, org, "conseil-a.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20007", "telephone": "+243811111111"},
        ), "2046", date_situation=date(2046, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, autre.id, "conseil-b.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20007", "telephone": None},
        ), "2046", date_situation=date(2046, 6, 20))

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        assert dossier.telephone is None
        assert outcome.reprises == 0

    @pytest.mark.asyncio
    async def test_la_reprise_ne_traverse_pas_les_exercices(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "2047.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20008", "heures": 90},
        ), "2047")
        outcome = await import_excel(db_session, test_admin_user, org, "2048.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.20008", "heures": None},
        ), "2048")

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()

        # Les heures de formation se comptent par exercice : rien ne se reporte d'une année sur l'autre.
        assert dossier.heures_forco is None

    @pytest.mark.asyncio
    async def test_la_reprise_ne_coute_pas_une_requete_par_ligne(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id

        def _fichier(nombre: int, telephone: str | None) -> bytes:
            return _make_import_bytes(*[
                {"numero_ordre": f"EC/16.{30000 + i:05d}", "telephone": telephone}
                for i in range(nombre)
            ])

        await import_excel(db_session, test_admin_user, org, "socle.xlsx", _fichier(20, "+243800000000"),
                           "2049", date_situation=date(2049, 1, 5))

        with _CompteurRequetes(db_session) as compteur:
            outcome = await import_excel(db_session, test_admin_user, org, "maj.xlsx", _fichier(20, None),
                                         "2049", date_situation=date(2049, 6, 20))

        assert outcome.reprises == 20
        assert compteur.total < 15


class TestDecisionsDeLaCommission:
    """Ce que la commission a tranché ne doit pas être effacé par un import ni par l'analyse."""

    async def _dossier_de(self, db, import_id):
        return (await db.execute(
            select(TableauDossier).where(TableauDossier.import_id == import_id)
        )).scalar_one()

    async def _decider(self, db, user, org, dossier_id, decision, motif=None):
        return await create_decision(db, user, org, TableauDecisionCreate(
            dossier_id=dossier_id,
            type_decision="deliberation",
            decision=decision,
            motif=motif,
        ))

    @pytest.mark.asyncio
    async def test_un_nouvel_import_porte_la_memoire_de_la_decision(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30001", "heures": 60},
        ), "2050", date_situation=date(2050, 3, 15))
        dossier_mars = await self._dossier_de(db_session, mars.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier_mars.id, "INSCRIT", "Dérogation accordée")

        juin = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30001", "heures": 60},
        ), "2050", date_situation=date(2050, 6, 20))
        dossier_juin = await self._dossier_de(db_session, juin.imp.id)

        assert juin.decisions_reportees == 1
        assert dossier_juin.raw_data["decisions"][0]["decision"] == "INSCRIT"
        assert dossier_juin.raw_data["decisions"][0]["motif"] == "Dérogation accordée"

    @pytest.mark.asyncio
    async def test_la_decision_prime_sur_le_verdict_automatique(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30002", "heures": 10, "cotisation": "NON"},
        ), "2051", date_situation=date(2051, 3, 15))
        dossier_mars = await self._dossier_de(db_session, mars.imp.id)

        # Sans décision, le verdict automatique conclut au rejet.
        await run_analyse(db_session, test_admin_user, org, mars.imp.id)
        await db_session.refresh(dossier_mars)
        assert dossier_mars.conclusion == V.NON_INSCRIT

        await self._decider(db_session, test_admin_user, org, dossier_mars.id, "INSCRIT", "Cas de force majeure")
        await run_analyse(db_session, test_admin_user, org, mars.imp.id)
        await db_session.refresh(dossier_mars)

        assert dossier_mars.conclusion == V.INSCRIT
        assert dossier_mars.statut_dossier == V.INSCRIT
        assert dossier_mars.conclusion_motif == "Cas de force majeure"

    @pytest.mark.asyncio
    async def test_la_decision_suit_le_membre_sur_l_import_suivant(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30003", "heures": 10, "cotisation": "NON"},
        ), "2052", date_situation=date(2052, 3, 15))
        dossier_mars = await self._dossier_de(db_session, mars.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier_mars.id, "INSCRIT", "Dérogation")

        juin = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30003", "heures": 10, "cotisation": "NON"},
        ), "2052", date_situation=date(2052, 6, 20))
        await run_analyse(db_session, test_admin_user, org, juin.imp.id)
        dossier_juin = await self._dossier_de(db_session, juin.imp.id)
        await db_session.refresh(dossier_juin)

        # La délibération portait sur le dossier de mars, mais elle engage le membre.
        assert dossier_juin.conclusion == V.INSCRIT
        assert dossier_juin.raw_data["decision_appliquee"]["verdict_automatique"] == V.NON_INSCRIT

    @pytest.mark.asyncio
    async def test_une_divergence_est_signalee_sans_etre_appliquee(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30004", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2053", date_situation=date(2053, 3, 15))
        dossier_mars = await self._dossier_de(db_session, mars.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier_mars.id, "NON INSCRIT", "Procédure disciplinaire")

        await run_analyse(db_session, test_admin_user, org, mars.imp.id)
        await db_session.refresh(dossier_mars)
        trace = dossier_mars.raw_data["decision_appliquee"]

        # Les données diraient « inscrit » ; la commission a dit l'inverse et elle prime.
        assert dossier_mars.conclusion == V.NON_INSCRIT
        assert trace["verdict_automatique"] == V.INSCRIT
        assert trace["diverge"] is True

    @pytest.mark.asyncio
    async def test_la_decision_la_plus_recente_prime(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        imp = await import_excel(db_session, test_admin_user, org, "f.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30005", "heures": 10, "cotisation": "NON"},
        ), "2054")
        dossier = await self._dossier_de(db_session, imp.imp.id)

        await self._decider(db_session, test_admin_user, org, dossier.id, "INSCRIT", "Première délibération")
        await self._decider(db_session, test_admin_user, org, dossier.id, "NON INSCRIT", "Réexamen")
        await run_analyse(db_session, test_admin_user, org, imp.imp.id)
        await db_session.refresh(dossier)

        assert dossier.conclusion == V.NON_INSCRIT
        assert dossier.conclusion_motif == "Réexamen"

    @pytest.mark.asyncio
    async def test_une_decision_sans_conclusion_ne_tranche_rien(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        imp = await import_excel(db_session, test_admin_user, org, "f.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30006", "heures": 10, "cotisation": "NON"},
        ), "2055")
        dossier = await self._dossier_de(db_session, imp.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier.id, "reporté", "En attente de pièces")

        await run_analyse(db_session, test_admin_user, org, imp.imp.id)
        await db_session.refresh(dossier)

        # « Reporté » n'est pas une conclusion : le verdict automatique s'applique.
        assert dossier.conclusion == V.NON_INSCRIT
        assert "decision_appliquee" not in dossier.raw_data

    @pytest.mark.asyncio
    async def test_les_statistiques_refletent_la_decision(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        imp = await import_excel(db_session, test_admin_user, org, "f.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30007", "heures": 10, "cotisation": "NON"},
        ), "2056")
        dossier = await self._dossier_de(db_session, imp.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier.id, "INSCRIT", "Dérogation")

        analyse = await run_analyse(db_session, test_admin_user, org, imp.imp.id)

        # Les compteurs de l'analyse doivent dire la même chose que les dossiers.
        await db_session.refresh(dossier)
        conclusions = analyse.stats_json["conclusions"]
        assert dossier.conclusion == V.INSCRIT
        assert conclusions["inscrits"] == 1
        assert conclusions["non_inscrits"] == 0

    @pytest.mark.asyncio
    async def test_la_decision_ne_traverse_pas_les_conseils(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        autre = Organisation(nom="Conseil Decision", slug=f"cp-dec-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        ici = await import_excel(db_session, test_admin_user, org, "a.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30008", "heures": 10, "cotisation": "NON"},
        ), "2057")
        dossier_ici = await self._dossier_de(db_session, ici.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier_ici.id, "INSCRIT", "Dérogation locale")

        ailleurs = await import_excel(db_session, test_admin_user, autre.id, "b.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30008", "heures": 10, "cotisation": "NON"},
        ), "2057")
        await run_analyse(db_session, test_admin_user, autre.id, ailleurs.imp.id)
        dossier_ailleurs = await self._dossier_de(db_session, ailleurs.imp.id)
        await db_session.refresh(dossier_ailleurs)

        assert ailleurs.decisions_reportees == 0
        assert dossier_ailleurs.conclusion == V.NON_INSCRIT

    @pytest.mark.asyncio
    async def test_la_decision_ne_traverse_pas_les_exercices(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        precedent = await import_excel(db_session, test_admin_user, org, "2058.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30009", "heures": 10, "cotisation": "NON"},
        ), "2058")
        dossier_precedent = await self._dossier_de(db_session, precedent.imp.id)
        await self._decider(db_session, test_admin_user, org, dossier_precedent.id, "INSCRIT", "Dérogation 2058")

        suivant = await import_excel(db_session, test_admin_user, org, "2059.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.30009", "heures": 10, "cotisation": "NON"},
        ), "2059")
        await run_analyse(db_session, test_admin_user, org, suivant.imp.id)
        dossier_suivant = await self._dossier_de(db_session, suivant.imp.id)
        await db_session.refresh(dossier_suivant)

        # Chaque exercice se délibère pour lui-même.
        assert suivant.decisions_reportees == 0
        assert dossier_suivant.conclusion == V.NON_INSCRIT


class TestNouveauxMembres:
    """Un import d'actualisation doit dire qui entre pour la première fois au Tableau."""

    @pytest.mark.asyncio
    async def test_le_premier_import_ne_compte_que_des_nouveaux(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(db_session, test_admin_user, org, "initial.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40001", "nom": "ALPHA Jean"},
            {"numero_ordre": "EC/18.40002", "nom": "BETA Marie"},
        ), "2060")

        dossiers = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalars().all()

        assert outcome.nouveaux_membres == 2
        assert all(d.raw_data["situation"]["nouveau"] is True for d in dossiers)

    @pytest.mark.asyncio
    async def test_l_import_suivant_ne_compte_que_les_arrivants(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40010", "nom": "ALPHA Jean"},
        ), "2061", date_situation=date(2061, 3, 15))
        outcome = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40010", "nom": "ALPHA Jean"},
            {"numero_ordre": "EC/18.40011", "nom": "GAMMA Paul"},
        ), "2061", date_situation=date(2061, 6, 20))

        dossiers = {
            d.numero_ordre: d for d in (await db_session.execute(
                select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
            )).scalars().all()
        }

        assert outcome.nouveaux_membres == 1
        assert dossiers["EC/18.40010"].raw_data["situation"]["nouveau"] is False
        assert dossiers["EC/18.40011"].raw_data["situation"]["nouveau"] is True

    @pytest.mark.asyncio
    async def test_un_membre_n_est_nouveau_qu_une_fois_tous_exercices_confondus(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "2062.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40020"},
        ), "2062")
        outcome = await import_excel(db_session, test_admin_user, org, "2063.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40020"},
        ), "2063")

        assert outcome.nouveaux_membres == 0

    @pytest.mark.asyncio
    async def test_deux_lignes_du_meme_arrivant_ne_comptent_qu_un_membre(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(db_session, test_admin_user, org, "doublon.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40030", "heures": 40},
            {"numero_ordre": "EC/18.40030", "heures": 95},
        ), "2064")

        assert outcome.nouveaux_membres == 1

    @pytest.mark.asyncio
    async def test_un_arrivant_dans_un_conseil_reste_nouveau_dans_l_autre(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        autre = Organisation(nom="Conseil Arrivant", slug=f"cp-arr-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        await import_excel(db_session, test_admin_user, org, "a.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40040"},
        ), "2065")
        outcome = await import_excel(db_session, test_admin_user, autre.id, "b.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.40040"},
        ), "2065")

        assert outcome.nouveaux_membres == 1


class TestAnalyseSurBaseConsolidee:
    """Délibérer sur un fichier isolé revient à juger sur des données périmées."""

    @pytest.mark.asyncio
    async def test_l_analyse_de_la_base_juge_sur_la_situation_la_plus_recente(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50001", "heures": 10, "cotisation": "NON"},
        ), "2070", date_situation=date(2070, 3, 15))
        juin = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50001", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2070", date_situation=date(2070, 6, 20))

        await run_analyse_base(db_session, test_admin_user, org, exercice="2070")
        dossier_juin = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == juin.imp.id)
        )).scalar_one()
        await db_session.refresh(dossier_juin)

        assert dossier_juin.conclusion == V.INSCRIT

    @pytest.mark.asyncio
    async def test_l_analyse_de_la_base_couvre_les_membres_absents_du_dernier_fichier(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50010", "nom": "ALPHA Jean", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
            {"numero_ordre": "EC/18.50011", "nom": "BETA Marie", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2071", date_situation=date(2071, 3, 15))
        await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50010", "nom": "ALPHA Jean", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2071", date_situation=date(2071, 6, 20))

        analyse = await run_analyse_base(db_session, test_admin_user, org, exercice="2071")
        beta = (await db_session.execute(
            select(TableauDossier).where(
                TableauDossier.import_id == mars.imp.id,
                TableauDossier.numero_ordre == "EC/18.50011",
            )
        )).scalar_one()
        await db_session.refresh(beta)

        # BETA n'est pas dans le fichier de juin : l'analyse par import l'aurait oubliée.
        assert analyse.total_dossiers == 2
        assert beta.conclusion == V.INSCRIT

    @pytest.mark.asyncio
    async def test_l_analyse_par_import_reste_disponible(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50020", "heures": 10, "cotisation": "NON"},
        ), "2072", date_situation=date(2072, 3, 15))
        await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50020", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2072", date_situation=date(2072, 6, 20))

        await run_analyse(db_session, test_admin_user, org, mars.imp.id)
        dossier_mars = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == mars.imp.id)
        )).scalar_one()
        await db_session.refresh(dossier_mars)

        # Analyser un fichier précis reste possible, et juge bien ce fichier.
        assert dossier_mars.conclusion == V.NON_INSCRIT

    @pytest.mark.asyncio
    async def test_la_decision_prime_aussi_sur_l_analyse_de_la_base(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        mars = await import_excel(db_session, test_admin_user, org, "mars.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50030", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2073", date_situation=date(2073, 3, 15))
        dossier_mars = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == mars.imp.id)
        )).scalar_one()
        await create_decision(db_session, test_admin_user, org, TableauDecisionCreate(
            dossier_id=dossier_mars.id, type_decision="deliberation",
            decision="NON INSCRIT", motif="Procédure disciplinaire",
        ))
        juin = await import_excel(db_session, test_admin_user, org, "juin.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50030", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2073", date_situation=date(2073, 6, 20))

        await run_analyse_base(db_session, test_admin_user, org, exercice="2073")
        dossier_juin = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == juin.imp.id)
        )).scalar_one()
        await db_session.refresh(dossier_juin)

        assert dossier_juin.conclusion == V.NON_INSCRIT
        assert dossier_juin.raw_data["decision_appliquee"]["diverge"] is True

    @pytest.mark.asyncio
    async def test_sans_exercice_l_analyse_prend_le_dernier(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(db_session, test_admin_user, org, "2074.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.50040", "heures": 200, "cotisation": "OUI", "assurance": "OUI"},
        ), "2074")

        analyse = await run_analyse_base(db_session, test_admin_user, org)

        assert analyse.exercice == "2074"

    @pytest.mark.asyncio
    async def test_analyse_de_base_sans_import_est_refusee(self, db_session, test_admin_user):
        autre = Organisation(nom="Conseil Sans Base", slug=f"cp-nb-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.flush()

        with pytest.raises(HTTPException) as erreur:
            await run_analyse_base(db_session, test_admin_user, autre.id)

        assert erreur.value.status_code == 404


def _migration_normalisation():
    """Charge la migration pour éprouver son SQL, et non une copie approximative."""
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260914_tableau_numeros.py"
    spec = importlib.util.spec_from_file_location("migration_numeros", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNormalisationDesNumerosExistants:
    """Les dossiers importés avant la règle de normalisation doivent s'y aligner."""

    NUMEROS_SALES = [
        ("  ec/18.00062 ", "EC/18.00062"),
        ("EC / 18.00063", "EC/18.00063"),
        ("ec/18.00064\t", "EC/18.00064"),
        ("Sec/18.00065", "SEC/18.00065"),
        ("EC/18.00066", "EC/18.00066"),
        ("   ", None),
    ]

    async def _poser_dossiers_bruts(self, db, org, exercice, import_id):
        """Insère en contournant l'import, pour simuler des données antérieures."""
        for index, (sale, _) in enumerate(self.NUMEROS_SALES):
            await db.execute(text("""
                INSERT INTO secretariat_tableau_dossiers
                    (organisation_id, import_id, exercice, numero_ordre, nom, categorie,
                     statut_dossier, anomalie_detectee, created_at, updated_at)
                VALUES (:org, :imp, :ex, :num, :nom, 'EC Cabinet',
                        'imported', false, now(), now())
            """), {"org": org, "imp": import_id, "ex": exercice, "num": sale, "nom": f"MEMBRE {index}"})
        await db.flush()

    @pytest.mark.asyncio
    async def test_le_sql_de_la_migration_reproduit_la_normalisation_python(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        socle = await import_excel(db_session, test_admin_user, org, "socle.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.60001"},
        ), "2080")
        await self._poser_dossiers_bruts(db_session, org, "2080", socle.imp.id)

        await db_session.execute(text(_migration_normalisation().UPDATE))
        await db_session.flush()

        res = await db_session.execute(
            select(TableauDossier.nom, TableauDossier.numero_ordre)
            .where(TableauDossier.exercice == "2080", TableauDossier.nom.like("MEMBRE %"))
        )
        obtenus = {nom: numero for nom, numero in res.all()}

        for index, (sale, attendu) in enumerate(self.NUMEROS_SALES):
            nom = f"MEMBRE {index}"
            assert obtenus[nom] == attendu, f"{sale!r} normalisé en {obtenus[nom]!r}"
            # Le SQL doit dire exactement ce que dit le service.
            assert obtenus[nom] == _norm_numero_ordre(sale)

    @pytest.mark.asyncio
    async def test_apres_normalisation_les_situations_se_regroupent(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        ancien = await import_excel(db_session, test_admin_user, org, "ancien.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.60010", "heures": 60},
        ), "2081", date_situation=date(2081, 1, 5))
        # Le dossier d'origine portait la graphie du fichier.
        await db_session.execute(text("""
            UPDATE secretariat_tableau_dossiers SET numero_ordre = ' ec/18.60010 '
             WHERE import_id = :imp
        """), {"imp": ancien.imp.id})
        await db_session.flush()

        recent = await import_excel(db_session, test_admin_user, org, "recent.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.60010", "heures": 120},
        ), "2081", date_situation=date(2081, 6, 20))

        avant = await get_base_tableau(db_session, [org], exercice="2081")
        await db_session.execute(text(_migration_normalisation().UPDATE))
        await db_session.flush()
        apres = await get_base_tableau(db_session, [org], exercice="2081")

        # Avant, les deux graphies passaient pour deux membres distincts.
        assert avant["total_membres"] == 2
        assert apres["total_membres"] == 1
        assert float(apres["dossiers"][0].heures_forco) == 120
        assert apres["dossiers"][0].import_id == recent.imp.id

    @pytest.mark.asyncio
    async def test_la_migration_est_sans_effet_sur_des_numeros_deja_propres(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        imp = await import_excel(db_session, test_admin_user, org, "propre.xlsx", _make_import_bytes(
            {"numero_ordre": "EC/18.60020"},
            {"numero_ordre": "SEC/19.60021"},
        ), "2082")

        avant = sorted(n for n in (await db_session.execute(
            select(TableauDossier.numero_ordre).where(TableauDossier.import_id == imp.imp.id)
        )).scalars().all())
        await db_session.execute(text(_migration_normalisation().UPDATE))
        await db_session.flush()
        apres = sorted(n for n in (await db_session.execute(
            select(TableauDossier.numero_ordre).where(TableauDossier.import_id == imp.imp.id)
        )).scalars().all())

        assert avant == apres == ["EC/18.60020", "SEC/19.60021"]


class TestFiabilisationTableau:
    def test_date_de_situation_hors_exercice_refusee(self):
        with pytest.raises(HTTPException) as erreur:
            valider_date_situation("2026", date(2025, 12, 31))

        assert erreur.value.status_code == 422

    @pytest.mark.asyncio
    async def test_import_et_base_conservent_des_analyses_distinctes(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session,
            test_admin_user,
            org,
            "perimetres.xlsx",
            _make_import_bytes({
                "numero_ordre": "EC/18.70001",
                "cotisation": "NON",
                "heures": 10,
            }),
            "2090",
            date_situation=date(2090, 6, 30),
        )

        analyse_import = await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        analyse_base = await run_analyse_base(db_session, test_admin_user, org, exercice="2090")
        anomalies_import = await list_anomalies(db_session, org, analyse_id=analyse_import.id)
        anomalies_base = await list_anomalies(db_session, org, analyse_id=analyse_base.id)

        assert analyse_import.id != analyse_base.id
        assert {analyse_import.scope, analyse_base.scope} == {"import", "base"}
        assert anomalies_import
        assert anomalies_base
        assert {a.analyse_id for a in anomalies_import} == {analyse_import.id}
        assert {a.analyse_id for a in anomalies_base} == {analyse_base.id}

    @pytest.mark.asyncio
    async def test_nouvel_import_invalide_l_analyse_de_base(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(
            db_session,
            test_admin_user,
            org,
            "initial.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70010"}),
            "2091",
            date_situation=date(2091, 3, 1),
        )
        analyse = await run_analyse_base(db_session, test_admin_user, org, exercice="2091")

        await import_excel(
            db_session,
            test_admin_user,
            org,
            "actualisation.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70010", "heures": 140}),
            "2091",
            date_situation=date(2091, 6, 1),
        )
        await db_session.refresh(analyse)

        assert analyse.status == "stale"

    @pytest.mark.asyncio
    async def test_filtre_anomalie_s_applique_apres_consolidation(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        ancien = await import_excel(
            db_session,
            test_admin_user,
            org,
            "ancien.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70020"}),
            "2092",
            date_situation=date(2092, 2, 1),
        )
        ancien_dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == ancien.imp.id)
        )).scalar_one()
        ancien_dossier.anomalie_detectee = True
        await db_session.commit()
        await import_excel(
            db_session,
            test_admin_user,
            org,
            "recent.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70020"}),
            "2092",
            date_situation=date(2092, 8, 1),
        )

        base = await get_base_tableau(db_session, [org], exercice="2092", anomalie_only=True)

        assert base["total_membres"] == 0
        assert base["dossiers"] == []

    @pytest.mark.asyncio
    async def test_pagination_ne_fausse_pas_les_totaux(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        await import_excel(
            db_session,
            test_admin_user,
            org,
            "pagination.xlsx",
            _make_import_bytes(
                {"numero_ordre": "EC/18.70030", "nom": "ALPHA Jean"},
                {"numero_ordre": "EC/18.70031", "nom": "BETA Marie"},
                {"numero_ordre": "EC/18.70032", "nom": "GAMMA Luc"},
            ),
            "2093",
            date_situation=date(2093, 4, 1),
        )

        base = await get_base_tableau(
            db_session,
            [org],
            exercice="2093",
            limit=1,
            offset=1,
        )

        assert base["total_membres"] == 3
        assert len(base["dossiers"]) == 1
        assert base["dossiers"][0].nom.startswith("BETA")

    @pytest.mark.asyncio
    async def test_correction_est_tenant_scopee_et_invalide_les_analyses(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session,
            test_admin_user,
            org,
            "correction.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70040"}),
            "2094",
            date_situation=date(2094, 4, 1),
        )
        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()
        analyse_import = await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        analyse_base = await run_analyse_base(db_session, test_admin_user, org, exercice="2094")

        autre = Organisation(nom="Conseil Correction", slug=f"cp-corr-{uuid.uuid4().hex[:8]}")
        db_session.add(autre)
        await db_session.commit()
        with pytest.raises(HTTPException) as erreur:
            await corriger_dossier(
                db_session,
                test_admin_user,
                autre.id,
                dossier.id,
                TableauDossierCorrection(changes={"nom": "INTERDIT"}, motif="Mauvais conseil"),
            )
        assert erreur.value.status_code == 404

        corrige = await corriger_dossier(
            db_session,
            test_admin_user,
            org,
            dossier.id,
            TableauDossierCorrection(
                changes={"numero_ordre": " ec/19.70040 ", "cotisation_payee": True},
                clear_fields=["telephone"],
                motif="Pièces justificatives reçues",
            ),
        )
        await db_session.refresh(analyse_import)
        await db_session.refresh(analyse_base)

        assert corrige.numero_ordre == "EC/19.70040"
        assert corrige.conclusion is None
        assert analyse_import.status == "stale"
        assert analyse_base.status == "stale"

    @pytest.mark.asyncio
    async def test_export_refuse_une_analyse_absente_ou_obsolete(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session,
            test_admin_user,
            org,
            "export.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70050"}),
            "2095",
            date_situation=date(2095, 5, 1),
        )

        with pytest.raises(HTTPException) as absente:
            await export_tableau(db_session, org, outcome.imp.id)
        assert absente.value.status_code == 409

        await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        contenu, nom = await export_tableau(db_session, org, outcome.imp.id)
        assert contenu.startswith(b"PK")
        assert nom.endswith(".xlsx")

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()
        await corriger_dossier(
            db_session,
            test_admin_user,
            org,
            dossier.id,
            TableauDossierCorrection(changes={"email": "membre@example.cd"}, motif="Adresse confirmée"),
        )
        with pytest.raises(HTTPException) as obsolete:
            await export_tableau(db_session, org, outcome.imp.id)
        assert obsolete.value.status_code == 409


class TestDecisionsSansNumeroDOrdre:
    """Une décision prise sur un membre « à compléter » doit survivre à l'analyse."""

    def _dossier_orm(self, id: int, numero_ordre: str | None, nom: str, prenom: str | None = None):
        return TableauDossier(
            id=id,
            organisation_id=1,
            import_id=1,
            exercice="2026",
            numero_ordre=numero_ordre,
            nom=nom,
            prenom=prenom,
            categorie="EC Cabinet",
        )

    def _decision(self, id: int, dossier_id: int, decision: str = "INSCRIT"):
        return TableauDecision(
            id=id,
            organisation_id=1,
            dossier_id=dossier_id,
            user_id=uuid.uuid4(),
            type_decision="inscription",
            decision=decision,
            motif="Pièces produites en séance",
        )

    def test_cle_prefere_le_numero_puis_le_nom(self):
        assert _cle_decision(" ec/18.00062 ", "Dupont", "Jean") == "ordre:EC/18.00062"
        assert _cle_decision(None, "  Dupont ", " Jean") == "nom:dupont|jean"
        assert _cle_decision(None, "", None) is None

    def test_decision_s_applique_a_un_membre_sans_numero(self):
        dossier = self._dossier_orm(1, None, "Dupont", "Jean")
        verdicts = {1: {"conclusion": V.NON_INSCRIT, "motif": "cotisation non réglée"}}

        appliquees = _appliquer_decisions(
            [dossier],
            verdicts,
            {"nom:dupont|jean": [self._decision(10, 1)]},
        )

        assert appliquees[1]["decision_id"] == 10
        assert verdicts[1]["conclusion"] == V.INSCRIT

    def test_homonymes_sans_numero_ne_recoivent_aucune_decision(self):
        dossiers = [
            self._dossier_orm(1, None, "Dupont", "Jean"),
            self._dossier_orm(2, None, "DUPONT", "jean"),
        ]
        verdicts = {1: {"conclusion": V.NON_INSCRIT}, 2: {"conclusion": V.NON_INSCRIT}}

        appliquees = _appliquer_decisions(
            dossiers,
            verdicts,
            {"nom:dupont|jean": [self._decision(10, 1)]},
        )

        assert appliquees == {}
        assert verdicts[1]["conclusion"] == V.NON_INSCRIT
        assert verdicts[2]["conclusion"] == V.NON_INSCRIT

    def test_le_pv_signale_les_decisions_hors_perimetre(self):
        contenu = generate_pv(
            "2026",
            {"total_dossiers": 1},
            [],
            decisions_hors_perimetre=[{
                "decision_id": 10,
                "dossier_id": 1,
                "numero_ordre": None,
                "membre": "DUPONT Jean",
                "type_decision": "inscription",
                "decision": "INSCRIT",
                "motif": "Pièces produites en séance",
            }],
        )

        assert "DÉCISIONS NON RATTACHÉES À L'ANALYSE" in contenu
        assert "DUPONT Jean" in contenu
        assert "sans n° d'ordre" in contenu
        assert "Pièces produites en séance" in contenu

    @pytest.mark.asyncio
    async def test_le_pv_reprend_la_decision_d_un_membre_sans_numero(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "sans_numero.xlsx",
            _make_import_bytes({"numero_ordre": None, "nom": "MBAYA Sylvie"}),
            "2096", date_situation=date(2096, 4, 1),
        )
        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()
        assert dossier.numero_ordre is None

        await create_decision(db_session, test_admin_user, org, TableauDecisionCreate(
            dossier_id=dossier.id, type_decision="inscription", decision="INSCRIT",
            motif="Dossier régularisé en séance",
        ))
        await run_analyse(db_session, test_admin_user, org, outcome.imp.id)

        pv = await create_pv(db_session, test_admin_user, org, TableauPVCreate(
            import_id=outcome.imp.id, exercice="2096",
        ))

        assert "MBAYA Sylvie" in pv.contenu
        assert "Dossier régularisé en séance" in pv.contenu

    @pytest.mark.asyncio
    async def test_le_pv_signale_la_decision_rendue_inapplicable_par_un_homonyme(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "homonymes.xlsx",
            _make_import_bytes(
                {"numero_ordre": None, "nom": "KALALA Paul"},
                {"numero_ordre": None, "nom": "KALALA Paul"},
            ),
            "2097", date_situation=date(2097, 4, 1),
        )
        dossiers = list((await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id).order_by(TableauDossier.id)
        )).scalars().all())
        assert len(dossiers) == 2

        await create_decision(db_session, test_admin_user, org, TableauDecisionCreate(
            dossier_id=dossiers[0].id, type_decision="inscription", decision="INSCRIT",
            motif="Homonymie à lever avant application",
        ))
        analyse = await run_analyse(db_session, test_admin_user, org, outcome.imp.id)

        # Indistinguables : la décision n'est appliquée à aucun des deux...
        assert analyse.source_decision_ids == []
        for dossier in dossiers:
            await db_session.refresh(dossier)
            assert dossier.conclusion != V.INSCRIT

        # ...mais le PV la soumet quand même à la commission.
        pv = await create_pv(db_session, test_admin_user, org, TableauPVCreate(
            import_id=outcome.imp.id, exercice="2097",
        ))
        assert "DÉCISIONS NON RATTACHÉES À L'ANALYSE" in pv.contenu
        assert "Homonymie à lever avant application" in pv.contenu

    def test_le_pv_n_est_plus_tronque_a_trente_decisions(self):
        decisions = [
            {"dossier_id": i, "membre": f"MEMBRE {i}", "numero_ordre": f"EC/26.{i:05d}",
             "type_decision": "inscription", "decision": "INSCRIT"}
            for i in range(40)
        ]

        contenu = generate_pv("2026", {}, decisions)

        assert "MEMBRE 39" in contenu


class TestCategoriesCorrigeables:
    """La liste des catégories corrigeables suit le barème de délibération."""

    def test_toutes_les_categories_du_bareme_sont_corrigeables(self):
        for categorie in V.CATEGORIE_CRITERES:
            assert _normaliser_correction("categorie", categorie) == categorie

    def test_categorie_hors_bareme_refusee(self):
        with pytest.raises(ValueError):
            _normaliser_correction("categorie", "Inconnu")



def _migration_droits_repris():
    """Charge la migration pour éprouver son SQL, et non une copie approximative."""
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260914_tableau_droits_repris.py"
    spec = importlib.util.spec_from_file_location("migration_droits_repris", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRepriseDesDroitsTableau:
    """Le durcissement des routes ne doit retirer aucune capacité déjà exercée."""

    async def _poser_permissions(self, db, codes):
        for code in codes:
            await db.execute(text(
                "INSERT INTO permissions (code, description, created_at) VALUES (:c, :c, now())"
                " ON CONFLICT (code) DO NOTHING"
            ), {"c": code})

    async def _creer_role(self, db, code, codes_permissions):
        res = await db.execute(text(
            "INSERT INTO roles (code, label, created_at) VALUES (:c, :c, now()) RETURNING id"
        ), {"c": code})
        role_id = res.scalar_one()
        for code_perm in codes_permissions:
            await db.execute(text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT :role, id FROM permissions WHERE code = :perm
            """), {"role": role_id, "perm": code_perm})
        return role_id

    async def _droits(self, db, role_id) -> set[str]:
        res = await db.execute(text("""
            SELECT p.code FROM role_permissions rp
              JOIN permissions p ON p.id = rp.permission_id
             WHERE rp.role_id = :role
        """), {"role": role_id})
        return set(res.scalars().all())

    @pytest.mark.asyncio
    async def test_un_role_qui_consultait_garde_ce_qu_il_exercait(self, db_session):
        migration = _migration_droits_repris()
        await self._poser_permissions(db_session, [
            "secretariat.tableau.view", "secretariat.tableau.correct", *migration.DROITS_REPRIS,
        ])
        consultant = await self._creer_role(db_session, f"tableau-consultant-{uuid.uuid4().hex[:8]}", [
            "secretariat.tableau.view",
        ])
        etranger = await self._creer_role(db_session, f"sans-tableau-{uuid.uuid4().hex[:8]}", [
            "secretariat.tableau.correct",
        ])

        await db_session.execute(text(migration.REPRISE))
        await db_session.flush()

        droits = await self._droits(db_session, consultant)
        assert set(migration.DROITS_REPRIS) <= droits
        # La correction n'existait pas avant : elle ne se donne pas d'office.
        assert "secretariat.tableau.correct" not in droits
        # Un rôle sans consultation n'hérite de rien.
        assert await self._droits(db_session, etranger) == {"secretariat.tableau.correct"}

    @pytest.mark.asyncio
    async def test_la_reprise_est_rejouable_sans_doublon(self, db_session):
        migration = _migration_droits_repris()
        await self._poser_permissions(db_session, [
            "secretariat.tableau.view", *migration.DROITS_REPRIS,
        ])
        role = await self._creer_role(db_session, f"tableau-rejoue-{uuid.uuid4().hex[:8]}", [
            "secretariat.tableau.view", "secretariat.tableau.export",
        ])

        await db_session.execute(text(migration.REPRISE))
        await db_session.execute(text(migration.REPRISE))
        await db_session.flush()

        res = await db_session.execute(text("""
            SELECT count(*) FROM role_permissions rp
              JOIN permissions p ON p.id = rp.permission_id
             WHERE rp.role_id = :role AND p.code = 'secretariat.tableau.export'
        """), {"role": role})
        assert res.scalar_one() == 1



class TestAnalyseNationaleConseilParConseil:
    """Un conseil en échec ne doit ni bloquer ni masquer le sort des autres."""

    @pytest.mark.asyncio
    async def test_un_conseil_en_echec_laisse_les_autres_analyses_valides(
        self, db_session, test_admin_user, monkeypatch,
    ):
        premier = test_admin_user.organisation_id
        second = Organisation(nom="Conseil National Test", slug=f"cp-nat-{uuid.uuid4().hex[:8]}")
        db_session.add(second)
        await db_session.commit()
        # Le rollback du conseil en échec expire les objets de cette session :
        # l'identifiant est retenu avant, et non relu après.
        second_id = second.id

        for org in (premier, second_id):
            await import_excel(
                db_session, test_admin_user, org, f"national_{org}.xlsx",
                _make_import_bytes({"numero_ordre": f"EC/18.8{org:04d}"}),
                "2098", date_situation=date(2098, 3, 1),
            )

        vraie_analyse = tableau_router.run_analyse_base

        async def analyse_qui_echoue_sur_le_second(db, user, organisation_id, exercice=None):
            if organisation_id == second_id:
                raise HTTPException(status_code=500, detail="Panne simulée")
            return await vraie_analyse(db, user, organisation_id, exercice=exercice)

        monkeypatch.setattr(tableau_router, "run_analyse_base", analyse_qui_echoue_sur_le_second)
        monkeypatch.setattr(test_admin_user, "role", "super_admin")

        resultat = await tableau_router.analyse_base(
            exercice="2098", national=True, db=db_session, user=test_admin_user, tenant_id=premier,
        )

        assert resultat.analyses_count == 1
        assert resultat.erreurs_count == 1
        sorts = {item.organisation_id: item.status for item in resultat.resultats}
        assert sorts[premier] == "ok"
        assert sorts[second_id] == "erreur"
        assert "Panne simulée" in next(i.detail for i in resultat.resultats if i.status == "erreur")

        # L'analyse du conseil épargné est bien enregistrée, pas annulée.
        enregistree = (await db_session.execute(
            select(TableauAnalyse).where(
                TableauAnalyse.organisation_id == premier,
                TableauAnalyse.exercice == "2098",
                TableauAnalyse.scope == "base",
            )
        )).scalars().first()
        assert enregistree is not None and enregistree.status == "completed"


class TestCompteursDuTableauDeBord:
    """Un compteur qui ne peut pas être calculé se dit inconnu, il n'affiche pas zéro."""

    async def _conseil_neuf(self, db):
        conseil = Organisation(nom="Conseil Compteurs", slug=f"cp-cpt-{uuid.uuid4().hex[:8]}")
        db.add(conseil)
        await db.commit()
        return conseil.id

    @pytest.mark.asyncio
    async def test_les_incomplets_restent_inconnus_sans_analyse_de_base(self, db_session, test_admin_user):
        org = await self._conseil_neuf(db_session)
        await import_excel(
            db_session, test_admin_user, org, "compteurs.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.90001", "cotisation": None, "heures": None}),
            "2099", date_situation=date(2099, 3, 1),
        )

        stats = await get_stats(db_session, org)

        assert stats["dossiers_incomplets"] is None
        assert stats["analyse_base_status"] is None

    @pytest.mark.asyncio
    async def test_l_analyse_de_base_renseigne_puis_perime_les_compteurs(self, db_session, test_admin_user):
        # Corriger un dossier exige que l'utilisateur appartienne au conseil :
        # ce test reste donc sur celui de l'admin, avec l'exercice le plus
        # récent du fichier — c'est lui que le tableau de bord mesure.
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "compteurs2.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.90010", "cotisation": None, "heures": None}),
            "2099", date_situation=date(2099, 3, 1),
        )
        await run_analyse_base(db_session, test_admin_user, org, exercice="2099")

        stats = await get_stats(db_session, org)
        assert stats["analyse_base_status"] == "completed"
        assert stats["dossiers_incomplets"] == 1

        dossier = (await db_session.execute(
            select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id)
        )).scalar_one()
        await corriger_dossier(
            db_session, test_admin_user, org, dossier.id,
            TableauDossierCorrection(changes={"cotisation_payee": True}, motif="Reçu présenté"),
        )

        stats = await get_stats(db_session, org)
        assert stats["analyse_base_status"] == "stale"
        assert stats["dossiers_incomplets"] is None
