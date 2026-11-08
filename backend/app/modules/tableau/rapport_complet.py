"""Rapport complet du Tableau (PDF et Excel) : le tableau de bord, puis la liste.

Le tableau de bord reprend les graphiques de la page Tableau : conformité de la base,
conformité par critère, conclusions par catégorie, profil des membres. Viennent ensuite
les listes, une section par catégorie, comme le Tableau publié. Le rapport peut se
limiter à une catégorie : graphiques et liste ne portent alors que sur elle.

Tout vient des dossiers analysés et des réglages de l'exercice : aucun chiffre, seuil ni
date n'est écrit en dur. La conclusion retenue est celle de l'analyse, décisions de la
commission comprises. Le module ne fait que lire : rien n'est écrit en base.
"""
from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable
from xml.sax.saxutils import escape

from . import verdict as verdict_engine

# Même découpage que le Tableau publié : une section, une liste, ses propres statistiques.
SECTIONS = [
    ("EC Cabinet", "SECTION A1 : EXPERTS-COMPTABLES EN CABINET", "EC EN CABINET"),
    ("EC Indépendant", "SECTION A2 : EXPERTS-COMPTABLES INDEPENDANTS", "EC INDEPENDANTS"),
    ("Société", "SECTION B : SOCIETES D'EXPERTISE COMPTABLE", "SOCIETES"),
    ("EC Salarié", "SECTION C : EXPERTS-COMPTABLES SALARIES", "EC SALARIES"),
]
ORDRE_CATEGORIES = [section[0] for section in SECTIONS]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

CRITERES = [
    ("cotisation", "Cotisation"),
    ("formation", "Formation (NHV)"),
    ("assurance", "Assurance"),
    ("chiffre_affaires", "Chiffre d'affaires"),
    ("nif", "NIF (EC indépendants)"),
]
# « - » ou « N/A » dans la colonne NIF disent justement qu'il n'y en a pas.
NIF_ABSENTS = {"", "-", "--", "N/A", "NA", "NEANT", "NÉANT", "AUCUN"}
# Conclusion non établie (membre sans dossier, cotisation absente des fichiers).
A_COMPLETER = "À compléter"
MOTIF_A_COMPLETER = "Conclusion non établie : la cotisation ne figure pas dans les fichiers importés."
VERT, MARINE = "3E9C76", "16324F"
GRIS_CLAIR, GRIS_MOYEN, GRIS_TEXTE = "F3F5F7", "D9E0E6", "44515C"

# Les couleurs du tableau de bord de la page Tableau : une couleur a le même sens partout.
# États des conclusions (réservés à elles), avec l'encre lisible sur chacun.
ETATS_CONCLUSION = [
    ("en_regle", "En règle", "0CA30C", "FFFFFF"),
    ("a_deliberer", "À délibérer", "FAB219", "0B0B0B"),
    ("non_en_regle", "Non en règle", "D03B3B", "FFFFFF"),
    ("sans_conclusion", "Sans conclusion", "C3C2B7", "0B0B0B"),
]
MARQUE, MARQUE_PISTE = "1F6B5C", "E4EDEB"
# Profil : la marque, une teinte moyenne, puis le gris des non renseignés. Validé pour les
# daltonismes (ΔE ≥ 12) ; les valeurs sont toujours écrites à côté.
TEINTES_PROFIL = ["1F6B5C", "5FA392", "C3C2B7"]
CRITERES_TABLEAU_DE_BORD = {
    "cotisation": ("Cotisation à jour", "à jour", "en défaut"),
    "formation": ("Formation (NHV) atteinte", "atteinte", "insuffisante"),
    "assurance": ("Assurance valide", "valide", "non valide"),
    "chiffre_affaires": ("Chiffre d'affaires déclaré", "déclaré", "non déclaré"),
    "nif": ("NIF renseigné (EC indépendants)", "renseigné", "manquant"),
}


@dataclass
class ContexteRapport:
    exercice: str
    date_situation: date | None
    source: str
    organisation: str
    reglages: verdict_engine.TableauReglages
    exercice_annee: int | None
    genere_le: date
    contact: str = ""
    logo: bytes | None = None
    # Rapport limité à une catégorie (« EC Cabinet »…) ; None : toutes.
    categorie: str | None = None


def est_fiche_essai(nom: Any) -> bool:
    """Fiche d'essai laissée dans un fichier source (« TEST TESTU Toto ») : pas un membre."""
    mots = _txt(nom).casefold().split()
    return bool(mots) and mots[0] == "test"


def fdate(valeur: date | None) -> str:
    if valeur is None:
        return "date non renseignée"
    return f"{'1er' if valeur.day == 1 else valeur.day} {MOIS[valeur.month - 1]} {valeur.year}"


def nombre(valeur: float, decimales: int = 1) -> str:
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


def heures_txt(valeur: float | None) -> str:
    return "—" if valeur is None else f"{float(valeur):g}".replace(".", ",")


def _txt(valeur: Any) -> str:
    return " ".join(str(valeur).split()) if valeur is not None else ""


def _maj(valeur: Any) -> str:
    return _txt(valeur).upper()


def nom_complet(dossier: dict[str, Any]) -> str:
    return " ".join(v for v in (_txt(dossier.get("nom")), _txt(dossier.get("prenom"))) if v)


