"""Rapport complet du Tableau : chiffres calculés, contrôles, sorties PDF et Excel."""
from __future__ import annotations

import io
from datetime import date
from types import SimpleNamespace

import openpyxl
import pdfplumber
import pytest
from fastapi import HTTPException

from app.modules.tableau import rapport_complet as R
from app.modules.tableau import verdict as V
from app.modules.tableau.excel_import import parse_excel_bytes
from app.modules.tableau.repository import get_analyse_for_import, list_dossiers
from app.modules.tableau.service import _norm_numero_ordre, export_rapport_complet, import_excel, imports_comparables, run_analyse, run_analyse_base

from test_tableau_module import _make_import_bytes


def _ctx(**overrides) -> R.ContexteRapport:
    valeurs = {
        "exercice": "2026",
        "date_situation": date(2026, 1, 10),
        "scope": "import",
        "source": "Fichier test.xlsx",
        "organisation": "CONSEIL TEST",
        "reglages": V.TableauReglages(),
        "exercice_annee": 2026,
        "genere_le": date(2026, 10, 31),
    }
    return R.ContexteRapport(**{**valeurs, **overrides})


def _dossier(id_: int, numero: str | None, conclusion: str = V.INSCRIT, **overrides) -> dict:
    return {
        "id": id_,
        "numero_ordre": numero,
        "nom": f"MEMBRE {id_}",
        "prenom": None,
        "categorie": "EC Cabinet",
        "cotisation_payee": True,
        "assurance": None,
        "chiffre_affaires": None,
        "heures_forco": 130.0,
        "sexe": "M",
        "anciennete": "Ancien",
        "telephone": f"+24381000{id_:04d}",
        "email": f"membre{id_}@example.cd",
        "conclusion": conclusion,
        "conclusion_motif": None,
        "raw_data": {},
        **overrides,
    }


def _donnees(dossiers, anomalies=(), **ctx):
    return R.construire_donnees(dossiers, list(anomalies), _ctx(**ctx), _norm_numero_ordre)


def _types(donnees) -> set[str]:
    return {item["type"] for item in donnees["registre"]}


def test_les_exemptes_ne_comptent_ni_dans_les_heures_ni_dans_les_zeros():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", heures_forco=120.0),
        _dossier(2, "EC/16.00002", V.NON_INSCRIT, heures_forco=0.0),
        _dossier(3, "EC/25.00003", heures_forco=0.0, anciennete="Nouveau"),
    ])
    assert donnees["nhv"]["soumis"] == 2
    assert donnees["nhv"]["exemptes"] == 1
    assert donnees["nhv"]["zero"] == 1
    assert donnees["nhv"]["moyenne"] == 60
    formation = next(c for c in donnees["criteres"] if c["critere"] == "formation")
    assert (formation["conformes"], formation["defauts"], formation["exemptes"]) == (1, 1, 1)


def test_le_seuil_vient_des_reglages_de_l_exercice():
    dossier = _dossier(1, "EC/16.00001", heures_forco=100.0)
    assert next(c for c in _donnees([dossier])["criteres"] if c["critere"] == "formation")["defauts"] == 1
    assouplis = _donnees([dossier], reglages=V.TableauReglages(heures_formation_min=80))
    assert next(c for c in assouplis["criteres"] if c["critere"] == "formation")["defauts"] == 0


def test_les_stagiaires_restent_hors_du_taux():
    donnees = _donnees([_dossier(1, "EC/16.00001"), _dossier(2, "ECS/24.0001", V.NON_APPLICABLE, categorie="Stagiaire")])
    assert donnees["total"] == 1
    assert donnees["taux"] == 1
    assert len(donnees["stagiaires"]) == 1


