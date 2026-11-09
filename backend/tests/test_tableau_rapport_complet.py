"""Rapport complet du Tableau : le tableau de bord, puis la liste ; toutes catégories ou une seule."""
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
from app.modules.tableau.service import _norm_numero_ordre, export_rapport_complet, import_excel, run_analyse, run_analyse_base

from test_tableau_module import _make_import_bytes


def _ctx(**overrides) -> R.ContexteRapport:
    valeurs = {
        "exercice": "2026",
        "date_situation": date(2026, 1, 10),
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


def _donnees(dossiers, **ctx):
    return R.construire_donnees(dossiers, _ctx(**ctx))


def _texte_pdf(donnees) -> list[str]:
    with pdfplumber.open(io.BytesIO(R.build_pdf(donnees))) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _critere(donnees, cle: str) -> dict:
    return next(c for c in donnees["criteres"] if c["critere"] == cle)


def test_les_exemptes_de_formation_sortent_du_taux_du_critere():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", heures_forco=120.0),
        _dossier(2, "EC/16.00002", V.NON_INSCRIT, heures_forco=0.0),
        _dossier(3, "EC/25.00003", heures_forco=0.0, anciennete="Nouveau"),
    ])
    formation = _critere(donnees, "formation")
    assert (formation["conformes"], formation["defauts"], formation["soumis"]) == (1, 1, 2)


def test_le_seuil_vient_des_reglages_de_l_exercice():
    dossier = _dossier(1, "EC/16.00001", heures_forco=100.0)
    assert _critere(_donnees([dossier]), "formation")["defauts"] == 1
    assert _critere(_donnees([dossier], reglages=V.TableauReglages(heures_formation_min=80)), "formation")["defauts"] == 0


def test_les_quatre_etats_de_la_page_tableau():
    donnees = _donnees([
        _dossier(1, "EC/16.00001"),
        _dossier(2, "EC/16.00002", V.NON_INSCRIT),
        _dossier(3, "EC/16.00003", V.A_DELIBERER),
        _dossier(4, "EC/16.00004", None),
    ])
    assert donnees["conclusions"] == {"en_regle": 1, "a_deliberer": 1, "non_en_regle": 1, "sans_conclusion": 1}
    assert donnees["par_categorie"] == [{"categorie": "EC Cabinet", "total": 4, **donnees["conclusions"]}]


def test_les_stagiaires_restent_hors_du_tableau_de_bord():
    donnees = _donnees([_dossier(1, "EC/16.00001"), _dossier(2, "ECS/24.0001", V.NON_APPLICABLE, categorie="Stagiaire")])
    assert donnees["total"] == 1
    assert donnees["conclusions"]["en_regle"] == 1
    assert len(donnees["stagiaires"]) == 1


def test_rapport_limite_a_une_categorie():
    dossiers = [
        _dossier(1, "EC/16.00001"),
        _dossier(2, "SEC/16.00002", V.NON_INSCRIT, categorie="Société", sexe=None),
        _dossier(3, "ECS/24.0003", V.NON_APPLICABLE, categorie="Stagiaire"),
    ]
    donnees = _donnees(dossiers, categorie="Société")
    assert donnees["total"] == 1
    assert donnees["conclusions"]["non_en_regle"] == 1
    assert [s["categorie"] for s in donnees["sections"]] == ["Société"]
    assert donnees["stagiaires"] == []
    assert R.titre_rapport(donnees["ctx"]) == "Rapport Tableau 2027 – Société"
    assert openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees))).sheetnames == ["Graphiques", "SOCIETES"]
    assert "Rapport Tableau 2027 – Société" in _texte_pdf(donnees)[0]


def test_profil_des_membres_comme_sur_la_page_tableau():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", sexe="F", actif=True),
        _dossier(2, "EC/16.00002", sexe="M", actif=False),
        # Inscrit l'année de l'exercice : nouveau.
        _dossier(3, "EC/26.00003", sexe=None, actif=None),
        _dossier(4, "SEC/16.00004", categorie="Société", sexe=None),
    ])
    profil = {rubrique: dict(parts) for rubrique, _, parts in donnees["profil"]}
    # Sexe et activité portent sur les personnes physiques ; l'ancienneté sur tous.
    assert profil["Sexe"] == {"Hommes": 1, "Femmes": 1, "Non renseigné": 1}
    assert profil["Actifs"] == {"Actifs": 1, "Inactifs": 1, "Non renseigné": 1}
    assert profil["Ancienneté"] == {"Anciens": 3, "Nouveaux": 1}