def norm_categorie(valeur: Any) -> str:
    texte = _txt(valeur)
    return "Société" if texte == "SEC" else (texte or "Non classé")


def classe_conclusion(valeur: Any) -> str:
    texte = _maj(valeur)
    if texte.startswith("NON INSCRIT"):
        return verdict_engine.NON_INSCRIT
    if texte.startswith("INSCRIT"):
        return verdict_engine.INSCRIT
    if texte in {verdict_engine.A_DELIBERER, "A DELIBERER"}:
        return verdict_engine.A_DELIBERER
    return texte or A_COMPLETER


def membre_en_dossier(ligne: Any, ca_par_numero: dict[str, bool], assurance_par_numero: dict[str, bool], norm_numero) -> dict[str, Any]:
    """Membre issu des fichiers sources, sans dossier : mêmes champs, mais aucune conclusion."""
    cle = norm_numero(ligne.numero_ordre) or ""
    # Assurance et chiffre d'affaires ne concernent que les sociétés et les EC indépendants.
    criteres = verdict_engine.CATEGORIE_CRITERES.get(ligne.categorie, [])
    assurance = None
    if "assurance" in criteres:
        assurance = ligne.assurance if ligne.assurance is not None else assurance_par_numero.get(cle)
    chiffre_affaires = ca_par_numero.get(cle) if "chiffre_affaires" in criteres else None
    return {
        "id": f"{ligne.genre}-{ligne.id}",
        "numero_ordre": ligne.numero_ordre or None,
        "nom": ligne.nom,
        "prenom": None,
        "categorie": ligne.categorie,
        "cotisation_payee": None,
        "assurance": assurance,
        "chiffre_affaires": chiffre_affaires,
        "heures_forco": float(ligne.nhv) if ligne.nhv is not None else None,
        "sexe": ligne.sexe,
        "age": None,
        "nif": ligne.nif,
        "anciennete": None,
        "telephone": ligne.telephone,
        "email": ligne.email,
        "cabinet": ligne.cabinet,
        "conclusion": None,
        "conclusion_motif": MOTIF_A_COMPLETER,
        "actif": ligne.actif,
        "province": ligne.province,
        "raw_data": {"signalements": [str(e.get("message")) for e in (ligne.erreurs or []) if e.get("message")]},
    }


def nif_renseigne(dossier: dict[str, Any]) -> bool:
    return _maj(dossier.get("nif")) not in NIF_ABSENTS


def criteres_rapport(categorie: Any, reglages: verdict_engine.TableauReglages | None = None) -> list[str]:
    """Critères du moteur de verdict (réglages compris), plus le NIF exigé des EC indépendants."""
    criteres = list(verdict_engine.criteres_requis(categorie or "", reglages) or [])
    return criteres + ["nif"] if categorie == "EC Indépendant" else criteres


def _etat_critere(dossier: dict[str, Any], critere: str, ctx: ContexteRapport) -> str:
    """conforme / defaut / exempte / inconnu, selon le moteur de verdict."""
    if critere == "nif":
        return "conforme" if nif_renseigne(dossier) else "defaut"
    raw = dossier.get("raw_data") or {}
    evaluation = {**dossier, "hformation": raw.get("hformation")}
    nouveau = verdict_engine.est_nouveau(evaluation, ctx.exercice_annee, ctx.reglages)
    if critere == "formation" and nouveau:
        return "exempte"
    valeur = verdict_engine._critere_ok(critere, evaluation, nouveau, ctx.reglages)
    return "inconnu" if valeur is None else ("conforme" if valeur else "defaut")


def _oui_non(valeur: Any) -> str:
    return "OUI" if valeur is True else ("NON" if valeur is False else "")


def _libelle_anciennete(dossier: dict[str, Any], ctx: ContexteRapport) -> str | None:
    return verdict_engine.libelle_anciennete(dossier.get("numero_ordre"), ctx.exercice_annee) or _txt(dossier.get("anciennete")) or None


