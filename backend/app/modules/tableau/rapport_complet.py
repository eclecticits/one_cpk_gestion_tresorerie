"""Rapport complet du Tableau : synthèse, conformité, qualité et plan d'action (PDF et Excel).

Tout vient des dossiers analysés et des réglages de l'exercice : aucun chiffre, seuil ni
date n'est écrit en dur. La conclusion retenue est celle de l'analyse, décisions de la
commission comprises. Le module ne fait que lire : rien n'est écrit en base.
"""
from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import mean, median
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
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

CRITERES = [
    ("cotisation", "Cotisation"),
    ("formation", "Formation (NHV)"),
    ("assurance", "Assurance"),
    ("chiffre_affaires", "Chiffre d'affaires"),
    ("nif", "NIF (EC indépendants)"),
]
# Ces anomalies sont des défauts de conformité, déjà comptés par critère : le registre de
# qualité ne garde que ce qui met en cause la donnée elle-même.
TYPES_CONFORMITE = {
    "cotisation_non_payee",
    "heures_forco_insuffisantes",
    "assurance_manquante",
    "chiffre_affaires_non_declare",
}
LIBELLES_ANOMALIE = {
    "doublon": "Doublon de nom",
    "dossier_incomplet": "Dossier incomplet",
    "categorie_inconnue": "Catégorie non reconnue",
    "cotisation_non_renseignee": "Cotisation non renseignée",
    "heures_forco_manquantes": "Heures de formation non renseignées",
    "assurance_non_renseignee": "Assurance non renseignée",
    "chiffre_affaires_non_renseigne": "Chiffre d'affaires non renseigné",
}
GRAVITES = {"high": "Élevée", "medium": "Moyenne", "low": "Faible"}
ORDRE_GRAVITE = {"Élevée": 0, "Moyenne": 1, "Faible": 2, "Information": 3}

A_COMPLETER = "À compléter"
TYPE_NIF_MANQUANT = "EC indépendant sans NIF"
TYPE_RANG_REPETE = "Même rang de N° d'ordre sous plusieurs années"
# « - » ou « N/A » dans la colonne NIF disent justement qu'il n'y en a pas.
NIF_ABSENTS = {"", "-", "--", "N/A", "NA", "NEANT", "NÉANT", "AUCUN"}
# Forme de la grande majorité des NIF importés : une lettre, sept chiffres, une lettre.
NIF_FORME_USUELLE = re.compile(r"[A-Z]\d{7}[A-Z]")
NUMERO_PROVISOIRE = re.compile(r"/\d{2}\.0+$")
RANG_NUMERO = re.compile(r"^([A-Za-z]+)/\d{2}\.(\d+)$")
MOTIF_A_COMPLETER = "Conclusion non établie : la cotisation ne figure pas dans les fichiers importés."
NOTE_NHV_FICHIER = (
    "Pour les membres sans dossier, le NHV est la colonne « % 120 FOR » du fichier des personnes physiques, "
    "telle qu'importée et comparée au minimum réglé, comme dans la Base Tableau."
)
# Un même code couleur dans tout le rapport : une couleur a toujours le même sens.
VERT_PALE, GRIS_NEUTRE = "A9D3C2", "C4CCD3"
ETATS = {
    "conforme": ("Conforme / inscrit", "3E9C76"),
    "exempte": ("Exempté", VERT_PALE),
    "defaut": ("En défaut / non inscrit", "C94C4C"),
    "deliberer": ("À délibérer", "D8A31A"),
    "inconnu": ("Non renseigné / à compléter", GRIS_NEUTRE),
}
AVERTISSEMENT_NHV = (
    "Aucun NHV n'a été lu dans ce périmètre : l'import ne reconnaît que les colonnes intitulées NHV. "
    "La formation est donc évaluée sur le libellé OUI/NON du fichier, sans statistique d'heures."
)

VERT, VERT_FONCE, MARINE, OR, ROUGE ="3E9C76", "286A54", "16324F", "D8A31A", "C94C4C"
VERT_CLAIR, BLEU_CLAIR, OR_CLAIR, ROUGE_CLAIR, GRIS_CLAIR, GRIS_MOYEN, GRIS_TEXTE = (
    "E8F3EE", "EAF1F8", "FBF3DC", "FBE9E9", "F3F5F7", "D9E0E6", "44515C",
)


@dataclass
class ContexteRapport:
    exercice: str
    date_situation: date | None
    scope: str
    source: str
    organisation: str
    reglages: verdict_engine.TableauReglages
    exercice_annee: int | None
    genere_le: date
    contact: str = ""
    logo: bytes | None = None
    comparaison_nom: str | None = None
    comparaison: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Numéros portés par plusieurs lignes d'un même fichier : la Base n'en garde qu'une.
    repetitions: list[dict[str, Any]] = field(default_factory=list)
    fiches_essai_ecartees: int = 0
    numeros_ecartes: dict[str, str] = field(default_factory=dict)


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


def pct(valeur: float | None) -> str:
    return "—" if valeur is None else f"{nombre(valeur * 100)} %"


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


def criteres_rapport(categorie: Any) -> list[str]:
    """Critères du moteur de verdict, plus le NIF exigé des EC indépendants."""
    criteres = list(verdict_engine.CATEGORIE_CRITERES.get(categorie or "", []))
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


def _bloc(titre: str, lignes: list[tuple[str, int]], total: int) -> dict[str, Any]:
    return {
        "titre": titre,
        "lignes": [(libelle, n, n / total if total else 0.0) for libelle, n in lignes if n],
        "total": total,
    }


def _section(categorie: str, titre: str, feuille: str, groupe: list[dict[str, Any]], ctx: ContexteRapport) -> dict[str, Any]:
    """Liste et blocs de statistiques d'une section, selon les seuls critères qui la concernent."""
    groupe = sorted(groupe, key=lambda d: nom_complet(d).casefold())
    total = len(groupe)
    criteres = criteres_rapport(categorie)

    def etats(critere: str) -> Counter:
        return Counter(_etat_critere(d, critere, ctx) for d in groupe)

    def libelle_anciennete(dossier: dict[str, Any]) -> str:
        return verdict_engine.libelle_anciennete(dossier.get("numero_ordre"), ctx.exercice_annee) or _txt(dossier.get("anciennete")) or "Non renseignée"

    anciennete = Counter(libelle_anciennete(d) for d in groupe)
    blocs = [_bloc("Ancienneté", anciennete.most_common(), total)]
    cotisation = etats("cotisation")
    blocs.append(_bloc("Régularisation de la Cotisation", [
        ("Cotisations Régularisées (OUI)", cotisation["conforme"]),
        ("Cotisations Non Régularisées (NON)", cotisation["defaut"]),
        ("Cotisations non renseignées", cotisation["inconnu"]),
    ], total))
    if "formation" in criteres:
        formation = etats("formation")
        blocs.append(_bloc("Heures Formations", [
            ("Le seuil atteint (OUI)", formation["conforme"]),
            ("Le seuil non applicable (NA)", formation["exempte"]),
            ("Le seuil Non atteint (NON)", formation["defaut"]),
            ("Heures non renseignées", formation["inconnu"]),
        ], total))
    if "assurance" in criteres:
        assurance = etats("assurance")
        blocs.append(_bloc("Déclaration d'assurance", [
            ("En règle avec l'assurance (OUI)", assurance["conforme"]),
            ("NON En règle avec l'assurance (NON)", assurance["defaut"]),
            ("Assurance non renseignée", assurance["inconnu"]),
        ], total))
    if "chiffre_affaires" in criteres:
        chiffre = etats("chiffre_affaires")
        blocs.append(_bloc("Déclaration de Chiffre d'affaire", [
            ("En règle avec le Chiffre d'affaire", chiffre["conforme"]),
            ("NON en règle avec le Chiffre d'affaire", chiffre["defaut"]),
            ("Chiffre d'affaire non renseigné", chiffre["inconnu"]),
        ], total))
    if "nif" in criteres:
        nif = etats("nif")
        blocs.append(_bloc("NIF", [("NIF renseigné", nif["conforme"]), ("NIF manquant", nif["defaut"])], total))
    conclusions = Counter(classe_conclusion(d.get("conclusion")) for d in groupe)
    blocs.append(_bloc("Conclusion", [
        ("Les Inscrits (INSCRIT)", conclusions.pop(verdict_engine.INSCRIT, 0)),
        ("Non Inscrits (NON INSCRIT)", conclusions.pop(verdict_engine.NON_INSCRIT, 0)),
        ("À délibérer", conclusions.pop(verdict_engine.A_DELIBERER, 0)),
        ("À compléter", conclusions.pop(A_COMPLETER, 0)),
        *conclusions.most_common(),
    ], total))

    classes = Counter(classe_conclusion(d.get("conclusion")) for d in groupe)
    connues = classes[verdict_engine.INSCRIT] + classes[verdict_engine.NON_INSCRIT] + classes[verdict_engine.A_DELIBERER]
    situation = [{
        "libelle": "Conclusion",
        "total": total,
        "etats": {
            "conforme": classes[verdict_engine.INSCRIT],
            "exempte": 0,
            "defaut": classes[verdict_engine.NON_INSCRIT],
            "deliberer": classes[verdict_engine.A_DELIBERER],
            "inconnu": total - connues,
        },
    }]
    for critere, libelle in CRITERES:
        if critere in criteres:
            compte = etats(critere)
            situation.append({
                "libelle": "NIF" if critere == "nif" else libelle,
                "total": total,
                "etats": {"conforme": compte["conforme"], "exempte": compte["exempte"], "defaut": compte["defaut"], "deliberer": 0, "inconnu": compte["inconnu"]},
            })
    defauts = [(ligne["etats"]["defaut"], ligne["libelle"]) for ligne in situation[1:] if ligne["etats"]["defaut"]]
    if defauts:
        volume, critere_principal = max(defauts)
        constat = f"Principal défaut : {critere_principal}, {volume} sur {total}."
    else:
        constat = "Aucun défaut relevé sur les critères renseignés."
    prefixe = titre.split(" : ")[0].replace("SECTION", "Section") if " : " in titre else ""

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
    colonnes += [("Ancienneté", libelle_anciennete, False), ("Cotisation", lambda d: _oui_non(d.get("cotisation_payee")), False)]
    if "assurance" in criteres:
        colonnes.append(("Assurance valide", lambda d: _oui_non(d.get("assurance")), False))
    if "formation" in criteres:
        colonnes.append(("H.Formation", formation_txt, False))
    if "chiffre_affaires" in criteres:
        colonnes.append(("Chiffre d'affaires", lambda d: _oui_non(d.get("chiffre_affaires")), False))
    colonnes.append(("Conclusion", lambda d: classe_conclusion(d.get("conclusion")), False))
    if "formation" in criteres:
        colonnes.append(("NHV", lambda d: d.get("heures_forco"), False))
    # Une colonne facultative vide n'apporte rien : les fichiers ne la renseignent pas tous.
    colonnes = [(libelle, lire, False) for libelle, lire, facultative in colonnes if not facultative or any(lire(d) for d in groupe)]
    entetes = ["N°"] + [libelle for libelle, _, _ in colonnes]
    lignes = [[index] + [lire(d) for _, lire, _ in colonnes] for index, d in enumerate(groupe, 1)]
    return {
        "categorie": categorie, "titre": titre, "feuille": feuille, "total": total, "blocs": blocs, "entetes": entetes, "lignes": lignes,
        "situation": situation, "constat": constat, "court": f"{prefixe} · {categorie}" if prefixe else categorie,
    }