def test_controles_de_coherence():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", raw_data={"hformation": True}, heures_forco=103.0),
        _dossier(2, "EC/18.00002", anciennete="Nouveau"),
        _dossier(3, "EC/30.00003"),
        _dossier(4, None),
        _dossier(5, "EC/16.00005"),
        _dossier(6, "EC/16.00005", email="pas-une-adresse"),
    ])
    assert {
        "Formation OUI sous le seuil",
        "Ancienneté incohérente avec le numéro d'ordre",
        "Numéro d'ordre postérieur à l'exercice",
        "Numéro d'ordre manquant",
        "Numéro d'ordre en double",
        "E-mail invalide",
    } <= _types(donnees)


def test_un_defaut_de_conformite_n_entre_pas_au_registre_de_qualite():
    anomalies = [
        {"dossier_id": 1, "type_anomalie": "cotisation_non_payee", "gravite": "high", "description": "Non réglée"},
        {"dossier_id": 1, "type_anomalie": "cotisation_non_renseignee", "gravite": "medium", "description": "Vide"},
    ]
    donnees = _donnees([_dossier(1, "EC/16.00001")], anomalies)
    assert "Cotisation non renseignée" in _types(donnees)
    assert not any("non réglée" in item["observation"] for item in donnees["registre"])


def test_contact_partage_grave_seulement_dans_une_meme_categorie():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", email="meme@example.cd"),
        _dossier(2, "EC/16.00002", email="meme@example.cd"),
        _dossier(3, "EC/16.00003", telephone="+243810000099"),
        _dossier(4, "SEC/16.00004", categorie="Société", telephone="+243 81 000 0099"),
    ])
    gravites = {item["type"]: item["gravite"] for item in donnees["registre"]}
    assert gravites["E-mail partagé dans une même catégorie"] == "Moyenne"
    assert gravites["Téléphone partagé entre catégories"] == "Information"


def test_rapprochement_avec_le_fichier_et_l_import_de_comparaison():
    donnees = _donnees(
        [
            _dossier(1, "EC/16.00001", V.NON_INSCRIT, raw_data={"conclusion_source": "INSCRIT"}),
            _dossier(2, "EC/16.00002", raw_data={"conclusion_source": "inscrit"}),
            _dossier(3, "EC/16.00003"),
        ],
        comparaison_nom="Version définitive.xlsx",
        comparaison={
            _norm_numero_ordre("EC/16.00002"): {"conclusion": "NON INSCRIT", "heures_forco": 90.0},
            _norm_numero_ordre("EC/16.00003"): {"conclusion": "INSCRIT", "heures_forco": 130.0},
        },
    )
    assert [e["numero_ordre"] for e in donnees["ecarts_fichier"]] == ["EC/16.00001"]
    assert [e["numero_ordre"] for e in donnees["ecarts_comparaison"]] == ["EC/16.00002"]
    assert donnees["avec_conclusion_source"] == 2


def test_le_plan_ne_propose_que_ce_qui_reste_a_faire():
    assert _donnees([_dossier(1, "EC/16.00001")])["plan"] == []
    plan = _donnees([_dossier(1, "EC/16.00001", V.NON_INSCRIT, heures_forco=10.0)])["plan"]
    assert [ligne[2] for ligne in plan] == ["Rattraper la formation des dossiers en défaut"]


def test_excel_sans_filtre_en_double_et_valeur_importee_neutralisee():
    donnees = _donnees([_dossier(1, "EC/16.00001", V.NON_INSCRIT, nom="=HACK()", heures_forco=10.0)])
    wb = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    assert {"Tableau de bord", "À traiter", "Profil", "Qualité données", "EC EN CABINET", "Plan d'action", "Méthode"} <= set(wb.sheetnames)
    feuille = wb["À traiter"]
    assert feuille.auto_filter.ref is None
    assert len(feuille.tables) == 1
    assert feuille["C5"].value == "'=HACK()"
    assert feuille["C5"].data_type == "s"
    graphique = wb["Tableau de bord"]._charts[0]
    assert graphique.grouping == "percentStacked"
    assert graphique.x_axis.scaling.max is None
    assert graphique.x_axis.delete is False
    assert [serie.graphicalProperties.solidFill.srgbClr for serie in graphique.series] == [couleur for _, couleur in R.ETATS.values()]