def _section(categorie: str, titre: str, feuille: str, groupe: list[dict[str, Any]], ctx: ContexteRapport) -> dict[str, Any]:
    """La liste d'une section, avec les seules colonnes de critères qui la concernent."""
    groupe = sorted(groupe, key=lambda d: nom_complet(d).casefold())
    criteres = criteres_rapport(categorie, ctx.reglages)

    def formation_txt(dossier: dict[str, Any]) -> str:
        return {"conforme": "OUI", "defaut": "NON", "exempte": "N/A"}.get(_etat_critere(dossier, "formation", ctx), "")

    societe = categorie == "Société"
    colonnes: list[tuple[str, Any, bool]] = [
        ("N° d'ordre", lambda d: _txt(d.get("numero_ordre")), False),
        ("Dénomination" if societe else "Nom, post-noms et prénoms", nom_complet, False),
    ]
    if societe:
        colonnes += [
            ("Raison sociale", lambda d: _txt((d.get("raw_data") or {}).get("raison_sociale")), True),
            ("Associé gérant", lambda d: _txt((d.get("raw_data") or {}).get("gerant")), True),
        ]
    else:
        colonnes.append(("Sexe", lambda d: _txt(d.get("sexe")), True))
        colonnes.append(("Actif", lambda d: _oui_non(d.get("actif")), True))
    colonnes += [("N° téléphone", lambda d: _txt(d.get("telephone")), True), ("E-mail", lambda d: _txt(d.get("email")), True)]
    if categorie in {"EC Cabinet", "EC Salarié"}:
        colonnes.append(("Cabinet d'attache" if categorie == "EC Cabinet" else "Employeur", lambda d: _txt(d.get("cabinet")), True))
    if categorie in {"EC Indépendant", "Société"}:
        # Exigé des EC indépendants : la colonne reste, même vide, pour montrer ce qui manque.
        colonnes.append(("NIF", lambda d: _txt(d.get("nif")), categorie == "Société"))
    colonnes += [
        ("Ancienneté", lambda d: _libelle_anciennete(d, ctx) or "Non renseignée", False),
        ("Cotisation", lambda d: _oui_non(d.get("cotisation_payee")), False),
    ]
    if "assurance" in criteres:
        colonnes.append(("Assurance valide", lambda d: _oui_non(d.get("assurance")), False))
    if "formation" in criteres:
        colonnes.append(("H.Formation", formation_txt, False))
    if "chiffre_affaires" in criteres:
        colonnes.append(("Chiffre d'affaires", lambda d: _oui_non(d.get("chiffre_affaires")), False))
    colonnes.append(("Conclusion", lambda d: verdict_engine.libelle_conclusion(classe_conclusion(d.get("conclusion"))), False))
    if "formation" in criteres:
        colonnes.append(("NHV", lambda d: d.get("heures_forco"), False))
    # Une colonne facultative vide n'apporte rien : les fichiers ne la renseignent pas tous.
    colonnes = [(libelle, lire, False) for libelle, lire, facultative in colonnes if not facultative or any(lire(d) for d in groupe)]
    entetes = ["N°"] + [libelle for libelle, _, _ in colonnes]
    lignes = [[index] + [lire(d) for _, lire, _ in colonnes] for index, d in enumerate(groupe, 1)]
    return {"categorie": categorie, "titre": titre, "feuille": feuille, "total": len(groupe), "entetes": entetes, "lignes": lignes}


def _conclusions(groupe: list[dict[str, Any]]) -> dict[str, int]:
    """Les quatre états du tableau de bord : tout ce qui n'est pas tranché est « sans conclusion »."""
    classes = Counter(classe_conclusion(d.get("conclusion")) for d in groupe)
    comptes = {
        "en_regle": classes[verdict_engine.INSCRIT],
        "a_deliberer": classes[verdict_engine.A_DELIBERER],
        "non_en_regle": classes[verdict_engine.NON_INSCRIT],
    }
    comptes["sans_conclusion"] = len(groupe) - sum(comptes.values())
    return comptes


def _parts(comptes: Counter, libelles: list[tuple[str, str]], total: int) -> list[tuple[str, int]]:
    """Les parts d'un profil dans l'ordre voulu ; le reste du total va à « Non renseigné »."""
    parts = [(libelle, comptes[cle]) for cle, libelle in libelles]
    reste = total - sum(n for _, n in parts)
    return parts + ([("Non renseigné", reste)] if reste else [])


def construire_donnees(dossiers: list[dict[str, Any]], ctx: ContexteRapport) -> dict[str, Any]:
    stagiaires = [d for d in dossiers if d.get("categorie") == "Stagiaire"]
    membres = [d for d in dossiers if d.get("categorie") != "Stagiaire"]
    if ctx.categorie:
        membres = [d for d in membres if norm_categorie(d.get("categorie")) == ctx.categorie]
        stagiaires = []
    categories = ORDRE_CATEGORIES + sorted({norm_categorie(d.get("categorie")) for d in membres} - set(ORDRE_CATEGORIES))

    par_categorie = []
    for categorie in categories:
        groupe = [d for d in membres if norm_categorie(d.get("categorie")) == categorie]
        if groupe:
            par_categorie.append({"categorie": categorie, "total": len(groupe), **_conclusions(groupe)})

    criteres = []
    for critere, _ in CRITERES:
        etats = Counter(
            _etat_critere(d, critere, ctx) for d in membres
            if critere in criteres_rapport(d.get("categorie"), ctx.reglages)
        )
        # Comme la page Tableau : la part des membres soumis au critère qui le remplissent,
        # exemptés de formation (nouveaux membres) hors du compte.
        soumis = etats["conforme"] + etats["defaut"] + etats["inconnu"]
        if soumis:
            libelle, ok, ko = CRITERES_TABLEAU_DE_BORD[critere]
            criteres.append({
                "critere": critere, "libelle": libelle, "ok": ok, "ko": ko,
                "conformes": etats["conforme"], "defauts": etats["defaut"], "inconnus": etats["inconnu"], "soumis": soumis,
            })

    physiques = [d for d in membres if norm_categorie(d.get("categorie")) != "Société"]
    anciennete = Counter(_libelle_anciennete(d, ctx) for d in membres)
    profil = [
        ("Sexe", "personnes physiques", _parts(Counter(_maj(d.get("sexe"))[:1] for d in physiques), [("M", "Hommes"), ("F", "Femmes")], len(physiques))),
        ("Ancienneté", "selon le N° d'ordre", _parts(anciennete, [("Ancien", "Anciens"), ("Nouveau", "Nouveaux")], len(membres))),
        ("Actifs", "personnes physiques", _parts(Counter(d.get("actif") for d in physiques), [(True, "Actifs"), (False, "Inactifs")], len(physiques))),
    ]

    sections = [
        (categorie, titre, feuille) for categorie, titre, feuille in
        [*SECTIONS, *((c, c.upper(), c.upper()[:31]) for c in categories if c not in ORDRE_CATEGORIES)]
    ]
    return {
        "ctx": ctx,
        "total": len(membres),
        "conclusions": _conclusions(membres),
        "par_categorie": par_categorie,
        "criteres": criteres,
        "profil": [(rubrique, aide, parts) for rubrique, aide, parts in profil if sum(n for _, n in parts)],
        "sections": [
            _section(categorie, titre, feuille, [d for d in membres if norm_categorie(d.get("categorie")) == categorie], ctx)
            for categorie, titre, feuille in sections
            if any(norm_categorie(d.get("categorie")) == categorie for d in membres)
        ],
        "stagiaires": stagiaires,
    }