def test_excel_tableau_de_bord_puis_la_liste():
    donnees = _donnees([
        _dossier(1, "EC/16.00001", V.NON_INSCRIT, nom="=HACK()", heures_forco=10.0),
        _dossier(2, "EC/16.00002"),
    ])
    wb = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    assert wb.sheetnames == ["Graphiques", "EC EN CABINET"]
    graphiques = wb["Graphiques"]._charts
    assert len(graphiques) == 2  # l'anneau des conclusions, les barres des critères
    barres = graphiques[1]
    assert barres.grouping == "percentStacked"
    assert [s.graphicalProperties.solidFill.srgbClr for s in barres.series] == ["0CA30C", "D03B3B", "C3C2B7"]
    liste = wb["EC EN CABINET"]
    assert liste.auto_filter.ref is None
    assert len(liste.tables) == 1
    noms = [liste.cell(ligne, 3).value for ligne in (5, 6)]
    assert "'=HACK()" in noms
    assert not liste._charts


def test_pdf_la_liste_puis_le_tableau_de_bord():
    donnees = _donnees([_dossier(1, "EC/16.00001"), _dossier(2, "EC/16.00002", V.NON_INSCRIT, heures_forco=10.0)])
    pages = _texte_pdf(donnees)
    # La liste suit le titre, sur la première page ; les graphiques viennent à la fin.
    assert "10 janvier 2026" in pages[0]
    assert "SECTION A1" in pages[0]
    assert "Conformité de la base" not in pages[0]
    assert pages[-1].lstrip().startswith("Graphiques")
    assert "Conformité de la base" in pages[-1]
    assert "Conformité par critère" in pages[-1]
    assert "50 %" in pages[-1]
    assert "Synthèse" not in "\n".join(pages)


def test_pdf_tolere_un_import_vide_et_des_caracteres_a_echapper():
    assert R.build_pdf(_donnees([])).startswith(b"%PDF")
    assert R.build_excel(_donnees([])).startswith(b"PK")
    assert R.build_pdf(_donnees([_dossier(1, "EC/16.00001", nom="A & B <SARL>")])).startswith(b"%PDF")


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
        assert nom_pdf == f"Rapport_Tableau_2062_{outcome.imp.id}.pdf"
        excel, nom_excel = await export_rapport_complet(db_session, org, outcome.imp.id, "xlsx")
        assert excel.startswith(b"PK")
        assert nom_excel.endswith(".xlsx")

    @pytest.mark.asyncio
    async def test_telechargement_par_categorie(self, db_session, test_admin_user):
        org = test_admin_user.organisation_id
        outcome = await import_excel(
            db_session, test_admin_user, org, "categorie.xlsx",
            _make_import_bytes({"numero_ordre": "EC/18.70068"}), "2062", date_situation=date(2062, 5, 1),
        )
        await run_analyse(db_session, test_admin_user, org, outcome.imp.id)
        contenu, nom = await export_rapport_complet(db_session, org, outcome.imp.id, "xlsx", categorie="EC Cabinet")
        assert nom == f"Rapport_Tableau_2063_{outcome.imp.id}_EC_Cabinet.xlsx"
        assert openpyxl.load_workbook(io.BytesIO(contenu)).sheetnames == ["Graphiques", "EC EN CABINET"]
        with pytest.raises(HTTPException) as vide:
            await export_rapport_complet(db_session, org, outcome.imp.id, "pdf", categorie="Société")
        assert vide.value.status_code == 409
        assert "Société" in vide.value.detail

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
        assert nom == "Rapport_Tableau_2040_base.xlsx"
        feuille = openpyxl.load_workbook(io.BytesIO(contenu))["EC EN CABINET"]
        assert {feuille.cell(ligne, 2).value for ligne in range(5, 7)} == {"EC/18.70063", "EC/18.70064"}

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
    session = {"Authorization": f"Bearer {admin_access_token}"}

    assert (await app_client.get(url)).status_code == 401
    reponse = await app_client.get(url, params={"format": "pdf"}, headers=session)
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert f"Rapport_Tableau_2030_{outcome.imp.id}.pdf" in reponse.headers["content-disposition"]
    assert reponse.content.startswith(b"%PDF")

    par_categorie = await app_client.get(url, params={"format": "pdf", "categorie": "EC Cabinet"}, headers=session)
    assert par_categorie.status_code == 200
    assert f"Rapport_Tableau_2030_{outcome.imp.id}_EC_Cabinet.pdf" in par_categorie.headers["content-disposition"]
    # Les stagiaires n'ont pas de rapport : leur catégorie n'est pas un choix.
    assert (await app_client.get(url, params={"categorie": "Stagiaire"}, headers=session)).status_code == 422