def test_pdf_au_format_francais_et_sans_donnee_vide():
    donnees = _donnees([_dossier(1, "EC/16.00001"), _dossier(2, "EC/16.00002", V.NON_INSCRIT, heures_forco=10.0)])
    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        texte = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "50,0 %" in texte
    assert "50.0" not in texte
    assert "10 janvier 2026" in texte
    assert "aucun rapprochement" in texte


def test_pdf_tolere_un_import_vide_et_des_caracteres_a_echapper():
    assert R.build_pdf(_donnees([])).startswith(b"%PDF")
    assert R.build_excel(_donnees([])).startswith(b"PK")
    donnees = _donnees([_dossier(1, "EC/16.00001", nom="A & B <SARL>")])
    assert R.build_pdf(donnees).startswith(b"%PDF")


class TestExportBoutEnBout:
    @pytest.mark.asyncio
    async def test_refuse_sans_analyse_puis_produit_les_deux_formats(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "rapport.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70060"}), "2061", date_situation=date(2061, 5, 1),
        )
        with pytest.raises(HTTPException) as absente:
            await export_rapport_complet(db_session, org, outcome.imp.id)
        assert absente.value.status_code == 409

        await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        pdf, nom_pdf = await export_rapport_complet(db_session, org, outcome.imp.id, "pdf")
        assert pdf.startswith(b"%PDF")
        assert nom_pdf == f"Rapport_Tableau_2061_{outcome.imp.id}.pdf"
        excel, nom_excel = await export_rapport_complet(db_session, org, outcome.imp.id, "xlsx")
        assert excel.startswith(b"PK")
        assert nom_excel.endswith(".xlsx")

    @pytest.mark.asyncio
    async def test_comparaison_refusee_hors_exercice_ou_sur_soi_meme(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        premier = await import_excel(
            db_session, test_admin_user, org, "a.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70061"}), "2062", date_situation=date(2062, 5, 1),
        )
        autre = await import_excel(
            db_session, test_admin_user, org, "b.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70062"}), "2063", date_situation=date(2063, 5, 1),
        )
        await run_analyse(db_session, test_admin_user, org, premier.imp.id)
        for cible in (premier.imp.id, autre.imp.id):
            with pytest.raises(HTTPException) as refus:
                await export_rapport_complet(db_session, org, premier.imp.id, comparer_a=cible)
            assert refus.value.status_code == 422

    @pytest.mark.asyncio
    async def test_base_retrouvee_depuis_n_importe_quel_import_de_l_exercice(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        ancien = await import_excel(
            db_session, test_admin_user, org, "ancien.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70063"}), "2039", date_situation=date(2039, 3, 1),
        )
        await import_excel(
            db_session, test_admin_user, org, "recent.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70064"}), "2039", date_situation=date(2039, 6, 1),
        )
        with pytest.raises(HTTPException) as absente:
            await export_rapport_complet(db_session, org, ancien.imp.id, scope="base")
        assert absente.value.status_code == 409
        assert "Analyser la base" in absente.value.detail

        await run_analyse_base(db_session, test_admin_user, org, "2039")
        contenu, nom = await export_rapport_complet(db_session, org, ancien.imp.id, "xlsx", scope="base")
        assert nom == "Rapport_Tableau_2039_base.xlsx"
        feuille = openpyxl.load_workbook(io.BytesIO(contenu))["EC EN CABINET"]
        assert {feuille.cell(ligne, 2).value for ligne in range(5, 7)} == {"EC/18.70063", "EC/18.70064"}

        # Tous les dossiers de ces deux imports sont dans la base : rien à comparer.
        assert await imports_comparables(db_session, org, ancien.imp.id, scope="base") == []
        with pytest.raises(HTTPException) as sans_autre:
            await export_rapport_complet(db_session, org, ancien.imp.id, "xlsx", scope="base", comparer_a=ancien.imp.id)
        assert sans_autre.value.status_code == 422

    @pytest.mark.asyncio
    async def test_la_base_se_compare_a_la_situation_remplacee_sans_compter_deux_fois(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        numero = "EC/18.70067"
        ancien = await import_excel(
            db_session, test_admin_user, org, "ancien.xlsx",
            _make_import_bytes({"numero_ordre": numero, "cotisation": "OUI", "heures": 130}), "2038", date_situation=date(2038, 3, 1),
        )
        await run_analyse(db_session, test_admin_user, org, ancien.imp.id)
        recent = await import_excel(
            db_session, test_admin_user, org, "recent.xlsx",
            _make_import_bytes({"numero_ordre": numero, "cotisation": "NON", "heures": 130}), "2038", date_situation=date(2038, 6, 1),
        )
        await run_analyse_base(db_session, test_admin_user, org, "2038")

        assert await imports_comparables(db_session, org, recent.imp.id, scope="base") == [{"id": ancien.imp.id, "file_name": "ancien.xlsx"}]
        with pytest.raises(HTTPException) as elle_meme:
            await export_rapport_complet(db_session, org, recent.imp.id, "xlsx", scope="base", comparer_a=recent.imp.id)
        assert elle_meme.value.status_code == 422

        contenu, _ = await export_rapport_complet(db_session, org, recent.imp.id, "xlsx", scope="base", comparer_a=ancien.imp.id)
        classeur = openpyxl.load_workbook(io.BytesIO(contenu))
        lignes = [l for l in classeur["Rapprochement"].iter_rows(min_row=5, values_only=True) if l[2]]
        assert [(l[2], l[4], l[5]) for l in lignes] == [(numero, V.NON_INSCRIT, V.INSCRIT)]
        decisions = [c.value for c in classeur["Synthèse Bureau"]["A"]]
        assert "Valider les écarts de conclusion : 1." in decisions

    @pytest.mark.asyncio
    async def test_perimetre_sans_dossier_refuse(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "vide.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70065"}), "2030", date_situation=date(2030, 5, 1),
        )
        await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        analyse = await get_analyse_for_import(db_session, org, outcome.imp.id)
        analyse.source_dossier_ids = []
        for dossier in await list_dossiers(db_session, org, import_id=outcome.imp.id):
            await db_session.delete(dossier)
        await db_session.commit()
        with pytest.raises(HTTPException) as refus:
            await export_rapport_complet(db_session, org, outcome.imp.id)
        assert refus.value.status_code == 409
        assert "Base consolidée" in refus.value.detail
        with pytest.raises(HTTPException) as base_vide:
            await export_rapport_complet(db_session, org, outcome.imp.id, scope="base")
        assert base_vide.value.status_code == 409
        assert "Aucun membre" in base_vide.value.detail
        with pytest.raises(HTTPException) as analyse_vide:
            await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        assert analyse_vide.value.status_code == 409
        assert "Base consolidée" in analyse_vide.value.detail