def titre_rapport(ctx: ContexteRapport) -> str:
    titre = f"Rapport complet du Tableau {ctx.exercice}"
    return f"{titre} – {ctx.categorie}" if ctx.categorie else titre


def _part(valeur: int, total: int) -> float:
    return valeur / total if total else 0.0


# ── Excel ────────────────────────────────────────────────────────────────────


def build_excel(d: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, DoughnutChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.chart.marker import DataPoint
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    ctx: ContexteRapport = d["ctx"]
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = titre_rapport(ctx)
    wb.properties.creator = ctx.organisation
    ligne_fine = Border(bottom=Side(style="hair", color=GRIS_MOYEN))
    tables = {"n": 0}

    def sure(valeur: Any) -> Any:
        # Une valeur importée commençant par « = » resterait sinon une formule exécutable.
        if isinstance(valeur, str) and valeur.startswith("="):
            return "'" + valeur
        return valeur

    def feuille(nom: str, texte: str, sous_titre: str):
        ws = wb.create_sheet(nom[:31])
        ws["A1"] = texte
        ws["A1"].font = Font(size=16, bold=True, color=MARINE)
        ws["A2"] = sous_titre
        ws["A2"].font = Font(size=10, italic=True, color=GRIS_TEXTE)
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = VERT
        ws.page_setup.orientation = "landscape"
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
        ws.oddFooter.center.text = f"{ctx.organisation} · Tableau {ctx.exercice}"
        ws.oddFooter.right.text = "Page &P / &N"
        return ws

    def bloc(ws, ligne: int, titre: str, aide: str) -> None:
        ws.cell(ligne, 1, titre).font = Font(size=12, bold=True, color=MARINE)
        ws.cell(ligne + 1, 1, aide).font = Font(size=9, italic=True, color=GRIS_TEXTE)

    def matrice(ws, ligne: int, entetes: list[str], lignes: list[list[Any]], tableau: bool = False, formats: dict[int, str] | None = None) -> int:
        for colonne, entete in enumerate(entetes, 1):
            cellule = ws.cell(ligne, colonne, entete)
            cellule.fill = PatternFill("solid", fgColor=VERT)
            cellule.font = Font(bold=True, color="FFFFFF")
            cellule.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for decalage, valeurs in enumerate(lignes, 1):
            for colonne, valeur in enumerate(valeurs, 1):
                cellule = ws.cell(ligne + decalage, colonne, sure(valeur))
                cellule.alignment = Alignment(vertical="top", wrap_text=True)
                cellule.border = ligne_fine
                if formats and colonne in formats:
                    cellule.number_format = formats[colonne]
        fin = ligne + len(lignes)
        if tableau and lignes:
            # Le tableau porte ses filtres : ne pas ajouter de filtre de feuille sur la même plage.
            tables["n"] += 1
            t = Table(displayName=f"Rapport{tables['n']}", ref=f"A{ligne}:{get_column_letter(len(entetes))}{fin}")
            t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
            ws.add_table(t)
            ws.freeze_panes = ws.cell(ligne + 1, 1)
        return fin

    def barres_100(ws, ligne_entete: int, nombre: int, colonnes: int, couleurs: list[str], ancre: str, hauteur_cm: float):
        """Barres horizontales empilées à 100 %, une par ligne, les nombres écrits dessus."""
        graphique = BarChart()
        graphique.type = "bar"
        graphique.grouping = "percentStacked"
        graphique.overlap = 100
        graphique.gapWidth = 60
        graphique.height, graphique.width = hauteur_cm, 18
        graphique.x_axis.delete = graphique.y_axis.delete = False
        graphique.x_axis.scaling.orientation = "maxMin"
        graphique.y_axis.numFmt = "0%"
        graphique.y_axis.majorGridlines = None
        graphique.legend.position = "b"
        graphique.add_data(Reference(ws, min_col=2, max_col=1 + colonnes, min_row=ligne_entete, max_row=ligne_entete + nombre), titles_from_data=True)
        graphique.set_categories(Reference(ws, min_col=1, min_row=ligne_entete + 1, max_row=ligne_entete + nombre))
        for serie, couleur in zip(graphique.series, couleurs):
            serie.graphicalProperties.solidFill = couleur
            serie.graphicalProperties.line.solidFill = "FFFFFF"
        graphique.dataLabels = DataLabelList()
        graphique.dataLabels.showVal = True
        graphique.dataLabels.numFmt = "0;;;"  # Masque les zéros, qui encombreraient les barres.
        ws.add_chart(graphique, ancre)

    total = d["total"]
    comptes = d["conclusions"]
    ws = feuille(
        "Tableau de bord", titre_rapport(ctx),
        f"{ctx.organisation} · {ctx.source} · situation du {fdate(ctx.date_situation)} · généré le {fdate(ctx.genere_le)}",
    )
    largeurs = [34, 13, 13, 14, 15, 10]
    for index, largeur in enumerate(largeurs, 1):
        ws.column_dimensions[get_column_letter(index)].width = largeur

    # 1. Conformité de la base
    ligne = 4
    bloc(ws, ligne, "Conformité de la base", f"Exercice {ctx.exercice} · {total} membres")
    ws.cell(ligne + 2, 1, "Taux en règle").font = Font(bold=True, color=GRIS_TEXTE)
    taux = ws.cell(ligne + 2, 2, _part(comptes["en_regle"], total))
    taux.number_format = "0.0%"
    taux.font = Font(size=14, bold=True, color=MARQUE)
    debut = ligne + 4
    lignes = [[libelle, comptes[cle], _part(comptes[cle], total)] for cle, libelle, _, _ in ETATS_CONCLUSION if cle != "sans_conclusion" or comptes[cle]]
    fin = matrice(ws, debut, ["Conclusion", "Membres", "Part"], lignes + [["Total", total, 1 if total else 0]], formats={3: "0.0%"})
    ws.cell(fin, 1).font = ws.cell(fin, 2).font = Font(bold=True)
    anneau = DoughnutChart(holeSize=60)
    anneau.title = "Conclusions"
    anneau.height, anneau.width = 7, 9
    anneau.add_data(Reference(ws, min_col=2, min_row=debut, max_row=debut + len(lignes)), titles_from_data=True)
    anneau.set_categories(Reference(ws, min_col=1, min_row=debut + 1, max_row=debut + len(lignes)))
    couleurs = {libelle: couleur for _, libelle, couleur, _ in ETATS_CONCLUSION}
    for index, (libelle, _, _) in enumerate(lignes):
        point = DataPoint(idx=index)
        point.graphicalProperties.solidFill = couleurs[libelle]
        point.graphicalProperties.line.solidFill = "FFFFFF"
        anneau.series[0].dPt.append(point)
    anneau.dataLabels = DataLabelList()
    anneau.dataLabels.showVal = True
    anneau.legend.position = "r"
    ws.add_chart(anneau, f"H{ligne}")
    ligne = max(fin, ligne + 14) + 2

    # 2. Conformité par critère
    if d["criteres"]:
        bloc(ws, ligne, "Conformité par critère", "Part des membres soumis au critère qui le remplissent")
        debut = ligne + 2
        lignes = [[c["libelle"], c["conformes"], c["defauts"], c["inconnus"], _part(c["conformes"], c["soumis"])] for c in d["criteres"]]
        fin = matrice(ws, debut, ["Critère", "Remplis", "Non remplis", "Non renseignés", "Taux"], lignes, formats={5: "0.0%"})
        barres_100(ws, debut, len(lignes), 3, ["0CA30C", "D03B3B", "C3C2B7"], f"H{ligne}", 2.2 + 1.2 * len(lignes))
        ligne = max(fin, ligne + 4 + int(2 * len(lignes))) + 3

    # 3. Conclusions par catégorie
    if len(d["par_categorie"]) > 1:
        bloc(ws, ligne, "Conclusions par catégorie", "Répartition en pourcentage ; le nombre de membres en dernière colonne")
        debut = ligne + 2
        etats = [(cle, libelle, couleur) for cle, libelle, couleur, _ in ETATS_CONCLUSION if cle != "sans_conclusion" or comptes[cle]]
        lignes = [[l["categorie"], *(l[cle] for cle, _, _ in etats), l["total"]] for l in d["par_categorie"]]
        fin = matrice(ws, debut, ["Catégorie", *(libelle for _, libelle, _ in etats), "Total"], lignes)
        barres_100(ws, debut, len(lignes), len(etats), [couleur for _, _, couleur in etats], f"H{ligne}", 2.2 + 1.2 * len(lignes))
        ligne = max(fin, ligne + 4 + int(2 * len(lignes))) + 3

    # 4. Profil des membres
    if d["profil"]:
        bloc(ws, ligne, "Profil des membres", "Qui compose la base de l'exercice")
        lignes = [
            [f"{rubrique} ({aide})" if rang == 0 else "", libelle, nombre_, _part(nombre_, sum(n for _, n in parts))]
            for rubrique, aide, parts in d["profil"]
            for rang, (libelle, nombre_) in enumerate(parts)
        ]
        matrice(ws, ligne + 2, ["Rubrique", "Valeur", "Effectif", "Part"], lignes, formats={4: "0.0%"})

    # Ensuite, la liste : une feuille par section, comme le Tableau publié.
    tailles = {"N°": 6, "N° d'ordre": 15, "E-mail": 30, "N° téléphone": 18, "Sexe": 6, "Actif": 7, "NHV": 8}
    larges = {"Nom, post-noms et prénoms", "Dénomination", "Raison sociale", "Cabinet d'attache", "Employeur", "Associé gérant"}
    for section in d["sections"]:
        ws = feuille(section["feuille"], section["titre"], f"{ctx.organisation} · {section['total']} membres")
        matrice(ws, 4, section["entetes"], section["lignes"], tableau=True)
        for colonne, entete in enumerate(section["entetes"], 1):
            ws.column_dimensions[get_column_letter(colonne)].width = tailles.get(entete, 36 if entete in larges else 13)

    if d["stagiaires"]:
        ws = feuille("Stagiaires", "Stagiaires", "Sans critère automatique : hors du tableau de bord")
        lignes = [[_txt(s.get("numero_ordre")), nom_complet(s), _txt(s.get("sexe")), _txt(s.get("telephone")), _txt(s.get("email"))] for s in d["stagiaires"]]
        matrice(ws, 4, ["N° d'ordre", "Nom", "Sexe", "Téléphone", "E-mail"], lignes, tableau=True)
        for index, largeur in enumerate([15, 34, 6, 18, 30], 1):
            ws.column_dimensions[get_column_letter(index)].width = largeur

    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────


def build_pdf(d: dict[str, Any]) -> bytes:
    # Helvetica : son jeu de caractères couvre le français, sans police à embarquer dans l'image.
    from reportlab.graphics.shapes import Circle, Drawing, Rect, String, Wedge
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ctx: ContexteRapport = d["ctx"]
    largeur, hauteur = A4
    utile = 180 * mm
    gris = HexColor(f"#{GRIS_TEXTE}")
    marine = HexColor(f"#{MARINE}")
    marque = HexColor(f"#{MARQUE}")
    piste = HexColor(f"#{MARQUE_PISTE}")
    filet = HexColor(f"#{GRIS_MOYEN}")
    corps = ParagraphStyle("corps", fontName="Helvetica", fontSize=9, leading=13, textColor=gris, spaceAfter=6)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=marine, spaceBefore=4, spaceAfter=2, keepWithNext=1)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=marine, spaceBefore=8, spaceAfter=0, keepWithNext=1)
    petit = ParagraphStyle("petit", fontName="Helvetica", fontSize=7.5, leading=10, textColor=gris, spaceAfter=4)
    cellule = ParagraphStyle("cellule", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=gris)
    entete = ParagraphStyle("entete", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5, textColor=colors.white, alignment=TA_CENTER)
    total = d["total"]
    comptes = d["conclusions"]
    etats = [e for e in ETATS_CONCLUSION if e[0] != "sans_conclusion" or comptes["sans_conclusion"]]

    def fmt_pct(valeur: float) -> str:
        return f"{nombre(valeur * 100, 1 if 0 < valeur < 0.1 else 0)} %"

    def texte(dessin: Drawing, x: float, y: float, contenu: str, taille: float = 7.5, gras: bool = False, encre=None, ancre: str = "start") -> None:
        dessin.add(String(x, y, contenu, fontName="Helvetica-Bold" if gras else "Helvetica", fontSize=taille, fillColor=encre or gris, textAnchor=ancre))

    def anneau(dessin: Drawing, cx: float, cy: float, rayon: float, epaisseur: float, part: float) -> None:
        """La piste complète, puis l'arc de la part, depuis midi, dans le sens des aiguilles."""
        dessin.add(Circle(cx, cy, rayon - epaisseur / 2, fillColor=None, strokeColor=piste, strokeWidth=epaisseur))
        if part >= 0.999:
            dessin.add(Circle(cx, cy, rayon - epaisseur / 2, fillColor=None, strokeColor=marque, strokeWidth=epaisseur))
        elif part > 0:
            dessin.add(Wedge(cx, cy, rayon, 90 - 360 * part, 90, radius1=rayon - epaisseur, fillColor=marque, strokeColor=None))

    def barre(dessin: Drawing, x: float, y: float, large: float, haut: float, parts: list[tuple[int, str, str]], somme: int, etiquettes: bool) -> None:
        """Barre à 100 %, un filet blanc entre les parts ; le nombre dessus quand il tient."""
        if not somme:
            dessin.add(Rect(x, y, large, haut, fillColor=piste, strokeColor=None))
            return
        for valeur, couleur, encre in parts:
            if not valeur:
                continue
            l = large * valeur / somme
            dessin.add(Rect(x, y, l, haut, fillColor=HexColor(f"#{couleur}"), strokeColor=colors.white, strokeWidth=0.8))
            if etiquettes and l > stringWidth(str(valeur), "Helvetica-Bold", 7.5) + 3 * mm:
                texte(dessin, x + l / 2, y + haut / 2 - 2.6, str(valeur), 7.5, True, HexColor(f"#{encre}"), "middle")
            x += l

    def legende(dessin: Drawing, x: float, y: float, items: list[tuple[str, str, str]], pas: float | None = None) -> None:
        """Pastille, libellé, valeur : l'identité n'est jamais portée par la seule couleur."""
        for libelle, couleur, valeur in items:
            dessin.add(Rect(x, y, 2.6 * mm, 2.6 * mm, fillColor=HexColor(f"#{couleur}"), strokeColor=None))
            texte(dessin, x + 3.6 * mm, y + 0.5 * mm, libelle, 7.5)
            avance = 3.6 * mm + stringWidth(libelle, "Helvetica", 7.5) + 1.5 * mm
            if valeur:
                texte(dessin, x + avance, y + 0.5 * mm, valeur, 7.5, True, marine)
                avance += stringWidth(valeur, "Helvetica-Bold", 7.5)
            if pas is None:
                x += avance + 5 * mm
            else:
                y -= pas

    def carte_conformite() -> Drawing:
        dessin = Drawing(utile, 46 * mm)
        part = _part(comptes["en_regle"], total)
        anneau(dessin, 22 * mm, 23 * mm, 21 * mm, 4.5 * mm, part)
        texte(dessin, 22 * mm, 23.5 * mm, fmt_pct(part), 16, True, marine, "middle")
        texte(dessin, 22 * mm, 18.5 * mm, "en règle", 8, False, gris, "middle")
        x = 52 * mm
        texte(dessin, x, 37 * mm, f"{total}", 20, True, marine)
        texte(dessin, x + stringWidth(str(total), "Helvetica-Bold", 20) + 2 * mm, 37.5 * mm, "membres analysés selon les règles de délibération", 8.5)
        barre(dessin, x, 20 * mm, utile - x, 10 * mm, [(comptes[cle], couleur, encre) for cle, _, couleur, encre in etats], total, True)
        legende(dessin, x, 11 * mm, [(libelle, couleur, str(comptes[cle])) for cle, libelle, couleur, _ in etats])
        return dessin

    def carte_criteres() -> Drawing:
        criteres = d["criteres"]
        colonne = utile / max(len(criteres), 4)
        # Moins de quatre critères (une seule catégorie) : les anneaux restent centrés.
        marge = (utile - colonne * len(criteres)) / 2
        dessin = Drawing(utile, 50 * mm)
        for rang, c in enumerate(criteres):
            cx = marge + colonne * rang + colonne / 2
            part = _part(c["conformes"], c["soumis"])
            anneau(dessin, cx, 35 * mm, 13 * mm, 3 * mm, part)
            texte(dessin, cx, 33.6 * mm, fmt_pct(part), 11, True, marine, "middle")
            # Un libellé plus large que sa colonne passe sur deux lignes au lieu d'empiéter.
            y = 17 * mm
            for morceau in lignes_a_largeur(c["libelle"], "Helvetica-Bold", 7.8, colonne - 3 * mm):
                texte(dessin, cx, y, morceau, 7.8, True, marine, "middle")
                y -= 3.4 * mm
            texte(dessin, cx, y - 0.6 * mm, f"{c['conformes']} {c['ok']} · {c['defauts']} {c['ko']}", 7.2, False, gris, "middle")
            if c["inconnus"]:
                texte(dessin, cx, y - 4.4 * mm, f"{c['inconnus']} non renseigné{'s' if c['inconnus'] > 1 else ''} ({fmt_pct(_part(c['inconnus'], c['soumis']))})", 6.8, False, gris, "middle")
        return dessin

    def carte_categories() -> Drawing:
        lignes = d["par_categorie"]
        pas = 9 * mm
        dessin = Drawing(utile, 8 * mm + pas * len(lignes))
        legende(dessin, 0, dessin.height - 4 * mm, [(libelle, couleur, "") for _, libelle, couleur, _ in etats])
        y = dessin.height - 8 * mm
        for ligne in lignes:
            y -= pas
            texte(dessin, 0, y + 2.4 * mm, ligne["categorie"], 8, True, marine)
            barre(dessin, 32 * mm, y + 0.6 * mm, utile - 46 * mm, 6.4 * mm, [(ligne[cle], couleur, encre) for cle, _, couleur, encre in etats], ligne["total"], True)
            texte(dessin, utile, y + 2.4 * mm, str(ligne["total"]), 8.5, True, marine, "end")
        return dessin

    def carte_profil() -> Drawing:
        profils = d["profil"]
        colonne = utile / 3
        dessin = Drawing(utile, 34 * mm)
        for rang, (rubrique, aide, parts) in enumerate(profils):
            x = colonne * rang
            somme = sum(n for _, n in parts)
            texte(dessin, x, 29 * mm, rubrique, 9, True, marine)
            texte(dessin, x + stringWidth(rubrique, "Helvetica-Bold", 9) + 2 * mm, 29 * mm, f"{aide} · {somme}", 7.2)
            # Deux parts nommées, puis « Non renseigné » s'il y en a : le gris lui revient toujours.
            teintes = TEINTES_PROFIL[:len(parts)]
            barre(dessin, x, 22 * mm, colonne - 8 * mm, 4 * mm, [(n, teinte, "FFFFFF") for (_, n), teinte in zip(parts, teintes)], somme, False)
            legende(dessin, x, 15.5 * mm, [(libelle, teinte, f"{n} · {fmt_pct(_part(n, somme))}") for (libelle, n), teinte in zip(parts, teintes)], pas=4.6 * mm)
        return dessin

    def lignes_a_largeur(contenu: str, police: str, taille: float, largeur_max: float) -> list[str]:
        mots, lignes = contenu.split(), [""]
        for mot in mots:
            essai = f"{lignes[-1]} {mot}".strip()
            if lignes[-1] and stringWidth(essai, police, taille) > largeur_max:
                lignes.append(mot)
            else:
                lignes[-1] = essai
        return lignes

    def carte(titre: str, aide: str, dessin: Drawing) -> KeepTogether:
        return KeepTogether([Paragraph(escape(titre), h2), Paragraph(escape(aide), petit), dessin, Spacer(1, 2 * mm)])

    def liste(entetes: list[str], lignes: list[list[Any]], tailles: list[float]) -> Table:
        contenu = [[Paragraph(escape(e), entete) for e in entetes]]
        contenu += [[Paragraph(escape(_txt(valeur)), cellule) for valeur in ligne] for ligne in lignes]
        t = Table(contenu, colWidths=[taille * mm for taille in tailles], repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor(f"#{VERT}")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, filet),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            *[("BACKGROUND", (0, i), (-1, i), HexColor(f"#{GRIS_CLAIR}")) for i in range(2, len(contenu), 2)],
        ]))
        return t

    def premiere_page(canvas, doc) -> None:
        canvas.saveState()
        if ctx.logo:
            try:
                canvas.drawImage(ImageReader(io.BytesIO(ctx.logo)), 15 * mm, hauteur - 24 * mm, width=34 * mm, height=16 * mm, preserveAspectRatio=True, mask="auto")
            except (OSError, ValueError):
                pass  # Un logo illisible ne doit pas priver du rapport.
        canvas.setFillColor(marine)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(largeur - 15 * mm, hauteur - 14 * mm, ctx.organisation[:70])
        if ctx.contact:
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(gris)
            canvas.drawRightString(largeur - 15 * mm, hauteur - 19 * mm, ctx.contact[:110])
        pied(canvas, doc)
        canvas.restoreState()

    def pied(canvas, doc) -> None:
        canvas.setStrokeColor(filet)
        canvas.line(15 * mm, 13 * mm, largeur - 15 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(gris)
        canvas.drawString(15 * mm, 9 * mm, f"{titre_rapport(ctx)} · situation du {fdate(ctx.date_situation)} · usage interne")
        canvas.drawRightString(largeur - 15 * mm, 9 * mm, f"Page {doc.page}")

    def page_suivante(canvas, doc) -> None:
        canvas.saveState()
        pied(canvas, doc)
        canvas.restoreState()

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(
        tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
        title=titre_rapport(ctx), author=ctx.organisation,
    )
    S: list[Any] = [
        Spacer(1, 14 * mm),
        Paragraph(escape(titre_rapport(ctx)), ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=marine, spaceAfter=4)),
        Paragraph(f"{escape(ctx.source)} · situation du {fdate(ctx.date_situation)} · généré le {fdate(ctx.genere_le)}", petit),
    ]

    # Le tableau de bord, comme sur la page Tableau.
    if total:
        S.append(carte("Conformité de la base", f"Exercice {ctx.exercice} · {total} membres", carte_conformite()))
        if d["criteres"]:
            S.append(carte("Conformité par critère", "Part des membres soumis au critère qui le remplissent", carte_criteres()))
        if len(d["par_categorie"]) > 1:
            S.append(carte("Conclusions par catégorie", "Répartition en pourcentage ; le nombre de membres à droite", carte_categories()))
        if d["profil"]:
            S.append(carte("Profil des membres", "Qui compose la base de l'exercice", carte_profil()))
    else:
        S.append(Paragraph("Aucun membre dans ce périmètre.", corps))

    # Ensuite, la liste.
    tailles = {"N°": 7, "N° d'ordre": 20, "Actif": 10, "Ancienneté": 16, "Cotisation": 15, "Assurance valide": 15, "H.Formation": 17, "Chiffre d'affaires": 14, "Conclusion": 21, "NHV": 9, "NIF": 18}
    for section in d["sections"]:
        S.append(PageBreak())
        S.append(Paragraph(escape(section["titre"]), h1))
        S.append(Paragraph(f"{section['total']} membres", petit))
        masque = {"N° téléphone", "E-mail", "Sexe", "Raison sociale", "Associé gérant", "Cabinet d'attache", "Employeur"} | ({"NIF"} if section["categorie"] != "EC Indépendant" else set())
        gardees = [
            i for i, entete_ in enumerate(section["entetes"])
            if entete_ not in masque and not (entete_ == "Cotisation" and not any(ligne[i] for ligne in section["lignes"]))
        ]
        occupe = sum(tailles.get(section["entetes"][i], 0) for i in gardees)
        tailles_pdf = [tailles.get(section["entetes"][i], 180 - occupe) for i in gardees]
        lignes_liste = [["" if ligne[i] is None else (heures_txt(ligne[i]) if isinstance(ligne[i], float) else ligne[i]) for i in gardees] for ligne in section["lignes"]]
        S.append(liste([section["entetes"][i] for i in gardees], lignes_liste, tailles_pdf))

    doc.build(S, onFirstPage=premiere_page, onLaterPages=page_suivante)
    return tampon.getvalue()