def _ligne_membre(id_: int, categorie: str = "EC Cabinet", **overrides):
    valeurs = {
        "genre": "PP", "id": id_, "numero_ordre": f"EC/16.{id_:05d}", "nom": f"MEMBRE {id_}", "categorie": categorie,
        "nif": None, "cabinet": "CABINET A", "email": f"m{id_}@example.cd", "telephone": f"+24381{id_:07d}",
        "assurance": None, "sexe": "F", "nhv": 130, "actif": True, "province": "KINSHASA", "erreurs": [],
    }
    return SimpleNamespace(**{**valeurs, **overrides})


def test_membres_sans_dossier_sans_conclusion_inventee():
    ca = {_norm_numero_ordre("EC/16.00002"): False}
    assurances = {_norm_numero_ordre("EC/16.00002"): True}
    dossiers = [
        R.membre_en_dossier(_ligne_membre(1, nhv=None, erreurs=[{"message": "Sexe illisible"}]), {}, {}, _norm_numero_ordre),
        R.membre_en_dossier(_ligne_membre(2, "EC Indépendant", nhv=90), ca, assurances, _norm_numero_ordre),
    ]
    assert dossiers[1]["assurance"] is True
    donnees = _donnees(dossiers)
    assert donnees["conclusions"]["sans_conclusion"] == 2
    assert _critere(donnees, "cotisation")["inconnus"] == 2
    assert dict(next(parts for rubrique, _, parts in donnees["profil"] if rubrique == "Actifs"))["Actifs"] == 2
    assert "Sans conclusion" in _texte_pdf(donnees)[-1]
    liste = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))["EC EN CABINET"]
    entetes = [c.value for c in liste[4]]
    assert liste.cell(5, entetes.index("Actif") + 1).value == "OUI"


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
    assert _critere(donnees, "assurance")["soumis"] == 2
    sections = {s["categorie"]: s for s in donnees["sections"]}
    assert list(sections) == ["EC Cabinet", "EC Indépendant", "Société", "EC Salarié"]
    for categorie in ("EC Cabinet", "EC Salarié"):
        assert "Assurance valide" not in sections[categorie]["entetes"]
        assert "Chiffre d'affaires" not in sections[categorie]["entetes"]
    assert "H.Formation" not in sections["Société"]["entetes"]
    assert {"Assurance valide", "H.Formation", "Chiffre d'affaires"} <= set(sections["EC Indépendant"]["entetes"])

    classeur = openpyxl.load_workbook(io.BytesIO(R.build_excel(donnees)))
    feuille = classeur["EC EN CABINET"]
    assert feuille["A1"].value.startswith("SECTION A1")
    assert "Assurance valide" not in [c.value for c in feuille[4]]
    # Plusieurs catégories : le tableau de bord ajoute les conclusions par catégorie.
    assert len(classeur["Graphiques"]._charts) == 3
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
    assert "Actif" in "\n".join(_texte_pdf(donnees))


def test_nif_exige_des_ec_independants_seulement():
    lignes = [
        _ligne_membre(1, "EC Indépendant", nif=None),
        _ligne_membre(2, "EC Indépendant", nif="A1810696X"),
        _ligne_membre(3, "EC Cabinet", nif=None),
        _ligne_membre(4, "Société", nif=None, sexe=None, nhv=None),
        _ligne_membre(5, "EC Indépendant", nif="-"),
    ]
    donnees = _donnees([R.membre_en_dossier(l, {}, {}, _norm_numero_ordre) for l in lignes])
    nif = _critere(donnees, "nif")
    # « - » dit justement qu'il n'y a pas de NIF.
    assert (nif["soumis"], nif["conformes"], nif["defauts"]) == (3, 1, 2)
    sections = {s["categorie"]: s for s in donnees["sections"]}
    assert "NIF" in sections["EC Indépendant"]["entetes"]
    assert "NIF" not in sections["EC Cabinet"]["entetes"]


def test_fiche_d_essai_reconnue():
    assert R.est_fiche_essai("TEST TESTU Toto")
    assert not R.est_fiche_essai("TESTA Jean")
    assert not R.est_fiche_essai("MUTEST Jean")
    assert not R.est_fiche_essai(None)