def _classeur_avec_bloc_de_statistiques() -> bytes:
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "EC EN CABINET 25"
    feuille.append(["N°", "N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Sexe", "Ancienneté", "Cotisation"])
    feuille.append([1, "EC/16.00001", "MEMBRE Un", "M", "Ancien", "OUI"])
    feuille.append([2, None, "SOCIETE SANS NUMERO SARL", None, "Nouvelle", "N/A"])
    feuille.append([3, "EC/16.00003", None, "F", "Ancien", "OUI"])
    feuille.append([])
    # Disposition réelle : libellé, puis le compte sous « N° d'ordre » et le % sous « Nom ».
    feuille.append(["Ancienneté", "Nombre", "%", "Régularisation de la Cotisation", "Nombre", "%"])
    feuille.append(["Anciennes", 100, 98.03921568627452, "Cotisations Régularisées (OUI)", 96, 94.1])
    feuille.append(["TOTAL", 102, 100, "TOTAL", 102, 100])
    feuille.append(["Sans pourcentage", 7, None])
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def test_les_blocs_de_statistiques_ne_deviennent_pas_des_membres():
    lignes, erreurs = parse_excel_bytes(_classeur_avec_bloc_de_statistiques(), "2026")
    assert erreurs == []
    assert [(l["numero_ordre"], l["nom"]) for l in lignes] == [
        ("EC/16.00001", "MEMBRE Un"),
        (None, "SOCIETE SANS NUMERO SARL"),
        ("EC/16.00003", ""),
    ]