def _anomalie(gravite: str, type_: str, dossier: dict[str, Any] | None, observation: str, action: str) -> dict[str, Any]:
    dossier = dossier or {}
    return {
        "gravite": gravite,
        "type": type_,
        "categorie": norm_categorie(dossier.get("categorie")) if dossier else "",
        "numero_ordre": _txt(dossier.get("numero_ordre")),
        "nom": nom_complet(dossier),
        "observation": observation,
        "action": action,
    }


def _registre_qualite(
    membres: list[dict[str, Any]], anomalies: Iterable[dict[str, Any]], ctx: ContexteRapport
) -> list[dict[str, Any]]:
    registre: list[dict[str, Any]] = []
    par_id = {d.get("id"): d for d in membres}
    seuil = ctx.reglages.heures_formation_min

    for anomalie in anomalies:
        type_ = anomalie.get("type_anomalie")
        dossier = par_id.get(anomalie.get("dossier_id"))
        if type_ in TYPES_CONFORMITE or dossier is None:
            continue
        registre.append(_anomalie(
            GRAVITES.get(anomalie.get("gravite"), "Moyenne"),
            LIBELLES_ANOMALIE.get(type_, _txt(type_).replace("_", " ").capitalize()),
            dossier,
            _txt(anomalie.get("description")),
            "Compléter ou corriger le dossier, puis relancer l'analyse.",
        ))

    numeros: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dossier in membres:
        for message in dict.fromkeys((dossier.get("raw_data") or {}).get("signalements") or []):
            registre.append(_anomalie("Moyenne", "Signalement à l'import", dossier, message, "Vérifier la ligne dans le fichier source."))
        numero = _maj(dossier.get("numero_ordre"))
        if numero:
            numeros[numero].append(dossier)
        else:
            registre.append(_anomalie(
                "Élevée", "Numéro d'ordre manquant", dossier,
                f"Conclusion : {_txt(dossier.get('conclusion')) or 'aucune'}.",
                "Attribuer le numéro d'ordre avant publication.",
            ))

        annee = verdict_engine.annee_ordre(dossier.get("numero_ordre"))
        libelle = _txt(dossier.get("anciennete")).lower()
        if annee is not None and ctx.exercice_annee is not None:
            if annee > ctx.exercice_annee:
                registre.append(_anomalie(
                    "Moyenne", "Numéro d'ordre postérieur à l'exercice", dossier,
                    f"Numéro de {annee} pour l'exercice {ctx.exercice_annee}.",
                    "Vérifier s'il s'agit d'un numéro provisoire.",
                ))
            debut_exemption = ctx.exercice_annee - (ctx.reglages.nouveau_anciennete_ans - 1)
            if "nouve" in libelle and annee < debut_exemption:
                registre.append(_anomalie(
                    "Moyenne", "Ancienneté incohérente avec le numéro d'ordre", dossier,
                    f"Libellé « {_txt(dossier.get('anciennete'))} » pour un numéro de {annee} : le libellé l'exempte de formation.",
                    "Confirmer l'ancienneté ou le numéro d'ordre.",
                ))

        heures = dossier.get("heures_forco")
        hformation = (dossier.get("raw_data") or {}).get("hformation")
        if heures is not None and _etat_critere(dossier, "formation", ctx) != "exempte":
            if hformation is True and heures < seuil:
                registre.append(_anomalie(
                    "Moyenne", "Formation OUI sous le seuil", dossier,
                    f"Libellé OUI avec {heures_txt(heures)} h de NHV (minimum {heures_txt(seuil)} h).",
                    "Corriger le libellé ou documenter la dérogation.",
                ))
            elif hformation is False and heures >= seuil:
                registre.append(_anomalie(
                    "Moyenne", "Formation NON au-dessus du seuil", dossier,
                    f"Libellé NON avec {heures_txt(heures)} h de NHV (minimum {heures_txt(seuil)} h).",
                    "Corriger le libellé.",
                ))

        if dossier.get("categorie") == "EC Indépendant" and not nif_renseigne(dossier):
            registre.append(_anomalie(
                "Élevée", TYPE_NIF_MANQUANT, dossier,
                "Un EC indépendant doit avoir un NIF.", "Obtenir le NIF et le reporter dans le fichier des membres.",
            ))
        elif dossier.get("categorie") == "EC Indépendant" and not NIF_FORME_USUELLE.fullmatch(re.sub(r"\s", "", _maj(dossier.get("nif")))):
            registre.append(_anomalie(
                "Moyenne", "NIF de forme inhabituelle", dossier,
                f"Valeur importée : {_txt(dossier.get('nif'))}.", "Vérifier le NIF auprès du membre.",
            ))

        if NUMERO_PROVISOIRE.search(_txt(dossier.get("numero_ordre"))):
            registre.append(_anomalie(
                "Moyenne", "Numéro d'ordre provisoire", dossier,
                f"Numéro {_txt(dossier.get('numero_ordre'))} : son rang vaut zéro.", "Confirmer le numéro d'ordre définitif.",
            ))

        email = _txt(dossier.get("email"))
        if email and not EMAIL_RE.fullmatch(email):
            registre.append(_anomalie(
                "Faible", "E-mail invalide", dossier, f"Valeur : {email}.", "Corriger l'adresse.",
            ))

    for numero, groupe in sorted(numeros.items()):
        if len(groupe) > 1:
            registre.append(_anomalie(
                "Élevée", "Numéro d'ordre en double", groupe[0],
                f"Numéro porté par {len(groupe)} dossiers : {'; '.join(nom_complet(d) for d in groupe)}.",
                "Rétablir un numéro unique par dossier.",
            ))

    # Le N° d'ordre est unique : ni répété à l'identique, ni le même rang sous une autre année.
    for repetition in ctx.repetitions:
        registre.append(_anomalie(
            "Élevée", "Numéro d'ordre en double", None,
            f"{repetition['numero_ordre']} porté par {repetition['lignes']} lignes : {repetition['noms']}.",
            "Garder un seul numéro par membre dans le fichier source.",
        ))
    rangs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for dossier in membres:
        trouve = RANG_NUMERO.match(_txt(dossier.get("numero_ordre")))
        if trouve and int(trouve.group(2)):
            rangs[(trouve.group(1).upper(), trouve.group(2))].append(dossier)
    for groupe in rangs.values():
        if len({_maj(d.get("numero_ordre")) for d in groupe}) > 1:
            registre.append(_anomalie(
                "Élevée", TYPE_RANG_REPETE, groupe[0],
                "; ".join(f"{_txt(d.get('numero_ordre'))} : {nom_complet(d)}" for d in groupe) + ".",
                "Vérifier lequel des numéros est le bon.",
            ))

    # L'analyse repère les doublons de nom des dossiers ; les membres sans dossier n'y passent pas.
    homonymes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dossier in membres:
        if not _txt(dossier.get("conclusion")) and nom_complet(dossier):
            homonymes[nom_complet(dossier).casefold()].append(dossier)
    for groupe in homonymes.values():
        if len(groupe) > 1:
            registre.append(_anomalie(
                "Élevée", "Même nom sous plusieurs numéros d'ordre", groupe[0],
                f"Numéros : {'; '.join(_txt(d.get('numero_ordre')) or 'aucun' for d in groupe)}.",
                "Vérifier s'il s'agit de la même personne, puis garder un seul numéro.",
            ))

    def cle_tel(dossier: dict[str, Any]) -> str:
        return re.sub(r"\D", "", _txt(dossier.get("telephone")))

    for libelle, cle in (("E-mail", lambda d: _maj(d.get("email"))), ("Téléphone", cle_tel)):
        groupes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for dossier in membres:
            valeur = cle(dossier)
            if valeur:
                groupes[valeur].append(dossier)
        for valeur, groupe in sorted(groupes.items()):
            if len(groupe) < 2:
                continue
            meme_categorie = len({norm_categorie(d.get("categorie")) for d in groupe}) == 1
            registre.append(_anomalie(
                "Moyenne" if meme_categorie else "Information",
                f"{libelle} partagé dans une même catégorie" if meme_categorie else f"{libelle} partagé entre catégories",
                groupe[0],
                f"{valeur} : {'; '.join(nom_complet(d) for d in groupe)}.",
                "Vérifier à qui appartient cette coordonnée." if meme_categorie else "Ne pas utiliser cette coordonnée comme identifiant.",
            ))

    registre.sort(key=lambda item: (ORDRE_GRAVITE.get(item["gravite"], 9), item["type"], item["numero_ordre"]))
    return registre