@pytest.mark.parametrize("numero", [1693, "EC16.00093", "16.00093", "EC 16.00093", None])
def test_une_ligne_de_membre_en_fin_de_tableau_n_est_jamais_perdue(numero):
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "EC EN CABINET 25"
    feuille.append(["N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Cotisation"])
    feuille.append(["EC/16.00001", "MEMBRE Un", "OUI"])
    feuille.append([numero, "DERNIER Membre", "OUI"])
    feuille.append([])
    feuille.append(["Ancienneté", "Nombre", "%"])
    feuille.append(["Anciennes", 100, 98.0])
    feuille.append(["TOTAL", 102, 100])
    tampon = io.BytesIO()
    classeur.save(tampon)

    lignes, erreurs = parse_excel_bytes(tampon.getvalue(), "2026")

    assert erreurs == []
    assert [ligne["nom"] for ligne in lignes] == ["MEMBRE Un", "DERNIER Membre"]


def test_un_compte_numerique_n_est_pas_un_numero_d_ordre_sans_colonne_de_rang():
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "EC EN CABINET 25"
    feuille.append(["N° D'ORDRE", "NOM, POST NOMS ET PRENOMS", "Cotisation"])
    feuille.append(["EC/16.00001", "MEMBRE Un", "OUI"])
    feuille.append([])
    feuille.append(["Ancienneté", "Nombre", "%"])
    feuille.append([100, 98.03921568627452, None])
    tampon = io.BytesIO()
    classeur.save(tampon)

    lignes, erreurs = parse_excel_bytes(tampon.getvalue(), "2026")

    assert erreurs == []
    assert [(ligne["numero_ordre"], ligne["nom"]) for ligne in lignes] == [
        ("EC/16.00001", "MEMBRE Un"),
    ]


@pytest.mark.asyncio
async def test_route_http_rend_le_pdf_et_exige_une_session(app_client, admin_access_token, db_session, test_admin_user):
    org = test_admin_user.organisation_id
    outcome = await import_excel(
        db_session, test_admin_user, org, "http.xlsx",
        _make_import_bytes({"numero_ordre": "EC/18.70066"}), "2029", date_situation=date(2029, 5, 1),
    )
    await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
    url = f"/api/v1/tableau/rapport-complet/{outcome.imp.id}"

    assert (await app_client.get(url)).status_code == 401
    reponse = await app_client.get(url, params={"format": "pdf"}, headers={"Authorization": f"Bearer {admin_access_token}"})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert f"Rapport_Tableau_2029_{outcome.imp.id}.pdf" in reponse.headers["content-disposition"]
    assert reponse.content.startswith(b"%PDF")

    comparables = await app_client.get(f"{url}/comparables", params={"scope": "base"}, headers={"Authorization": f"Bearer {admin_access_token}"})
    assert comparables.status_code == 200
    assert comparables.json() == []


def test_nhv_absent_signale_plutot_qu_une_moyenne_a_zero():
    donnees = _donnees([_dossier(1, "EC/16.00001", heures_forco=None, raw_data={"hformation": True})])
    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        texte = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Aucun NHV n'a été lu" in texte
    assert "Moyenne" not in texte


def _ligne_membre(id_: int, categorie: str = "EC Cabinet", **overrides):
    valeurs = {
        "genre": "PP", "id": id_, "numero_ordre": f"EC/16.{id_:05d}", "nom": f"MEMBRE {id_}", "categorie": categorie,
        "nif": None, "cabinet": "CABINET A", "email": f"m{id_}@example.cd", "telephone": f"+24381{id_:07d}",
        "assurance": None, "sexe": "F", "nhv": 130, "actif": True, "province": "KINSHASA", "erreurs": [],
    }
    return SimpleNamespace(**{**valeurs, **overrides})


def test_membres_sans_dossier_a_completer_et_sans_conclusion_inventee():
    ca = {_norm_numero_ordre("EC/16.00002"): False}
    assurances = {_norm_numero_ordre("EC/16.00002"): True}
    dossiers = [
        R.membre_en_dossier(_ligne_membre(1, nhv=None, erreurs=[{"message": "Sexe illisible"}]), {}, {}, _norm_numero_ordre),
        R.membre_en_dossier(_ligne_membre(2, "EC Indépendant", nhv=90), ca, assurances, _norm_numero_ordre),
    ]
    assert dossiers[1]["assurance"] is True
    donnees = _donnees(dossiers)
    assert (donnees["inscrits"], donnees["non_inscrits"], donnees["a_completer"]) == (0, 0, 2)
    assert donnees["taux"] is None
    assert donnees["cotisations_inconnues"] == 2
    assert "Signalement à l'import" in _types(donnees)
    assert donnees["plan"][0][2].startswith("Renseigner la cotisation")
    assert ["Rattraper la formation des dossiers en défaut"] == [l[2] for l in donnees["plan"] if "formation" in l[2]]
    assert ["Actif", 2] in donnees["profil"]["actif"]
    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        texte = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "à compléter" in texte
    assert "% 120 FOR" in texte
    classeur = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    assert classeur["À traiter"]["H5"].value == R.A_COMPLETER
    assert classeur["À traiter"]["E4"].value == "Actif"
    assert classeur["À traiter"]["E5"].value == "OUI"


def test_assurance_et_ca_reserves_aux_societes_et_aux_independants():
    ca = {_norm_numero_ordre(f"EC/16.{i:05d}"): True for i in range(1, 5)}
    assurances = {_norm_numero_ordre(f"EC/16.{i:05d}"): True for i in range(1, 5)}
    lignes = [
        _ligne_membre(1, "EC Cabinet", assurance=False),
        _ligne_membre(2, "EC Salarié"),
        _ligne_membre(3, "EC Indépendant"),
        _ligne_membre(4, "Société", sexe=None, nhv=None),
    ]
    dossiers = [R.membre_en_dossier(l, ca, assurances, _norm_numero_ordre) for l in lignes]
    assert [(d["assurance"], d["chiffre_affaires"]) for d in dossiers] == [(None, None), (None, None), (True, True), (True, True)]

    donnees = _donnees(dossiers)
    assert next(c for c in donnees["criteres"] if c["critere"] == "assurance")["perimetre"] == 2
    sections = {s["categorie"]: s for s in donnees["sections"]}
    assert list(sections) == ["EC Cabinet", "EC Indépendant", "Société", "EC Salarié"]
    for categorie in ("EC Cabinet", "EC Salarié"):
        assert "Assurance valide" not in sections[categorie]["entetes"]
        assert "Chiffre d'affaires" not in sections[categorie]["entetes"]
        assert {b["titre"] for b in sections[categorie]["blocs"]} == {"Ancienneté", "Régularisation de la Cotisation", "Heures Formations", "Conclusion"}
    assert "Heures Formations" not in {b["titre"] for b in sections["Société"]["blocs"]}
    assert "H.Formation" not in sections["Société"]["entetes"]
    assert {"Assurance valide", "H.Formation", "Chiffre d'affaires"} <= set(sections["EC Indépendant"]["entetes"])

    classeur = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    feuille = classeur["EC EN CABINET"]
    assert feuille["A2"].value.startswith("SECTION A1")
    assert "Assurance valide" not in [c.value for c in feuille[4]]
    assert len(feuille._charts) == 1
    assert feuille._charts[0].grouping == "percentStacked"
    assert R.build_pdf(donnees).startswith(b"%PDF")