def _ecarts(membres: list[dict[str, Any]], ctx: ContexteRapport, norm_numero) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Écarts avec la conclusion du fichier importé, puis avec l'import de comparaison."""
    fichier: list[dict[str, Any]] = []
    comparaison: list[dict[str, Any]] = []
    avec_conclusion_source = 0
    for dossier in membres:
        conclusion = classe_conclusion(dossier.get("conclusion"))
        base = {
            "categorie": norm_categorie(dossier.get("categorie")),
            "numero_ordre": _txt(dossier.get("numero_ordre")),
            "nom": nom_complet(dossier),
            "conclusion": conclusion,
            "motif": _txt(dossier.get("conclusion_motif")),
            "nhv": dossier.get("heures_forco"),
        }
        source = (dossier.get("raw_data") or {}).get("conclusion_source")
        if _txt(source):
            avec_conclusion_source += 1
            if classe_conclusion(source) != conclusion:
                fichier.append({**base, "autre": _txt(source)})
        if ctx.comparaison:
            autre = ctx.comparaison.get(norm_numero(dossier.get("numero_ordre")) or "")
            if autre and classe_conclusion(autre.get("conclusion")) != conclusion:
                comparaison.append({**base, "autre": _txt(autre.get("conclusion")), "nhv_autre": autre.get("heures_forco")})
    return fichier, comparaison, avec_conclusion_source


def construire_donnees(
    dossiers: list[dict[str, Any]], anomalies: Iterable[dict[str, Any]], ctx: ContexteRapport, norm_numero
) -> dict[str, Any]:
    stagiaires = [d for d in dossiers if d.get("categorie") == "Stagiaire"]
    membres = [d for d in dossiers if d.get("categorie") != "Stagiaire"]
    categories = ORDRE_CATEGORIES + sorted({norm_categorie(d.get("categorie")) for d in membres} - set(ORDRE_CATEGORIES))

    lignes_categories = []
    for categorie in categories:
        groupe = [d for d in membres if norm_categorie(d.get("categorie")) == categorie]
        if not groupe:
            continue
        classes = Counter(classe_conclusion(d.get("conclusion")) for d in groupe)
        inscrits = classes[verdict_engine.INSCRIT]
        non_inscrits = classes[verdict_engine.NON_INSCRIT]
        a_deliberer = classes[verdict_engine.A_DELIBERER]
        a_completer = classes[A_COMPLETER]
        evalues = len(groupe) - a_completer
        lignes_categories.append({
            "categorie": categorie,
            "total": len(groupe),
            "inscrits": inscrits,
            "non_inscrits": non_inscrits,
            "a_deliberer": a_deliberer,
            "a_completer": a_completer,
            "autres": len(groupe) - inscrits - non_inscrits - a_deliberer - a_completer,
            "taux": inscrits / evalues if evalues else None,
        })
    total = len(membres)
    inscrits = sum(l["inscrits"] for l in lignes_categories)
    non_inscrits = sum(l["non_inscrits"] for l in lignes_categories)
    a_deliberer = sum(l["a_deliberer"] for l in lignes_categories)
    a_completer = sum(l["a_completer"] for l in lignes_categories)
    avec_conclusion = total - a_completer

    lignes_criteres = []
    for critere, libelle in CRITERES:
        etats = Counter(
            _etat_critere(d, critere, ctx)
            for d in membres
            if critere in criteres_rapport(d.get("categorie"))
        )
        evalues = etats["conforme"] + etats["defaut"]
        if sum(etats.values()):
            lignes_criteres.append({
                "critere": critere,
                "libelle": libelle,
                "perimetre": sum(etats.values()),
                "conformes": etats["conforme"],
                "defauts": etats["defaut"],
                "exemptes": etats["exempte"],
                "inconnus": etats["inconnu"],
                "taux": etats["conforme"] / evalues if evalues else None,
            })

    soumis = [
        d for d in membres
        if "formation" in verdict_engine.CATEGORIE_CRITERES.get(d.get("categorie") or "", [])
    ]
    exemptes = [d for d in soumis if _etat_critere(d, "formation", ctx) == "exempte"]
    ids_exemptes = {id(d) for d in exemptes}
    heures = [float(d["heures_forco"]) for d in soumis if id(d) not in ids_exemptes and d.get("heures_forco") is not None]

    restants = Counter()
    for dossier in membres:
        if classe_conclusion(dossier.get("conclusion")) != verdict_engine.INSCRIT:
            for critere, _ in CRITERES:
                if critere in criteres_rapport(dossier.get("categorie")) and _etat_critere(dossier, critere, ctx) == "defaut":
                    restants[critere] += 1

    registre = _registre_qualite(membres, anomalies, ctx)
    ecarts_fichier, ecarts_comparaison, avec_conclusion_source = _ecarts(membres, ctx, norm_numero)
    decisions = sum(bool((d.get("raw_data") or {}).get("decision_appliquee")) for d in membres)
    sexes = Counter(_maj(d.get("sexe"))[:1] for d in membres if norm_categorie(d.get("categorie")) != "Société")
    sexes_inscrits = Counter(
        _maj(d.get("sexe"))[:1] for d in membres
        if norm_categorie(d.get("categorie")) != "Société" and classe_conclusion(d.get("conclusion")) == verdict_engine.INSCRIT
    )

    def profil(valeurs: Iterable[Any]) -> list[list[Any]]:
        comptes = Counter(_txt(v) for v in valeurs if _txt(v))
        return [[libelle, nombre_] for libelle, nombre_ in comptes.most_common()]

    def anciennete(dossier: dict[str, Any]) -> Any:
        return verdict_engine.libelle_anciennete(dossier.get("numero_ordre"), ctx.exercice_annee) or dossier.get("anciennete")

    donnees = {
        "ctx": ctx,
        "a_completer": a_completer,
        "sections": [
            _section(categorie, titre, feuille, [d for d in membres if norm_categorie(d.get("categorie")) == categorie], ctx)
            for categorie, titre, feuille in [*SECTIONS, *((c, c.upper(), c.upper()[:31]) for c in categories if c not in ORDRE_CATEGORIES)]
            if any(norm_categorie(d.get("categorie")) == categorie for d in membres)
        ],
        "profil": {
            "anciennete": profil(anciennete(d) for d in membres),
            "actif": profil({True: "Actif", False: "Inactif"}.get(d.get("actif")) for d in membres),
            "province": profil(d.get("province") for d in membres),
            "cabinets": profil(d.get("cabinet") for d in membres)[:10],
        },
        "cotisations_inconnues": next((c["inconnus"] for c in lignes_criteres if c["critere"] == "cotisation"), 0),
        "membres": membres,
        "stagiaires": stagiaires,
        "categories": lignes_categories,
        "criteres": lignes_criteres,
        "total": total,
        "inscrits": inscrits,
        "non_inscrits": non_inscrits,
        "a_deliberer": a_deliberer,
        "taux": inscrits / avec_conclusion if avec_conclusion else None,
        "restants": restants,
        "registre": registre,
        "types_registre": Counter((item["gravite"], item["type"]) for item in registre),
        "ecarts_fichier": ecarts_fichier,
        "ecarts_comparaison": ecarts_comparaison,
        "avec_conclusion_source": avec_conclusion_source,
        "decisions": decisions,
        "sexes": sexes,
        "sexes_inscrits": sexes_inscrits,
        "nhv": {
            "soumis": len(soumis) - len(exemptes),
            "exemptes": len(exemptes),
            "renseignes": len(heures),
            "total": sum(heures),
            "moyenne": mean(heures) if heures else 0.0,
            "mediane": median(heures) if heures else 0.0,
            "zero": sum(h == 0 for h in heures),
            "sous_seuil": sum(h < ctx.reglages.heures_formation_min for h in heures),
        },
    }
    donnees["plan"] = _plan_action(donnees)
    donnees["constats"], donnees["decisions_attendues"] = _synthese(donnees)
    donnees["titre_situation"] = _titre_situation(donnees)
    return donnees