def test_colonne_actif_dans_les_listes_du_rapport():
    lignes = [
        _ligne_membre(1, "EC Cabinet", actif=True),
        _ligne_membre(2, "EC Cabinet", actif=False),
        _ligne_membre(3, "EC Cabinet", actif=None),
        _ligne_membre(4, "Société", actif=None, sexe=None, nhv=None),
    ]
    donnees = _donnees([R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes])
    sections = {s["categorie"]: s for s in donnees["sections"]}
    entetes = sections["EC Cabinet"]["entetes"]
    assert entetes.index("Actif") == entetes.index("Sexe") + 1
    assert [ligne[entetes.index("Actif")] for ligne in sections["EC Cabinet"]["lignes"]] == ["OUI", "NON", ""]
    # Le fichier des personnes morales ne porte pas ce statut : pas de colonne vide.
    assert "Actif" not in sections["Société"]["entetes"]

    feuille = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))["EC EN CABINET"]
    assert "Actif" in [cellule.value for cellule in feuille[4]]
    assert feuille.tables, "le tableau Excel porte le filtre de la colonne"
    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        assert "Actif" in "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_nif_exige_des_ec_independants_seulement():
    lignes = [
        _ligne_membre(1, "EC Indépendant", nif=None),
        _ligne_membre(2, "EC Indépendant", nif="A1810696X"),
        _ligne_membre(3, "EC Cabinet", nif=None),
        _ligne_membre(4, "Société", nif=None, sexe=None, nhv=None),
    ]
    donnees = _donnees([R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes])
    nif = next(c for c in donnees["criteres"] if c["critere"] == "nif")
    assert (nif["perimetre"], nif["conformes"], nif["defauts"]) == (2, 1, 1)
    assert [r["numero_ordre"] for r in donnees["registre"] if r["type"] == R.TYPE_NIF_MANQUANT] == ["EC/16.00001"]
    assert any(ligne[2].startswith("Obtenir le NIF") and ligne[5] == "1" for ligne in donnees["plan"])
    sections = {s["categorie"]: s for s in donnees["sections"]}
    assert "NIF" in sections["EC Indépendant"]["entetes"]
    assert "NIF" in {b["titre"] for b in sections["EC Indépendant"]["blocs"]}
    assert "NIF" not in {b["titre"] for b in sections["EC Cabinet"]["blocs"]}
    assert "NIF" not in {b["titre"] for b in sections["Société"]["blocs"]}


def test_synthese_bureau_calculee_sur_les_donnees():
    lignes = [
        _ligne_membre(1, "EC Indépendant", nif=None, nhv=10),
        _ligne_membre(2, "EC Cabinet", nhv=None),
    ]
    donnees = _donnees([R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes])
    assert any(c.startswith("Sans conclusion : 2 membres sur 2") for c in donnees["constats"])
    assert any(c.startswith("Formation : 1 sous le minimum") and "1 sans NHV" in c for c in donnees["constats"])
    assert any(c.startswith("NIF manquant : 1 EC indépendants sur 1") for c in donnees["constats"])
    assert any("source officielle de la cotisation" in c for c in donnees["decisions_attendues"])
    assert any("% 120 FOR" in c for c in donnees["decisions_attendues"])
    assert donnees["titre_situation"].endswith("1 dossier")
    assert donnees["titre_situation"].startswith("Le critère le plus souvent en défaut")
    sections = {s["categorie"]: s for s in donnees["sections"]}
    assert sections["EC Cabinet"]["constat"] == "Aucun défaut relevé sur les critères renseignés."
    assert sections["EC Cabinet"]["situation"][0]["etats"]["inconnu"] == 1

    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        textes = [page.extract_text() or "" for page in pdf.pages]
    assert "Synthèse pour le Bureau" in textes[0]
    assert "Décisions attendues" in textes[0]
    # Les listes viennent après l'analyse, en annexes.
    assert any(t.lstrip().startswith("Annexe 1.") for t in textes[1:])
    classeur = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    assert classeur.sheetnames[0] == "Synthèse Bureau"


def test_synthese_sans_rien_a_signaler():
    donnees = _donnees([_dossier(1, "EC/16.00001")])
    assert not any(c.startswith("Formation") for c in donnees["constats"])
    assert donnees["decisions_attendues"] == []
    assert R.build_pdf(donnees).startswith(b"%PDF")


def test_nif_de_remplissage_doublons_et_numero_provisoire_signales():
    lignes = [
        _ligne_membre(1, "EC Indépendant", nif="-"),
        _ligne_membre(2, "EC Indépendant", nif="N/A"),
        _ligne_membre(3, "EC Indépendant", nif="A 0705673 A"),
        _ligne_membre(4, "EC Indépendant", nif="123456789XYZ"),
        _ligne_membre(5, "EC Cabinet", nom="MEME NOM"),
        _ligne_membre(6, "EC Cabinet", nom="Meme  Nom"),
        _ligne_membre(7, "EC Cabinet", numero_ordre="EC/24.00000"),
    ]
    donnees = _donnees([R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes])
    nif = next(c for c in donnees["criteres"] if c["critere"] == "nif")
    assert (nif["conformes"], nif["defauts"]) == (2, 2)

    def numeros(type_: str) -> list[str]:
        return [r["numero_ordre"] for r in donnees["registre"] if r["type"] == type_]

    assert numeros("NIF de forme inhabituelle") == ["EC/16.00004"]
    assert numeros("Numéro d'ordre provisoire") == ["EC/24.00000"]
    assert len(numeros("Même nom sous plusieurs numéros d'ordre")) == 1


def test_un_homonyme_de_dossier_analyse_reste_a_l_analyse():
    donnees = _donnees([_dossier(1, "EC/16.00001", nom="X"), _dossier(2, "EC/16.00002", nom="X")])
    assert "Même nom sous plusieurs numéros d'ordre" not in _types(donnees)


def test_numero_d_ordre_unique_rang_et_repetition_signales():
    lignes = [
        _ligne_membre(1, numero_ordre="EC/16.00092", nom="A"),
        _ligne_membre(2, numero_ordre="EC/19.00092", nom="B"),
        _ligne_membre(3, numero_ordre="SEC/19.00092", nom="C", categorie="Société"),
        _ligne_membre(4, numero_ordre="EC/20.00000", nom="D"),
        _ligne_membre(5, numero_ordre="EC/21.00000", nom="E"),
    ]
    donnees = _donnees(
        [R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes],
        repetitions=[{"numero_ordre": "EC/16.00001", "lignes": 2, "noms": "X / Y"}],
    )
    rangs = [r for r in donnees["registre"] if r["type"] == R.TYPE_RANG_REPETE]
    # Même rang : seuls les deux EC. SEC est une autre série, et le rang zéro a son propre contrôle.
    assert len(rangs) == 1
    assert "EC/16.00092 : A; EC/19.00092 : B" in rangs[0]["observation"]
    assert any(r["type"] == "Numéro d'ordre en double" and "EC/16.00001" in r["observation"] for r in donnees["registre"])
    assert any(c.startswith("N° d'ordre non uniques à vérifier : 2") for c in donnees["constats"])
    assert donnees["decisions_attendues"][0].startswith("Arbitrer les N° d'ordre")


def test_fiche_d_essai_reconnue():
    assert R.est_fiche_essai("TEST TESTU Toto")
    assert not R.est_fiche_essai("TESTA Jean")
    assert not R.est_fiche_essai("MUTEST Jean")
    assert not R.est_fiche_essai(None)


def test_ecartes_mentionnes_dans_la_methode():
    donnees = _donnees(
        [_dossier(1, "EC/19.00092")],
        numeros_ecartes={"EC/16.00092": "erroné, retenu EC/19.00092"},
        fiches_essai_ecartees=1,
    )
    regles = dict(R._methode(donnees))
    assert "EC/16.00092 (erroné, retenu EC/19.00092)" in regles["Lignes écartées"]
    assert "fiches d'essai : 1" in regles["Lignes écartées"]