def _titre_situation(d: dict[str, Any]) -> str:
    """Le titre du graphique dit le constat, et il est calculé : il suit les données."""
    defauts = [(c["defauts"], c["libelle"]) for c in d["criteres"] if c["defauts"]]
    if defauts:
        volume, libelle = max(defauts)
        return f"Le critère le plus souvent en défaut : {libelle}, {volume} dossier{'s' if volume > 1 else ''}"
    return "Aucun défaut relevé sur les critères renseignés"


def _synthese(d: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Constats et décisions de la page du Bureau : uniquement ce que les données établissent."""
    criteres = {c["critere"]: c for c in d["criteres"]}
    ctx: ContexteRapport = d["ctx"]
    constats: list[str] = []
    if d["a_completer"]:
        constats.append(f"Sans conclusion : {d['a_completer']} membres sur {d['total']}, car la cotisation ne figure pas dans les fichiers importés.")
    if d["taux"] is not None:
        constats.append(f"Taux d'inscription des dossiers ayant une conclusion : {pct(d['taux'])} ({d['inscrits']} inscrits, {d['non_inscrits']} non inscrits, {d['a_deliberer']} à délibérer).")
    formation = criteres.get("formation")
    if formation and formation["defauts"] + formation["inconnus"]:
        constats.append(f"Formation : {formation['defauts']} sous le minimum réglé et {formation['inconnus']} sans NHV, sur {formation['perimetre']} personnes physiques.")
    assurance = criteres.get("assurance")
    if assurance and assurance["defauts"] + assurance["inconnus"]:
        constats.append(f"Assurance : {assurance['defauts']} en défaut et {assurance['inconnus']} non renseignées, sur {assurance['perimetre']} sociétés et EC indépendants.")
    chiffre = criteres.get("chiffre_affaires")
    if chiffre and chiffre["defauts"] + chiffre["inconnus"]:
        constats.append(f"Chiffre d'affaires : {chiffre['defauts']} en défaut et {chiffre['inconnus']} non renseignés, sur {chiffre['perimetre']} sociétés et EC indépendants.")
    nif = criteres.get("nif")
    if nif and nif["defauts"]:
        constats.append(f"NIF manquant : {nif['defauts']} EC indépendants sur {nif['perimetre']}.")
    cotisation = criteres.get("cotisation")
    if cotisation and cotisation["defauts"]:
        constats.append(f"Cotisation non régularisée : {cotisation['defauts']} sur {cotisation['perimetre']}.")

    a_verifier = sum(n for (_, type_), n in d["types_registre"].items() if type_ in {TYPE_RANG_REPETE, "Numéro d'ordre en double"})
    if a_verifier:
        constats.append(f"N° d'ordre non uniques à vérifier : {a_verifier}.")

    decisions: list[str] = []
    if a_verifier:
        decisions.append(f"Arbitrer les N° d'ordre non uniques : {a_verifier}.")
    if d["cotisations_inconnues"]:
        decisions.append("Désigner la source officielle de la cotisation : aucune conclusion n'est possible sans elle.")
    if d["a_deliberer"]:
        decisions.append(f"Trancher les dossiers à délibérer : {d['a_deliberer']}.")
    if d["ecarts_fichier"] or d["ecarts_comparaison"]:
        decisions.append(f"Valider les écarts de conclusion : {len(d['ecarts_fichier']) + len(d['ecarts_comparaison'])}.")
    if nif and nif["defauts"]:
        decisions.append("Arrêter le traitement des EC indépendants sans NIF.")
    if d["a_completer"] and d["nhv"]["renseignes"]:
        decisions.append(f"Confirmer la lecture de la colonne « % 120 FOR » face au minimum réglé de {heures_txt(ctx.reglages.heures_formation_min)}.")
    return constats, decisions


def _plan_action(d: dict[str, Any]) -> list[list[str]]:
    plan: list[list[str]] = []
    restants = d["restants"]
    # Le NIF a sa propre ligne au plan : ne pas le compter deux fois.
    bloquants = sum(n for (gravite, type_), n in d["types_registre"].items() if gravite == "Élevée" and type_ != TYPE_NIF_MANQUANT)
    nif_manquants = d["types_registre"].get(("Élevée", TYPE_NIF_MANQUANT), 0)
    a_verifier = sum(n for (gravite, _), n in d["types_registre"].items() if gravite == "Moyenne")

    def ajouter(priorite: str, horizon: str, action: str, pilote: str, indicateur: str, volume: int) -> None:
        if volume:
            plan.append([priorite, horizon, action, pilote, indicateur, str(volume)])

    ajouter("P1", "0–30 jours", "Renseigner la cotisation : sans elle, aucune conclusion n'est possible", "Trésorerie et Commission", "Cotisations à renseigner", d["cotisations_inconnues"])
    ajouter("P1", "0–30 jours", "Obtenir le NIF des EC indépendants qui n'en ont pas", "Commission Tableau", "NIF manquants", nif_manquants)
    ajouter("P1", "0–15 jours", "Trancher les dossiers à délibérer", "Commission Tableau", "Dossiers tranchés", d["a_deliberer"])
    ajouter("P1", "0–15 jours", "Documenter les écarts avec le fichier importé", "Commission Tableau", "Écarts documentés", len(d["ecarts_fichier"]))
    ajouter("P1", "0–15 jours", "Documenter les écarts avec l'import de comparaison", "Commission Tableau", "Écarts documentés", len(d["ecarts_comparaison"]))
    ajouter("P1", "0–30 jours", "Corriger les anomalies graves du registre de qualité", "Référent données", "Anomalies ouvertes", bloquants)
    ajouter("P2", "0–30 jours", "Vérifier les anomalies moyennes du registre de qualité", "Référent données", "Anomalies ouvertes", a_verifier)
    ajouter("P2", "30–60 jours", "Rattraper la formation des dossiers en défaut", "FORCO et Commission", "Formation en défaut", restants["formation"])
    ajouter("P2", "30–60 jours", "Régulariser les cotisations en défaut", "Trésorerie et Commission", "Cotisation en défaut", restants["cotisation"])
    ajouter("P2", "30–90 jours", "Obtenir les preuves d'assurance", "Commission Tableau", "Assurance en défaut", restants["assurance"])
    ajouter("P2", "30–90 jours", "Obtenir les déclarations de chiffre d'affaires", "Commission Tableau", "Chiffre d'affaires en défaut", restants["chiffre_affaires"])
    return plan


# ── Excel ────────────────────────────────────────────────────────────────────


def build_excel(d: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    ctx: ContexteRapport = d["ctx"]
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = f"Rapport complet du Tableau {ctx.exercice}"
    wb.properties.creator = ctx.organisation
    ligne_fine = Border(bottom=Side(style="hair", color=GRIS_MOYEN))
    tables = {"n": 0}

    def sure(valeur: Any) -> Any:
        # Une valeur importée commençant par « = » resterait sinon une formule exécutable.
        if isinstance(valeur, str) and valeur.startswith("="):
            return "'" + valeur
        return valeur

    def titre(ws, texte: str, sous_titre: str) -> None:
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

    def section(ws, ligne: int, texte: str, colonnes: int) -> None:
        ws.merge_cells(start_row=ligne, start_column=1, end_row=ligne, end_column=colonnes)
        cellule = ws.cell(ligne, 1, texte)
        cellule.fill = PatternFill("solid", fgColor=MARINE)
        cellule.font = Font(bold=True, color="FFFFFF")

    def matrice(ws, ligne: int, entetes: list[str], lignes: list[list[Any]], tableau: bool = False) -> int:
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
        fin = ligne + len(lignes)
        if tableau and lignes:
            # Le tableau porte ses filtres : ne pas ajouter de filtre de feuille sur la même plage.
            tables["n"] += 1
            t = Table(displayName=f"Rapport{tables['n']}", ref=f"A{ligne}:{get_column_letter(len(entetes))}{fin}")
            t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True)
            ws.add_table(t)
            ws.freeze_panes = ws.cell(ligne + 1, 1)
        return fin

    def largeurs(ws, valeurs: list[int]) -> None:
        for index, largeur in enumerate(valeurs, 1):
            ws.column_dimensions[get_column_letter(index)].width = largeur

    def lignes_situation(sections: list[dict[str, Any]], avec_section: bool) -> list[list[Any]]:
        return [
            [f"{section['court']} : {ligne['libelle']}" if avec_section else ligne["libelle"], *(ligne["etats"][cle] for cle in ETATS)]
            for section in sections
            for ligne in section["situation"]
        ]

    def graphique_situation(ws, ligne_entete: int, nombre_lignes: int, titre_graphique: str, ancre: str, hauteur_cm: float) -> None:
        """Barres empilées à 100 % : conforme, exempté, défaut, à délibérer, non renseigné."""
        graphique = BarChart()
        graphique.type = "bar"
        graphique.grouping = "percentStacked"
        graphique.overlap = 100
        graphique.title = titre_graphique
        graphique.height, graphique.width = hauteur_cm, 22
        graphique.x_axis.delete = graphique.y_axis.delete = False
        graphique.x_axis.scaling.orientation = "maxMin"
        graphique.y_axis.numFmt = "0%"
        graphique.y_axis.majorGridlines = None
        graphique.legend.position = "b"
        graphique.add_data(Reference(ws, min_col=2, max_col=1 + len(ETATS), min_row=ligne_entete, max_row=ligne_entete + nombre_lignes), titles_from_data=True)
        graphique.set_categories(Reference(ws, min_col=1, min_row=ligne_entete + 1, max_row=ligne_entete + nombre_lignes))
        for serie, (_, couleur) in zip(graphique.series, ETATS.values()):
            serie.graphicalProperties.solidFill = couleur
            serie.graphicalProperties.line.solidFill = "FFFFFF"
        graphique.dataLabels = DataLabelList()
        graphique.dataLabels.showVal = True
        graphique.dataLabels.numFmt = "0;;;"  # Masque les zéros, qui encombreraient les barres.
        ws.add_chart(graphique, ancre)

    # Synthèse pour le Bureau
    ws = wb.create_sheet("Synthèse Bureau")
    titre(ws, "Synthèse pour le Bureau", f"{ctx.organisation} · Tableau {ctx.exercice} · situation du {fdate(ctx.date_situation)}")
    fin = matrice(ws, 4, ["Constats"], [[c] for c in d["constats"]] or [["Aucun constat particulier."]])
    matrice(ws, fin + 2, ["Décisions attendues"], [[c] for c in d["decisions_attendues"]] or [["Aucune décision en attente."]])
    largeurs(ws, [120])

    # Tableau de bord
    ws = wb.create_sheet("Tableau de bord")
    titre(ws, f"Rapport complet du Tableau {ctx.exercice}", f"{ctx.organisation} · {ctx.source} · situation du {fdate(ctx.date_situation)} · généré le {fdate(ctx.genere_le)}")
    cartes = [("A", "B", "MEMBRES", str(d["total"]), BLEU_CLAIR, MARINE), ("C", "D", "INSCRITS", str(d["inscrits"]), VERT_CLAIR, VERT_FONCE),
              ("E", "F", "NON INSCRITS", str(d["non_inscrits"]), ROUGE_CLAIR, ROUGE), ("G", "H", "À DÉLIBÉRER", str(d["a_deliberer"]), OR_CLAIR, OR),
              ("I", "J", "À COMPLÉTER", str(d["a_completer"]), BLEU_CLAIR, MARINE), ("K", "L", "TAUX D'INSCRIPTION", pct(d["taux"]), OR_CLAIR, OR)]
    for debut, fin, libelle, valeur, fond, couleur in cartes:
        ws.merge_cells(f"{debut}4:{fin}6")
        cellule = ws[f"{debut}4"]
        cellule.value = f"{libelle}\n{valeur}"
        cellule.fill = PatternFill("solid", fgColor=fond)
        cellule.font = Font(size=13, bold=True, color=couleur)
        cellule.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    section(ws, 8, "Résultats par catégorie", 7)
    lignes = [[l["categorie"], l["total"], l["inscrits"], l["non_inscrits"], l["a_deliberer"], l["a_completer"], l["taux"]] for l in d["categories"]]
    fin_categories = matrice(ws, 9, ["Catégorie", "Total", "Inscrits", "Non inscrits", "À délibérer", "À compléter", "Taux"], lignes)
    total = fin_categories + 1
    for colonne, valeur in enumerate(["TOTAL", d["total"], d["inscrits"], d["non_inscrits"], d["a_deliberer"], d["a_completer"], d["taux"]], 1):
        ws.cell(total, colonne, valeur).font = Font(bold=True)
    for ligne in range(10, total + 1):
        ws.cell(ligne, 7).number_format = "0.0%"

    debut_criteres = max(total + 2, 26)
    section(ws, debut_criteres, "Conformité des critères", 7)
    lignes = [[c["libelle"], c["perimetre"], c["conformes"], c["defauts"], c["exemptes"], c["inconnus"], c["taux"]] for c in d["criteres"]]
    fin_criteres = matrice(ws, debut_criteres + 1, ["Critère", "Périmètre", "Conformes", "En défaut", "Exemptés", "Non renseignés", "Taux conforme"], lignes)
    for ligne in range(debut_criteres + 2, fin_criteres + 1):
        ws.cell(ligne, 7).number_format = "0.0%"

    debut_situation = fin_criteres + 2
    section(ws, debut_situation, "Situation par section", 6)
    lignes = lignes_situation(d["sections"], True)
    matrice(ws, debut_situation + 1, ["Section et critère", *(libelle for libelle, _ in ETATS.values())], lignes)
    if lignes:
        graphique_situation(ws, debut_situation + 1, len(lignes), d["titre_situation"], "I8", 15)
    largeurs(ws, [40, 11, 11, 13, 12, 12, 11, 3] + [11] * 8)

    # Rapprochement
    if d["ecarts_fichier"] or d["ecarts_comparaison"]:
        ws = wb.create_sheet("Rapprochement")
        titre(ws, "Rapprochement des conclusions", "Conclusion de l'analyse comparée aux autres conclusions disponibles")
        entetes = ["Origine", "Catégorie", "N° d'ordre", "Nom", "Conclusion de l'analyse", "Autre conclusion", "Motif de l'analyse", "NHV"]
        lignes = [["Fichier importé", e["categorie"], e["numero_ordre"], e["nom"], e["conclusion"], e["autre"], e["motif"], e["nhv"]] for e in d["ecarts_fichier"]]
        lignes += [[ctx.comparaison_nom or "Comparaison", e["categorie"], e["numero_ordre"], e["nom"], e["conclusion"], e["autre"], e["motif"], e["nhv"]] for e in d["ecarts_comparaison"]]
        matrice(ws, 4, entetes, lignes, tableau=True)
        largeurs(ws, [24, 16, 15, 34, 16, 16, 38, 8])

    # Profil
    ws = wb.create_sheet("Profil")
    titre(ws, "Profil des membres", "Répartition par sexe, ancienneté, activité, province et cabinet")
    ligne_profil = 4
    sexes = [["Femmes", d["sexes"].get("F", 0)], ["Hommes", d["sexes"].get("M", 0)]]
    for libelle, lignes in (("Sexe (personnes physiques)", sexes), ("Ancienneté", d["profil"]["anciennete"]), ("Activité", d["profil"]["actif"]), ("Province", d["profil"]["province"]), ("Principaux cabinets", d["profil"]["cabinets"])):
        if lignes:
            ligne_profil = matrice(ws, ligne_profil, [libelle, "Effectif"], lignes) + 2
    largeurs(ws, [42, 11])

    # À traiter
    ws = wb.create_sheet("À traiter")
    titre(ws, "Dossiers à traiter", "Tout ce qui n'est pas encore inscrit, triable et filtrable")
    a_traiter = [m for m in d["membres"] if classe_conclusion(m.get("conclusion")) != verdict_engine.INSCRIT]
    lignes = [[norm_categorie(m.get("categorie")), _txt(m.get("numero_ordre")), nom_complet(m), _txt(m.get("sexe")), _oui_non(m.get("actif")), _txt(m.get("telephone")), _txt(m.get("email")),
               classe_conclusion(m.get("conclusion")), _txt(m.get("conclusion_motif")), m.get("heures_forco")] for m in a_traiter]
    matrice(ws, 4, ["Catégorie", "N° d'ordre", "Nom", "Sexe", "Actif", "Téléphone", "E-mail", "Conclusion", "Motif", "NHV"], lignes, tableau=True)
    largeurs(ws, [16, 15, 34, 6, 7, 18, 30, 15, 42, 8])

    # Qualité
    ws = wb.create_sheet("Qualité données")
    titre(ws, "Registre de qualité des données", "Anomalies de l'analyse et contrôles de cohérence")
    lignes = [[r["gravite"], r["type"], r["categorie"], r["numero_ordre"], r["nom"], r["observation"], r["action"]] for r in d["registre"]]
    matrice(ws, 4, ["Gravité", "Type", "Catégorie", "N° d'ordre", "Nom", "Observation", "Action recommandée"], lignes, tableau=True)
    largeurs(ws, [11, 32, 16, 15, 32, 52, 42])

    # Sections : une feuille par section, comme le Tableau publié
    for section in d["sections"]:
        ws = wb.create_sheet(section["feuille"][:31])
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = VERT
        ws.page_setup.orientation = "landscape"
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
        ws["A1"] = ctx.organisation
        ws["A1"].font = Font(size=12, bold=True, color=MARINE)
        ws["A2"] = section["titre"]
        ws["A2"].font = Font(size=12, bold=True, color=VERT_FONCE)
        fin_liste = matrice(ws, 4, section["entetes"], section["lignes"], tableau=True)
        for colonne, entete in enumerate(section["entetes"], 1):
            ws.column_dimensions[get_column_letter(colonne)].width = {"N°": 6, "N° d'ordre": 15, "E-mail": 30, "N° téléphone": 18, "Sexe": 6, "Actif": 7, "NHV": 8}.get(entete, 36 if entete in {"Nom, post-noms et prénoms", "Dénomination", "Raison sociale", "Cabinet d'attache", "Employeur", "Associé gérant"} else 13)
        ligne = fin_liste + 3
        lignes = lignes_situation([section], False)
        for colonne, entete in enumerate(["Situation par critère", *(libelle for libelle, _ in ETATS.values())], 1):
            cellule = ws.cell(ligne, colonne, entete)
            cellule.fill = PatternFill("solid", fgColor=MARINE)
            cellule.font = Font(bold=True, color="FFFFFF")
            cellule.alignment = Alignment(wrap_text=True, vertical="center")
        for decalage, valeurs in enumerate(lignes, 1):
            for colonne, valeur in enumerate(valeurs, 1):
                ws.cell(ligne + decalage, colonne, valeur)
        graphique_situation(ws, ligne, len(lignes), section["constat"], f"H{ligne}", 8)
        ligne += len(lignes) + 3
        for bloc in section["blocs"]:
            if not bloc["lignes"]:
                continue
            for colonne, entete in zip((2, 3, 4), (bloc["titre"], "Nombre", "%")):
                cellule = ws.cell(ligne, colonne, entete)
                cellule.fill = PatternFill("solid", fgColor=MARINE)
                cellule.font = Font(bold=True, color="FFFFFF")
                cellule.alignment = Alignment(wrap_text=True, vertical="center")
            for decalage, (libelle, nombre_, part) in enumerate(bloc["lignes"], 1):
                ws.cell(ligne + decalage, 2, libelle).alignment = Alignment(wrap_text=True)
                ws.cell(ligne + decalage, 3, nombre_)
                ws.cell(ligne + decalage, 4, part).number_format = "0.0%"
            fin = ligne + len(bloc["lignes"]) + 1
            for colonne, valeur in zip((2, 3, 4), ("TOTAL", bloc["total"], 1)):
                ws.cell(fin, colonne, valeur).font = Font(bold=True)
            ws.cell(fin, 4).number_format = "0.0%"
            ligne = fin + 2

    # Stagiaires
    if d["stagiaires"]:
        ws = wb.create_sheet("Stagiaires")
        titre(ws, "Stagiaires", "Sans critère automatique : hors taux d'inscription")
        lignes = [[_txt(s.get("numero_ordre")), nom_complet(s), _txt(s.get("sexe")), _txt(s.get("telephone")), _txt(s.get("email"))] for s in d["stagiaires"]]
        matrice(ws, 4, ["N° d'ordre", "Nom", "Sexe", "Téléphone", "E-mail"], lignes, tableau=True)
        largeurs(ws, [15, 34, 6, 18, 30])

    # Plan d'action
    ws = wb.create_sheet("Plan d'action")
    titre(ws, "Plan d'action proposé", "Délais comptés à partir de la validation du plan; à compléter par la Commission Tableau")
    lignes = [ligne + ["À lancer", ""] for ligne in d["plan"]]
    matrice(ws, 4, ["Priorité", "Horizon", "Action", "Pilote proposé", "Indicateur", "Volume", "Statut", "Commentaire"], lignes, tableau=True)
    largeurs(ws, [9, 13, 52, 26, 26, 9, 11, 30])

    # Méthode
    ws = wb.create_sheet("Méthode")
    titre(ws, "Méthode et limites", "Règles appliquées à ce rapport")
    matrice(ws, 4, ["Sujet", "Règle"], [[sujet, regle] for sujet, regle in _methode(d)])
    largeurs(ws, [24, 110])

    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def _methode(d: dict[str, Any]) -> list[tuple[str, str]]:
    ctx: ContexteRapport = d["ctx"]
    r = ctx.reglages
    exemption = (
        f"Formation non requise pour les membres inscrits depuis moins de {r.nouveau_anciennete_ans} an(s), selon l'année du numéro d'ordre, et pour le libellé « Nouveau »."
        if r.exempter_nouveaux else "Aucune exemption des nouveaux membres."
    )
    lignes = [
        ("Source", f"{ctx.source}; situation du {fdate(ctx.date_situation)}."),
        ("Conclusion", f"Résultat de l'analyse selon les réglages de l'exercice, décisions de la commission comprises ({d['decisions']} appliquées)."),
        ("Formation", f"NHV = nombre d'heures validées. Minimum réglé : {heures_txt(r.heures_formation_min)} h. Les exemptés sont exclus des statistiques d'heures."),
        ("Exemption", exemption),
        ("Critères par section", "Cotisation pour toutes les sections; formation pour les personnes physiques; assurance et chiffre d'affaires pour les sociétés et les EC indépendants uniquement; NIF exigé des EC indépendants."),
        ("Taux conforme", "Conformes / (conformes + en défaut). Exemptés et non renseignés sont exclus du dénominateur."),
        ("Contacts partagés", "Alertes à vérifier, pas des doublons certains."),
        ("Limites", "Aucune pièce justificative, preuve de paiement ni police d'assurance n'a été contrôlée individuellement."),
    ]
    if d["nhv"]["soumis"] and not d["nhv"]["renseignes"]:
        lignes.insert(2, ("Heures", AVERTISSEMENT_NHV))
    if ctx.fiches_essai_ecartees or ctx.numeros_ecartes:
        details = [f"{numero} ({motif})" for numero, motif in sorted(ctx.numeros_ecartes.items())]
        if ctx.fiches_essai_ecartees:
            details.append(f"fiches d'essai : {ctx.fiches_essai_ecartees}")
        lignes.insert(2, ("Lignes écartées", "; ".join(details) + "."))
    if d["a_completer"]:
        lignes.insert(2, ("Membres à compléter", MOTIF_A_COMPLETER + " Le taux d'inscription ne porte que sur les dossiers ayant une conclusion."))
        lignes.insert(3, ("Sources des membres", "Fichiers de membres pour l'identité, l'activité et l'assurance; à défaut, déclarations d'assurance; déclarations de chiffre d'affaires pour le CA. " + NOTE_NHV_FICHIER))
    if d["avec_conclusion_source"]:
        lignes.insert(2, ("Rapprochement", f"{d['avec_conclusion_source']} dossiers portent une conclusion dans le fichier importé, comparée à celle de l'analyse."))
    else:
        lignes.insert(2, ("Rapprochement", "Les fichiers importés ne portent pas de colonne de conclusion : aucun rapprochement n'est possible."))
    return lignes


# ── PDF ──────────────────────────────────────────────────────────────────────


def build_pdf(d: dict[str, Any]) -> bytes:
    # Helvetica : son jeu de caractères couvre le français, sans police à embarquer dans l'image.
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ctx: ContexteRapport = d["ctx"]
    largeur, hauteur = A4
    gris = HexColor(f"#{GRIS_TEXTE}")
    marine = HexColor(f"#{MARINE}")
    vert = HexColor(f"#{VERT}")
    corps = ParagraphStyle("corps", fontName="Helvetica", fontSize=9, leading=13, textColor=gris, alignment=TA_JUSTIFY, spaceAfter=6)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=marine, spaceBefore=12, spaceAfter=6, keepWithNext=1)
    petit = ParagraphStyle("petit", fontName="Helvetica", fontSize=7.5, leading=10, textColor=gris, spaceAfter=3)
    cellule = ParagraphStyle("cellule", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=gris)
    gras = ParagraphStyle("gras", parent=cellule, fontName="Helvetica-Bold")
    entete = ParagraphStyle("entete", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.white, alignment=TA_CENTER)

    entete_annexe = ParagraphStyle("entete_annexe", parent=entete, fontSize=6.8, leading=8.5)
    puce = ParagraphStyle("puce", parent=corps, leftIndent=10, bulletIndent=0, alignment=0, spaceAfter=4)
    constat_style = ParagraphStyle("constat", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=marine, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=HexColor(f"#{VERT_FONCE}"), spaceBefore=8, spaceAfter=4, keepWithNext=1)

    def tableau(entetes: list[str], lignes: list[list[Any]], tailles: list[float], total: bool = False, annexe: bool = False) -> Table:
        style_entete = entete_annexe if annexe else entete
        contenu = [[Paragraph(escape(e), style_entete) for e in entetes]]
        for index, ligne in enumerate(lignes):
            style = gras if total and index == len(lignes) - 1 else cellule
            contenu.append([Paragraph(escape(_txt(valeur)), style) for valeur in ligne])
        t = Table(contenu, colWidths=[taille * mm for taille in tailles], repeatRows=1, hAlign="LEFT")
        commandes = [
            ("BACKGROUND", (0, 0), (-1, 0), vert),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, HexColor(f"#{GRIS_MOYEN}")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        commandes += [("BACKGROUND", (0, i), (-1, i), HexColor(f"#{GRIS_CLAIR}")) for i in range(2, len(contenu), 2)]
        t.setStyle(TableStyle(commandes))
        return t

    def figure_situation(sections: list[dict[str, Any]]) -> Drawing:
        """Une barre empilée à 100 % par critère et par section, avec les nombres écrits dessus."""
        hauteur_ligne, hauteur_tete, hauteur_legende = 5.6 * mm, 6.5 * mm, 9 * mm
        lignes_total = sum(len(section["situation"]) for section in sections)
        hauteur_totale = lignes_total * hauteur_ligne + len(sections) * hauteur_tete + hauteur_legende
        dessin = Drawing(180 * mm, hauteur_totale)
        x_legende = 0.0
        for libelle, couleur in ETATS.values():
            dessin.add(Rect(x_legende, hauteur_totale - 4 * mm, 3 * mm, 3 * mm, fillColor=HexColor(f"#{couleur}"), strokeColor=None))
            dessin.add(String(x_legende + 4 * mm, hauteur_totale - 3.5 * mm, libelle, fontName="Helvetica", fontSize=7, fillColor=gris))
            x_legende += 5 * mm + stringWidth(libelle, "Helvetica", 7) + 3 * mm
        y = hauteur_totale - hauteur_legende
        x_barre, largeur_barre = 34 * mm, 146 * mm
        for section in sections:
            y -= hauteur_tete
            dessin.add(String(0, y + 1.5 * mm, section["court"], fontName="Helvetica-Bold", fontSize=8.5, fillColor=marine))
            for ligne in section["situation"]:
                y -= hauteur_ligne
                dessin.add(String(0, y + 1.3 * mm, ligne["libelle"][:24], fontName="Helvetica", fontSize=7.5, fillColor=gris))
                x = x_barre
                for cle, (_, couleur) in ETATS.items():
                    volume = ligne["etats"][cle]
                    if not volume or not ligne["total"]:
                        continue
                    large = largeur_barre * volume / ligne["total"]
                    dessin.add(Rect(x, y + 0.5 * mm, large, 4.3 * mm, fillColor=HexColor(f"#{couleur}"), strokeColor=colors.white, strokeWidth=0.4))
                    if large > 7 * mm:
                        encre = marine if cle in {"inconnu", "exempte"} else colors.white
                        dessin.add(String(x + large / 2, y + 1.5 * mm, str(volume), fontName="Helvetica-Bold", fontSize=7, fillColor=encre, textAnchor="middle"))
                    x += large
        return dessin

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
        canvas.setStrokeColor(HexColor(f"#{GRIS_MOYEN}"))
        canvas.line(15 * mm, 13 * mm, largeur - 15 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(gris)
        canvas.drawString(15 * mm, 9 * mm, f"Rapport complet du Tableau {ctx.exercice} · situation du {fdate(ctx.date_situation)} · usage interne")
        canvas.drawRightString(largeur - 15 * mm, 9 * mm, f"Page {doc.page}")

    def page_suivante(canvas, doc) -> None:
        canvas.saveState()
        pied(canvas, doc)
        canvas.restoreState()

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(
        tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Rapport complet du Tableau {ctx.exercice}", author=ctx.organisation,
    )
    S: list[Any] = [
        Spacer(1, 14 * mm),
        Paragraph(f"Rapport complet du Tableau {escape(ctx.exercice)}", ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=marine, spaceAfter=4)),
        Paragraph(f"{escape(ctx.source)} · situation du {fdate(ctx.date_situation)} · généré le {fdate(ctx.genere_le)}", petit),
    ]

    # 1. Synthèse pour le Bureau
    S.append(Paragraph("1. Synthèse pour le Bureau", h1))
    kpis = [("Membres", str(d["total"]), MARINE, BLEU_CLAIR)]
    if d["total"] - d["a_completer"]:
        kpis += [("Inscrits", str(d["inscrits"]), VERT_FONCE, VERT_CLAIR), ("Non inscrits", str(d["non_inscrits"]), ROUGE, ROUGE_CLAIR)]
        if d["a_deliberer"]:
            kpis.append(("À délibérer", str(d["a_deliberer"]), OR, OR_CLAIR))
        kpis.append(("Taux d'inscription", pct(d["taux"]), OR, OR_CLAIR))
    if d["a_completer"]:
        kpis.append(("À compléter", str(d["a_completer"]), MARINE, GRIS_CLAIR))
    nif_critere = next((c for c in d["criteres"] if c["critere"] == "nif"), None)
    if nif_critere and nif_critere["defauts"]:
        kpis.append(("EC indépendants sans NIF", str(nif_critere["defauts"]), ROUGE, ROUGE_CLAIR))
    kpi = ParagraphStyle("kpi", alignment=TA_CENTER, leading=17)
    t = Table([[Paragraph(f'<font name="Helvetica-Bold" size="14" color="#{c}">{escape(v)}</font><br/><font size="7" color="#{GRIS_TEXTE}">{escape(l.upper())}</font>', kpi) for l, v, c, _ in kpis]], colWidths=[180 / len(kpis) * mm] * len(kpis), rowHeights=[18 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")] + [("BACKGROUND", (i, 0), (i, 0), HexColor(f"#{item[3]}")) for i, item in enumerate(kpis)]))
    S += [t, Spacer(1, 3 * mm)]
    S.append(Paragraph("Constats", h2))
    if d["constats"]:
        S.extend(Paragraph(escape(item), puce, bulletText="•") for item in d["constats"])
    else:
        S.append(Paragraph("Aucun constat particulier.", corps))
    S.append(Paragraph("Décisions attendues", h2))
    if d["decisions_attendues"]:
        S.extend(Paragraph(escape(item), puce, bulletText="•") for item in d["decisions_attendues"])
    else:
        S.append(Paragraph("Aucune décision en attente.", corps))
    if d["decisions"]:
        S.append(Paragraph(f"Ces conclusions intègrent {d['decisions']} décision(s) de la commission.", petit))
    S.append(Paragraph("Résultats par section", h2))
    cles = [("categorie", "Section", 58), ("total", "Total", 18), ("inscrits", "Inscrits", 20), ("non_inscrits", "Non inscrits", 22), ("a_deliberer", "À délibérer", 22), ("a_completer", "À compléter", 22)]
    gardees = [c for c in cles if c[0] in {"categorie", "total"} or any(l[c[0]] for l in d["categories"])]
    avec_taux = any(l["taux"] is not None for l in d["categories"])
    lignes = [[l[c[0]] for c in gardees] + ([pct(l["taux"])] if avec_taux else []) for l in d["categories"]]
    lignes.append(["TOTAL"] + [d[c[0]] for c in gardees[1:]] + ([pct(d["taux"])] if avec_taux else []))
    S.append(tableau([c[1] for c in gardees] + (["Taux"] if avec_taux else []), lignes, [c[2] for c in gardees] + ([18] if avec_taux else []), total=True))
    S.append(PageBreak())

    # 2. Situation par section
    S.append(Paragraph("2. Situation par section et par critère", h1))
    S.append(Paragraph(escape(d["titre_situation"]), constat_style))
    if d["sections"]:
        S += [figure_situation(d["sections"]), Spacer(1, 3 * mm)]
    lignes = [[c["libelle"], c["perimetre"], c["conformes"], c["defauts"], c["exemptes"], c["inconnus"], pct(c["taux"])] for c in d["criteres"]]
    S.append(tableau(["Critère", "Périmètre", "Conformes", "En défaut", "Exemptés", "Non renseignés", "Taux conforme"], lignes, [48, 20, 20, 20, 20, 22, 20]))
    S.append(Paragraph("Assurance et chiffre d'affaires ne concernent que les sociétés et les EC indépendants; le NIF est exigé des EC indépendants. Taux conforme = conformes / (conformes + en défaut). Plusieurs défauts peuvent concerner le même dossier : ces nombres ne s'additionnent pas.", petit))

    # Statistiques par section
    numero = 3
    for section in d["sections"]:
        S.append(Paragraph(f"{numero}. {escape(section['titre'])}", h1))
        numero += 1
        S.append(Paragraph(f"{section['total']} membres. {escape(section['constat'])}", constat_style))
        lignes_blocs = []
        for bloc in section["blocs"]:
            for rang, (libelle, nombre_, part) in enumerate(bloc["lignes"]):
                lignes_blocs.append([bloc["titre"] if rang == 0 else "", libelle, nombre_, pct(part)])
        S.append(tableau(["Rubrique", "Situation", "Nombre", "%"], lignes_blocs, [52, 80, 22, 26]))

    # Formation
    n = d["nhv"]
    S.append(Paragraph(f"{numero}. Formation continue (NHV, heures validées)", h1))
    numero += 1
    lignes = [
        ["Dossiers soumis à la formation", n["soumis"]], ["Exemptés, exclus des statistiques", n["exemptes"]],
        ["Dossiers avec un NHV renseigné", n["renseignes"]],
    ]
    if n["renseignes"] and d["a_completer"]:
        # « % 120 FOR » n'est pas forcément exprimé en heures : ni unité, ni somme.
        lignes += [
            ["Moyenne des valeurs importées", nombre(n["moyenne"])], ["Médiane des valeurs importées", nombre(n["mediane"])],
            ["Dossiers à 0", n["zero"]], [f"Dossiers sous le minimum réglé ({heures_txt(ctx.reglages.heures_formation_min)})", n["sous_seuil"]],
        ]
    elif n["renseignes"]:
        lignes += [
            ["Heures validées totales", f"{nombre(n['total'])} h"], ["Moyenne", f"{nombre(n['moyenne'])} h"], ["Médiane", f"{nombre(n['mediane'])} h"],
            ["Dossiers à 0 heure", n["zero"]], [f"Dossiers sous {heures_txt(ctx.reglages.heures_formation_min)} h", n["sous_seuil"]],
        ]
    S.append(tableau(["Indicateur", "Résultat"], lignes, [100, 50]))
    if n["soumis"] and not n["renseignes"]:
        S.append(Spacer(1, 2 * mm))
        S.append(Paragraph(AVERTISSEMENT_NHV, corps))

    if d["a_completer"] and n["renseignes"]:
        S.append(Spacer(1, 2 * mm))
        S.append(Paragraph(NOTE_NHV_FICHIER, petit))

    # Profil
    S.append(Paragraph(f"{numero}. Profil des membres", h1))
    numero += 1
    femmes, hommes = d["sexes"].get("F", 0), d["sexes"].get("M", 0)
    if femmes + hommes:
        S.append(Paragraph(f"Les femmes représentent {pct(femmes / (femmes + hommes))} des {femmes + hommes} experts-comptables individuels dont le sexe est renseigné.", corps))
    profil_lignes = [["Sexe", "Femmes", femmes], ["Sexe", "Hommes", hommes]] if femmes + hommes else []
    for rubrique, cle in (("Activité", "actif"), ("Province", "province"), ("Cabinet", "cabinets")):
        profil_lignes += [[rubrique, libelle, effectif] for libelle, effectif in d["profil"][cle]]
    if profil_lignes:
        S.append(tableau(["Rubrique", "Valeur", "Effectif"], profil_lignes, [30, 110, 20]))

    # Rapprochement : seulement s'il y a de quoi comparer
    if d["avec_conclusion_source"] or ctx.comparaison_nom:
        S.append(Paragraph(f"{numero}. Rapprochement des conclusions", h1))
        numero += 1
        if d["avec_conclusion_source"]:
            S.append(Paragraph(f"{d['avec_conclusion_source']} dossiers portent une conclusion dans le fichier importé : {len(d['ecarts_fichier'])} diffèrent de l'analyse.", corps))
        if d["ecarts_fichier"]:
            lignes = [[e["numero_ordre"] or "—", e["nom"], e["conclusion"], e["autre"], heures_txt(e["nhv"]), e["motif"]] for e in d["ecarts_fichier"]]
            S.append(tableau(["N° d'ordre", "Nom", "Analyse", "Fichier", "NHV", "Motif de l'analyse"], lignes, [24, 50, 20, 20, 11, 55]))
        if ctx.comparaison_nom:
            S.append(Spacer(1, 3 * mm))
            S.append(Paragraph(f"Comparaison avec {escape(ctx.comparaison_nom)} : {len(d['ecarts_comparaison'])} conclusion(s) diffèrent.", corps))
            if d["ecarts_comparaison"]:
                lignes = [[e["numero_ordre"] or "—", e["nom"], e["conclusion"], e["autre"], heures_txt(e["nhv"]), heures_txt(e.get("nhv_autre"))] for e in d["ecarts_comparaison"]]
                S.append(tableau(["N° d'ordre", "Nom", "Analyse", "Comparaison", "NHV", "NHV comparaison"], lignes, [26, 62, 24, 26, 15, 27]))

    # Qualité
    S.append(Paragraph(f"{numero}. Qualité des données", h1))
    numero += 1
    if d["types_registre"]:
        lignes = [[g, t_, v] for (g, t_), v in sorted(d["types_registre"].items(), key=lambda x: (ORDRE_GRAVITE.get(x[0][0], 9), x[0][1]))]
        S.append(tableau(["Gravité", "Contrôle", "Volume"], lignes, [28, 112, 20]))
        S.append(Paragraph("Le détail, dossier par dossier, figure dans la feuille « Qualité données » du classeur Excel.", petit))
    else:
        S.append(Paragraph("Aucune anomalie de donnée relevée.", corps))

    # Plan
    S.append(Paragraph(f"{numero}. Plan d'action proposé", h1))
    numero += 1
    if d["plan"]:
        S.append(Paragraph("Actions calculées à partir des constats ci-dessus; les délais courent à partir de la validation du plan.", petit))
        S.append(tableau(["Priorité", "Horizon", "Action", "Pilote proposé", "Volume"], [[l[0], l[1], l[2], l[3], l[5]] for l in d["plan"]], [15, 22, 80, 40, 15]))
    else:
        S.append(Paragraph("Aucune action ouverte.", corps))

    # Méthode
    S.append(Paragraph(f"{numero}. Méthode et limites", h1))
    if d["stagiaires"]:
        S.append(Paragraph(f"{len(d['stagiaires'])} stagiaire(s) sont listés dans le classeur Excel; sans critère automatique, ils sont hors du taux d'inscription.", corps))
    S.append(tableau(["Sujet", "Règle"], [list(item) for item in _methode(d)], [32, 148]))

    # Annexes : les listes, après l'analyse
    tailles = {"N°": 7, "N° d'ordre": 20, "Actif": 10, "Ancienneté": 16, "Cotisation": 15, "Assurance valide": 15, "H.Formation": 17, "Chiffre d'affaires": 14, "Conclusion": 17, "NHV": 9, "NIF": 18}
    for rang, section in enumerate(d["sections"], 1):
        S.append(PageBreak())
        S.append(Paragraph(f"Annexe {rang}. {escape(section['titre'])}", h1))
        masque = {"N° téléphone", "E-mail", "Sexe", "Raison sociale", "Associé gérant", "Cabinet d'attache", "Employeur"} | ({"NIF"} if section["categorie"] != "EC Indépendant" else set())
        gardees = [
            i for i, entete_ in enumerate(section["entetes"])
            if entete_ not in masque and not (entete_ == "Cotisation" and not any(ligne[i] for ligne in section["lignes"]))
        ]
        occupe = sum(tailles.get(section["entetes"][i], 0) for i in gardees)
        tailles_pdf = [tailles.get(section["entetes"][i], 180 - occupe) for i in gardees]
        lignes_liste = [["" if ligne[i] is None else (heures_txt(ligne[i]) if isinstance(ligne[i], float) else ligne[i]) for i in gardees] for ligne in section["lignes"]]
        S.append(tableau([section["entetes"][i] for i in gardees], lignes_liste, tailles_pdf, annexe=True))

    doc.build(S, onFirstPage=premiere_page, onLaterPages=page_suivante)
    return tampon.getvalue()
