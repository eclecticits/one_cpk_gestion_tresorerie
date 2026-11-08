"""Relevé de situation au Tableau, envoyé au membre par e-mail et WhatsApp.

Le relevé dit au membre ce que dit la Base du Tableau, ni plus ni moins :

* **les critères sont ceux de sa catégorie**, selon les réglages
  (`verdict.criteres_requis`) — un EC Cabinet n'a pas de ligne Assurance ;
* **la conclusion est celle de la colonne Conclusion** ;
* la cotisation se lit « soldée » ou « non soldée », sans montant ;
* la formation donne les heures validées (NHV) face au minimum de la catégorie.

Rien ne part pour un dossier « À délibérer » (la commission n'a pas tranché),
non analysé, ou d'un membre sorti du Tableau.

La civilité suit le sexe renseigné ; sans sexe, « Madame, Monsieur ». Un membre
du Bureau est appelé par sa fonction (« Madame la Trésorière »), seulement si
son N° d'ordre ou son e-mail le relie sans ambiguïté à sa fiche du Bureau. Une
société est saluée à l'attention de son associé gérant.

Le membre qui conteste ne répond pas au message : il déclare sur son espace
membre. Le relevé est signé par la Commission Tableau du conseil.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import defer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_member import CommissionMember
from app.models.notification_log import STATUS_SENT, NotificationLog
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.services.email_config import SMTPConfig, resolve_smtp_config
from app.services.mailer import (
    _releve_situation_html,
    normalize_email_list,
    send_in_thread,
    send_releve_situation_email,
)
from app.services.notifications import (
    TABLEAU_SITUATION,
    Recipient,
    WhatsAppSettings,
    load_bureau_members,
    load_whatsapp_settings,
    normalize_phone,
    notify_whatsapp,
)
from app.services.system_settings_service import get_system_settings
from app.utils.hierarchie_fonctions import rang_fonction

from . import verdict as verdict_engine
from .audit import record_tableau_audit
from .models import TableauDossier, TableauImport, TableauReleve, TableauReleveLot
from .service import _norm_numero_ordre, get_base_tableau
from .sorties import est_morale

logger = logging.getLogger("onec_cpk_api.tableau.releves")

ESPACE_MEMBRE_URL = "https://membres.onecrdc.com"
MARQUE = "ONEC-RDC"
ENTITY_TYPE = "tableau_releve"
CANAUX = ("email", "whatsapp")

CONCLUSIONS_ENVOYABLES = {
    verdict_engine.INSCRIT: "EN RÈGLE",
    verdict_engine.NON_INSCRIT: "NON EN RÈGLE",
}


# ── Civilité ────────────────────────────────────────────────────────────────

# Fonctions du Bureau qui donnent un titre d'appel. « Membre », « Assistant(e) »,
# « Autre » n'en donnent pas : « Monsieur le Membre » ne se dit pas.
_FONCTIONS_APPEL = ("président", "rapporteur", "trésorier", "secrétaire")

_FEMININS = {
    "président": "présidente",
    "vice-président": "vice-présidente",
    "trésorier": "trésorière",
    "rapporteur": "rapporteure",
    "adjoint": "adjointe",
    "exécutif": "exécutive",
    "général": "générale",
}


def _sexe(valeur: str | None) -> str | None:
    v = (valeur or "").strip().upper()
    if v in {"M", "H", "MASCULIN", "HOMME"}:
        return "M"
    if v in {"F", "FEMININ", "FÉMININ", "FEMME"}:
        return "F"
    return None


def fonction_accordee(libelle: str | None, sexe: str | None) -> str | None:
    """« Trésorier(e) adjoint » → « Trésorière adjointe » pour une femme.

    None si la fonction ne donne pas de titre d'appel, ou si le sexe n'est pas
    connu : on n'accorde pas au hasard.
    """
    libelle = (libelle or "").strip()
    sexe = _sexe(sexe)
    if not libelle or sexe is None or not any(f in libelle.casefold() for f in _FONCTIONS_APPEL):
        return None
    masculin = re.sub(r"\((?:e|ve|euse|rice)\)", "", libelle, flags=re.IGNORECASE)
    masculin = re.sub(r"\s+", " ", masculin).strip()
    if sexe == "M":
        return masculin

    def feminiser(match: re.Match[str]) -> str:
        mot = match.group(0)
        feminin = _FEMININS.get(mot.casefold())
        if feminin is None:
            return mot
        return feminin[0].upper() + feminin[1:] if mot[0].isupper() else feminin

    return re.sub(r"[\wÀ-ÿ-]+", feminiser, masculin)


def libelle_organisation(organisation: str | None) -> str:
    """« ONEC-RDC – Conseil Provincial de Kinshasa » : l'Ordre, puis le conseil qui écrit."""
    org = (organisation or "").strip()
    if not org or org.upper().startswith(MARQUE):
        return org or MARQUE
    return f"{MARQUE} – {org}"


def appel_confraternel(sexe: str | None, categorie: str | None) -> str:
    """« Cher Expert-Comptable, » / « Chère Experte-Comptable, » selon le sexe."""
    stagiaire = " stagiaire" if (categorie or "").casefold() == "stagiaire" else ""
    if sexe == "M":
        return f"Cher Expert-Comptable{stagiaire},"
    if sexe == "F":
        return f"Chère Experte-Comptable{stagiaire},"
    return f"Cher(e) Expert(e)-Comptable{stagiaire},"


def _appel_fonction(fonction: str, sexe: str) -> str:
    """« Madame la Trésorière », « Monsieur le Président »."""
    return f"Madame la {fonction}" if sexe == "F" else f"Monsieur le {fonction}"


# ── Le relevé ───────────────────────────────────────────────────────────────


@dataclass
class Releve:
    numero_ordre: str
    nom: str
    categorie: str | None
    conclusion: str | None
    raison: str | None = None
    sujet: str = ""
    corps: str = ""
    emails: list[str] = field(default_factory=list)
    telephone: str | None = None
    fonction_bureau: str | None = None
    empreinte: str = ""
    # Pourquoi le relevé ne part pas : sorti, a_deliberer, sans_conclusion,
    # sans_numero, sans_contact. None quand il est envoyable.
    blocage: str | None = None
    # Les morceaux du message, que chaque canal met en forme à sa façon.
    reference: str = ""
    entete: list[str] = field(default_factory=list)
    appel: str = ""
    annonce: str = ""
    criteres: list[tuple[str, str]] = field(default_factory=list)
    # Pour chaque critère : True conforme, False à régulariser, None inconnu.
    conformites: list[bool | None] = field(default_factory=list)
    conclusion_libelle: str = ""
    en_regle: bool = False
    consigne: str = ""
    politesse: str = ""
    organisation: str = ""

    @property
    def envoyable(self) -> bool:
        return self.blocage is None


def _heures(valeur: float) -> str:
    return f"{int(valeur)}" if float(valeur).is_integer() else f"{valeur:g}".replace(".", ",")


def _date_fr(valeur: Any) -> str:
    if isinstance(valeur, datetime):
        valeur = valeur.date()
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    return date.today().strftime("%d/%m/%Y")


def _annee(exercice: str) -> str:
    m = re.search(r"(20\d{2})", exercice or "")
    return m.group(1) if m else (exercice or "")


def criteres_releve(membre: dict[str, Any], reglages: verdict_engine.TableauReglages) -> list[tuple[str, str, bool | None]]:
    """Un critère de la catégorie par ligne, dans l'ordre des colonnes du Tableau :
    libellé, valeur lue par le membre, et conformité (None quand on ne sait pas)."""
    categorie = membre.get("categorie")
    lignes: list[tuple[str, str, bool | None]] = []
    for critere in verdict_engine.criteres_requis(categorie, reglages) or []:
        if critere == "cotisation":
            etat = membre.get("cotisation_etat")
            # Ni note de débit ni valeur importée : un tiret, sans rien affirmer.
            if not etat:
                lignes.append(("Cotisation", "-", None))
            else:
                lignes.append(("Cotisation", "soldée" if etat == "payee" else "non soldée", etat == "payee"))
        elif critere == "formation":
            etat = membre.get("formation_etat")
            nhv = membre.get("nhv")
            minimum = reglages.heures_min(categorie)
            conforme = {"atteint": True, "non_requis": True, "insuffisant": False}.get(etat or "")
            if etat == "non_requis":
                texte = "non requise (nouveau membre)"
            elif nhv is not None:
                texte = f"{_heures(float(nhv))} h validées sur {_heures(minimum)} h requises"
                if conforme is None:
                    conforme = float(nhv) >= minimum
            else:
                texte = {"atteint": "conforme", "insuffisant": "insuffisante"}.get(etat or "", "non renseignée")
            lignes.append(("Formation (NHV)", texte, conforme))
        elif critere == "assurance":
            valeur = membre.get("assurance")
            lignes.append(("Assurance", "non renseignée" if valeur is None else ("valide" if valeur else "non valide"), valeur))
        elif critere == "chiffre_affaires":
            valeur = membre.get("chiffre_affaires")
            lignes.append(("Chiffre d'affaires", "non renseigné" if valeur is None else ("déclaré" if valeur else "non déclaré"), valeur))
    return lignes


_DEMARCHES = {
    "cotisation": "effectué un paiement",
    "formation": "suivi une formation",
    "assurance": "souscrit une assurance",
    "chiffre_affaires": "déclaré {possessif} chiffre d'affaires",
}


def consigne_declaration(categorie: str | None, reglages: verdict_engine.TableauReglages, societe: bool) -> str:
    """« Si vous avez effectué un paiement ou suivi une formation… » : les seules démarches de la catégorie."""
    possessif = "son" if societe else "votre"
    demarches = [
        _DEMARCHES[c].format(possessif=possessif)
        for c in verdict_engine.criteres_requis(categorie, reglages) or []
        if c in _DEMARCHES
    ]
    if not demarches:
        return "Pour toute mise à jour de votre dossier, merci de la déclarer sur votre espace membre."
    liste = demarches[0] if len(demarches) == 1 else ", ".join(demarches[:-1]) + " ou " + demarches[-1]
    sujet = "Si votre société a" if societe else "Si vous avez"
    return f"{sujet} {liste} et que cela n'apparaît pas ci-dessus, merci de le déclarer sur votre espace membre."


def _empreinte(exercice: str, numero: str, conclusion: str, lignes: list[str]) -> str:
    """La situation, sans la date : un réimport qui ne change rien n'appelle pas un nouvel envoi."""
    brut = json.dumps([exercice, numero, conclusion, lignes], ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def construire_releve(
    membre: dict[str, Any],
    *,
    exercice: str,
    reglages: verdict_engine.TableauReglages,
    organisation: str,
    fonction_bureau: str | None = None,
) -> Releve:
    """Le relevé d'un membre : texte, destinataires, et s'il peut partir."""
    numero = membre.get("numero_ordre") or ""
    nom = " ".join(x for x in (membre.get("nom"), membre.get("prenom")) if x).strip()
    categorie = membre.get("categorie")
    conclusion = membre.get("conclusion")
    releve = Releve(
        numero_ordre=numero,
        nom=nom,
        categorie=categorie,
        conclusion=conclusion,
        emails=normalize_email_list(membre.get("email")),
        telephone=normalize_phone(membre.get("telephone")),
    )

    sortie = membre.get("sortie")
    if sortie:
        releve.blocage = "sorti"
        releve.raison = f"Membre sorti du Tableau ({sortie.get('libelle') or 'sortie déclarée'}) : aucun relevé n'est envoyé."
        return releve
    verdict = (conclusion or "").strip().upper()
    if verdict == verdict_engine.A_DELIBERER:
        releve.blocage = "a_deliberer"
        releve.raison = "Dossier à délibérer : le relevé partira quand la commission aura tranché."
        return releve
    if verdict not in CONCLUSIONS_ENVOYABLES:
        releve.blocage = "sans_conclusion"
        releve.raison = "Dossier sans conclusion : lancez l'analyse avant d'envoyer le relevé."
        return releve
    if not numero:
        releve.blocage = "sans_numero"
        releve.raison = "N° d'ordre manquant : le dossier est à compléter."
        return releve

    libelle = CONCLUSIONS_ENVOYABLES[verdict]
    en_regle = verdict == verdict_engine.INSCRIT
    evalues = criteres_releve(membre, reglages)
    criteres = [(label, valeur) for label, valeur, _ in evalues]
    arretee = _date_fr(membre.get("date_situation"))
    annee = _annee(exercice)
    societe = est_morale(categorie)
    sexe = _sexe(membre.get("sexe"))

    entete: list[str] = []
    politesse = "nos salutations distinguées"
    if societe:
        raison_sociale = membre.get("raison_sociale") or nom
        gerant = (membre.get("associe_gerant") or "").strip()
        if gerant:
            entete.append(f"À l'attention de {gerant}, associé gérant")
        entete.append(f"Société : {raison_sociale} – N° d'ordre : {numero}")
        appel = formule = "Madame, Monsieur"
        objet = "de la situation de votre société"
        releve.sujet = f"Situation de votre société au Tableau de l'Ordre – exercice {annee}"
    else:
        # Personne physique : on s'adresse au confrère, puis on le nomme.
        objet = "de votre situation"
        releve.sujet = f"Votre situation au Tableau de l'Ordre – exercice {annee}"
        appel = appel_confraternel(sexe, categorie).rstrip(",")
        civilite = {"M": "Monsieur ", "F": "Madame "}.get(sexe, "")
        if fonction_bureau and sexe:
            # Membre du Bureau : sa fonction dans l'identité et dans la formule finale.
            entete.append(f"{civilite}{nom}, {fonction_bureau} du Bureau – N° d'ordre : {numero}")
            formule = _appel_fonction(fonction_bureau, sexe)
            politesse = "notre haute considération"
            releve.fonction_bureau = fonction_bureau
        else:
            entete.append(f"{civilite}{nom} – N° d'ordre : {numero}")
            formule = {"M": "Monsieur", "F": "Madame"}.get(sexe, "Madame, Monsieur")

    annonce = "Nous avons le plaisir de vous informer" if en_regle else "Nous vous informons"
    releve.reference = f"Exercice {annee} · N° d'ordre {numero}"
    releve.entete = entete
    releve.appel = f"{appel},"
    releve.annonce = f"{annonce} {objet} au Tableau de l'Ordre, arrêtée au {arretee} :"
    releve.criteres = criteres
    releve.conformites = [conforme for _, _, conforme in evalues]
    releve.conclusion_libelle = libelle
    releve.en_regle = en_regle
    releve.consigne = "" if en_regle else consigne_declaration(categorie, reglages, societe)
    releve.politesse = f"Veuillez agréer, {formule}, l'expression de {politesse}."
    organisation = libelle_organisation(organisation)
    releve.organisation = organisation

    # Version texte : celle de l'e-mail sans mise en forme, et celle du journal.
    lignes = [f"{label} : {valeur}" for label, valeur in criteres]
    if societe:
        corps = [*entete, "", releve.appel, ""]
    else:
        corps = [releve.appel, *entete, ""]
    corps += [releve.annonce, ""]
    corps += [f"- {ligne}" for ligne in lignes]
    corps += ["", f"Conclusion : {libelle}", ""]
    if releve.consigne:
        corps += [releve.consigne, ESPACE_MEMBRE_URL, ""]
    corps += [releve.politesse, "", "La Commission Tableau", organisation]
    releve.corps = "\n".join(corps)
    releve.empreinte = _empreinte(exercice, numero, verdict, lignes)
    if not releve.emails and not releve.telephone:
        releve.blocage = "sans_contact"
        releve.raison = "Ni e-mail ni téléphone au dossier : complétez la fiche du membre."
    return releve


def html_releve(releve: Releve) -> str:
    return _releve_situation_html(
        titre="Situation au Tableau de l'Ordre",
        reference=releve.reference,
        entete=releve.entete,
        appel=releve.appel,
        annonce=releve.annonce,
        criteres=[(label, valeur, conforme) for (label, valeur), conforme in zip(releve.criteres, releve.conformites)],
        conclusion=releve.conclusion_libelle,
        apercu_boite=f"Conclusion : {releve.conclusion_libelle} – {releve.reference}",
        en_regle=releve.en_regle,
        consigne=releve.consigne,
        lien=ESPACE_MEMBRE_URL,
        politesse=releve.politesse,
        brand_label=releve.organisation,
    )


def variables_whatsapp(releve: Releve) -> dict[str, str]:
    """Les trous du gabarit TABLEAU_SITUATION, mis en forme comme les autres messages."""
    if est_morale(releve.categorie):
        salutation = [*releve.entete, "", releve.appel]
    else:
        salutation = [releve.appel, *releve.entete]
    return {
        "reference": releve.reference,
        "salutation": "\n".join(salutation) + "\n",
        "message": releve.annonce,
        "resume": "".join(f"▸ *{label} :* {valeur}\n" for label, valeur in releve.criteres).rstrip("\n"),
        "conclusion": releve.conclusion_libelle,
        "consigne": f"{releve.consigne}\n{ESPACE_MEMBRE_URL}" if releve.consigne else "",
        "organisation": releve.organisation or MARQUE,
    }


# ── Lecture du membre ───────────────────────────────────────────────────────


def _membre_depuis_dossier(dossier: TableauDossier) -> dict[str, Any]:
    """`sortie`, `cotisation_notes`, `assurance_valide`… sont posés par `get_base_tableau`."""
    notes = dossier.cotisation_notes
    etat = notes.get("etat") if notes else None
    if etat is None and dossier.cotisation_payee is not None:
        etat = "payee" if dossier.cotisation_payee else "non_payee"
    return {
        "numero_ordre": dossier.numero_ordre,
        "nom": dossier.nom,
        "prenom": dossier.prenom,
        "sexe": dossier.sexe,
        "email": dossier.email,
        "telephone": dossier.telephone,
        "categorie": dossier.categorie,
        "conclusion": dossier.conclusion,
        "sortie": dossier.sortie,
        "cotisation_etat": etat,
        "nhv": float(dossier.heures_forco) if dossier.heures_forco is not None else None,
        "formation_etat": dossier.formation_etat,
        "assurance": dossier.assurance_valide,
        "chiffre_affaires": dossier.chiffre_affaires,
        "raison_sociale": dossier.raison_sociale,
        "associe_gerant": dossier.associe_gerant,
        "date_situation": dossier.date_situation,
    }


def _membre_depuis_ligne(ligne: dict[str, Any]) -> dict[str, Any]:
    notes = ligne.get("cotisation_notes")
    return {
        **{k: ligne.get(k) for k in (
            "numero_ordre", "nom", "sexe", "email", "telephone", "categorie", "conclusion", "sortie",
            "nhv", "formation_etat", "chiffre_affaires", "raison_sociale", "associe_gerant", "date_situation",
        )},
        "prenom": None,
        "cotisation_etat": notes.get("etat") if notes else None,
        "assurance": ligne.get("assurance_valide"),
    }


async def _reglages(db: AsyncSession, organisation_id: int, exercice: str) -> verdict_engine.TableauReglages:
    """Ceux du dernier import de l'exercice, comme la Base."""
    meta = (await db.execute(
        select(TableauImport.metadata_json)
        .where(TableauImport.organisation_id == organisation_id, TableauImport.exercice == exercice)
        .order_by(TableauImport.date_situation.desc(), TableauImport.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    return verdict_engine.TableauReglages.from_dict((meta or {}).get("reglages"))


async def _organisation(db: AsyncSession, organisation_id: int) -> str:
    """Le nom du conseil tel qu'il s'imprime, à défaut celui de l'organisation."""
    imprime = (await db.execute(
        select(PrintSettings.organization_name).where(PrintSettings.organisation_id == organisation_id).limit(1)
    )).scalar_one_or_none()
    if (imprime or "").strip():
        return imprime.strip()
    return (await db.execute(
        select(Organisation.nom).where(Organisation.id == organisation_id).limit(1)
    )).scalar_one_or_none() or ""


@dataclass
class Contexte:
    """Ce qui vaut pour tous les relevés d'un conseil et d'un exercice : lu une fois."""

    exercice: str
    reglages: verdict_engine.TableauReglages
    organisation: str
    bureau: list[CommissionMember]


async def _contexte(db: AsyncSession, organisation_id: int, exercice: str) -> Contexte:
    fiches = [
        fiche for fiche in await load_bureau_members(db, organisation_id, only_opted_in=False)
        if "bureau" in fiche.service.libelle.casefold()
    ]
    return Contexte(
        exercice=exercice,
        reglages=await _reglages(db, organisation_id, exercice),
        organisation=await _organisation(db, organisation_id),
        bureau=fiches,
    )


def _fonction_bureau(fiches: list[CommissionMember], numero: str, emails: list[str], sexe: str | None) -> str | None:
    """La fonction du membre au Bureau, s'il y siège et qu'on l'y reconnaît sans doute."""
    adresses = {e.casefold() for e in emails}
    trouves: list[tuple[int, str]] = []
    for fiche in fiches:
        meme_numero = bool(fiche.matricule) and _norm_numero_ordre(fiche.matricule) == numero
        meme_email = bool(fiche.email) and fiche.email.strip().casefold() in adresses
        if not (meme_numero or meme_email):
            continue
        libelle = (fiche.function.label if fiche.function is not None else "") or fiche.custom_title or ""
        accordee = fonction_accordee(libelle, sexe)
        if accordee:
            trouves.append((rang_fonction(libelle), accordee))
    return min(trouves)[1] if trouves else None


def _releve_de(membre: dict[str, Any], ctx: Contexte) -> Releve:
    numero = membre.get("numero_ordre") or ""
    fonction = _fonction_bureau(ctx.bureau, numero, normalize_email_list(membre.get("email")), membre.get("sexe")) if numero else None
    return construire_releve(
        membre, exercice=ctx.exercice, reglages=ctx.reglages, organisation=ctx.organisation, fonction_bureau=fonction,
    )


def _membres_de_la_base(base: dict[str, Any]) -> list[dict[str, Any]]:
    """Dossiers puis membres sans dossier, dans l'ordre de la Base, n° d'ordre normalisé."""
    membres = [_membre_depuis_dossier(d) for d in base["dossiers"]]
    membres += [_membre_depuis_ligne(m) for m in base["membres_a_completer"]]
    for membre in membres:
        membre["numero_ordre"] = _norm_numero_ordre(membre.get("numero_ordre")) or None
    return membres


async def charger_releve(db: AsyncSession, organisation_id: int, exercice: str | None, numero_ordre: str) -> tuple[Releve, str]:
    """Le relevé d'un membre, d'après la Base du Tableau. Renvoie aussi l'exercice retenu."""
    numero = _norm_numero_ordre(numero_ordre)
    if not numero:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="N° d'ordre manquant.")
    base = await get_base_tableau(db, [organisation_id], exercice=exercice, recherche=numero, situation="tous")
    exercice = base["exercice"]
    membre = next((m for m in _membres_de_la_base(base) if m["numero_ordre"] == numero), None)
    if membre is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre introuvable dans la Base du Tableau.")
    return _releve_de(membre, await _contexte(db, organisation_id, exercice)), exercice


#: Filtres de la Base repris pour une sélection « tous les membres du filtre » :
#: les noms sont ceux de `get_base_tableau`.
FILTRES_BASE = (
    "recherche", "categorie", "personne", "province", "sexe", "anciennete", "actif", "situation",
    "conclusion", "cotisation", "assurance", "chiffre_affaires", "formation", "anomalie_only",
)


async def releves_selection(
    db: AsyncSession,
    organisation_id: int,
    *,
    exercice: str | None,
    numeros: list[str] | None = None,
    filtres: dict[str, Any] | None = None,
) -> tuple[list[Releve], str]:
    """Les relevés d'une sélection : des n° d'ordre choisis, ou tous les membres d'un filtre.

    La Base n'est consolidée qu'une fois pour toute la sélection.
    """
    if numeros is not None:
        voulus = list(dict.fromkeys(n for n in (_norm_numero_ordre(x) for x in numeros) if n))
        base = await get_base_tableau(db, [organisation_id], exercice=exercice, situation="tous")
        # Le premier l'emporte (le dossier avant la ligne sans dossier), comme
        # `charger_releve` et la sélection par filtre : le lot envoie ce que l'aperçu montre.
        par_numero: dict[str, dict[str, Any]] = {}
        for m in _membres_de_la_base(base):
            if m["numero_ordre"]:
                par_numero.setdefault(m["numero_ordre"], m)
        membres = [par_numero[n] for n in voulus if n in par_numero]
    else:
        criteres = {k: v for k, v in (filtres or {}).items() if k in FILTRES_BASE and v not in (None, "")}
        base = await get_base_tableau(db, [organisation_id], exercice=exercice, **criteres)
        vus: set[str] = set()
        membres = []
        for membre in _membres_de_la_base(base):
            cle = membre["numero_ordre"] or f"sans-numero-{len(membres)}"
            if cle not in vus:
                vus.add(cle)
                membres.append(membre)
    exercice = base["exercice"]
    if not membres:
        return [], exercice
    ctx = await _contexte(db, organisation_id, exercice)
    return [_releve_de(m, ctx) for m in membres], exercice


# ── Journal ─────────────────────────────────────────────────────────────────


async def envois_du_membre(db: AsyncSession, organisation_id: int, exercice: str, numero: str) -> list[TableauReleve]:
    return list((await db.execute(
        select(TableauReleve)
        .options(defer(TableauReleve.corps))
        .where(
            TableauReleve.organisation_id == organisation_id,
            TableauReleve.exercice == exercice,
            TableauReleve.numero_ordre == numero,
        )
        .order_by(TableauReleve.created_at.desc(), TableauReleve.id.desc())
    )).scalars().all())


@dataclass(frozen=True)
class _Envoi:
    """Ce que la garde anti-doublon lit d'un relevé parti.

    Une copie, pas l'objet ORM : un lot annule la transaction d'un membre en
    échec, ce qui expirerait des objets ORM gardés en mémoire pour tout le lot.
    """

    canal: str
    empreinte: str
    statut: str
    created_at: datetime


async def _envoyes(db: AsyncSession, organisation_id: int, exercice: str, *colonnes: Any) -> list[Any]:
    """Les relevés partis de l'exercice, du plus récent au plus ancien, réduits aux colonnes voulues."""
    return list((await db.execute(
        select(TableauReleve.numero_ordre, TableauReleve.canal, TableauReleve.created_at, *colonnes)
        .where(
            TableauReleve.organisation_id == organisation_id,
            TableauReleve.exercice == exercice,
            TableauReleve.statut == "envoye",
        )
        .order_by(TableauReleve.created_at.desc())
    )).all())


async def _envois_de_l_exercice(db: AsyncSession, organisation_id: int, exercice: str) -> dict[str, list[_Envoi]]:
    """Tous les relevés partis de l'exercice, par n° d'ordre : la garde anti-doublon d'un lot."""
    out: dict[str, list[_Envoi]] = {}
    for numero, canal, quand, empreinte in await _envoyes(db, organisation_id, exercice, TableauReleve.empreinte):
        out.setdefault(numero, []).append(_Envoi(canal=canal, empreinte=empreinte, statut="envoye", created_at=quand))
    return out


async def derniers_envois(db: AsyncSession, organisation_id: int, exercice: str) -> dict[str, dict[str, Any]]:
    """Pour chaque N° d'ordre : le dernier relevé parti et ses canaux."""
    out: dict[str, dict[str, Any]] = {}
    for numero, canal, quand in await _envoyes(db, organisation_id, exercice):
        item = out.setdefault(numero, {"date": quand, "canaux": []})
        if canal not in item["canaux"]:
            item["canaux"].append(canal)
    return out


def _deja_envoye(envois: list[TableauReleve] | list[_Envoi], empreinte: str) -> dict[str, datetime]:
    """Canaux sur lesquels cette même situation est déjà partie, avec la date."""
    out: dict[str, datetime] = {}
    for envoi in envois:
        if envoi.statut == "envoye" and envoi.empreinte == empreinte and envoi.canal not in out:
            out[envoi.canal] = envoi.created_at
    return out


@dataclass
class Moyens:
    """Les canaux du conseil, lus une fois : SMTP et WhatsApp."""

    smtp: SMTPConfig | None
    whatsapp: WhatsAppSettings
    # Fabrique de sessions de la remise WhatsApp ; None : celle de l'application.
    session_factory: Any = None


async def _moyens(db: AsyncSession, organisation_id: int, organisation: str, session_factory: Any = None) -> Moyens:
    return Moyens(
        smtp=resolve_smtp_config(await get_system_settings(db, organisation_id)),
        whatsapp=await load_whatsapp_settings(db, organisation_id, organisation),
        session_factory=session_factory,
    )


async def apercu(db: AsyncSession, organisation_id: int, exercice: str | None, numero_ordre: str) -> dict[str, Any]:
    releve, exercice = await charger_releve(db, organisation_id, exercice, numero_ordre)
    envois = await envois_du_membre(db, organisation_id, exercice, releve.numero_ordre)
    moyens = await _moyens(db, organisation_id, "")
    return {
        "exercice": exercice,
        "numero_ordre": releve.numero_ordre,
        "nom": releve.nom,
        "categorie": releve.categorie,
        "envoyable": releve.envoyable,
        "raison": releve.raison,
        "sujet": releve.sujet,
        "corps": releve.corps,
        "emails": releve.emails,
        "telephone": releve.telephone,
        "fonction_bureau": releve.fonction_bureau,
        "email_actif": moyens.smtp is not None,
        "whatsapp_actif": bool(moyens.whatsapp.enabled),
        "deja_envoye": _deja_envoye(envois, releve.empreinte) if releve.envoyable else {},
        "historique": [
            {"date": e.created_at, "canal": e.canal, "destinataire": e.destinataire, "statut": e.statut,
             "conclusion": e.conclusion, "erreur": e.erreur}
            for e in envois[:10]
        ],
    }


# ── Envoi ───────────────────────────────────────────────────────────────────


def _canaux_connus(canaux: list[str] | None) -> list[str]:
    """Les canaux demandés que l'on sait servir, dans l'ordre de CANAUX."""
    demandes = set(canaux or [])
    return [c for c in CANAUX if c in demandes]


def _voies(canaux: list[str]) -> list[str]:
    voies = _canaux_connus(canaux)
    if not voies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choisissez l'e-mail, WhatsApp, ou les deux.")
    return voies


async def _envoyer_releve(
    db: AsyncSession,
    releve: Releve,
    voies: list[str],
    *,
    deja: dict[str, datetime],
    renvoyer: bool,
    moyens: Moyens,
    organisation_id: int,
    exercice: str,
    user_id: Any,
    lot_id: int | None = None,
) -> tuple[list[dict[str, Any]], list[TableauReleve]]:
    """Envoie le relevé sur chaque canal demandé. Rien n'est ajouté à la session : l'appelant consigne."""
    resultats: list[dict[str, Any]] = []
    journal: list[TableauReleve] = []

    def consigner(canal: str, destinataire: str, statut: str, erreur: str | None = None, corps: str | None = None) -> None:
        # `corps` : le texte réellement remis sur ce canal ; à défaut, celui de l'e-mail.
        journal.append(TableauReleve(
            organisation_id=organisation_id, exercice=exercice, numero_ordre=releve.numero_ordre,
            nom=releve.nom[:300], categorie=releve.categorie, conclusion=(releve.conclusion or "")[:30],
            canal=canal, destinataire=destinataire[:255], sujet=releve.sujet[:300], corps=corps or releve.corps,
            empreinte=releve.empreinte, statut=statut, erreur=erreur, envoye_par=user_id, lot_id=lot_id,
        ))
        resultats.append({"canal": canal, "destinataire": destinataire, "statut": statut, "message": erreur})

    def ignorer(canal: str, message: str, destinataire: str = "") -> None:
        resultats.append({"canal": canal, "destinataire": destinataire, "statut": "ignore", "message": message})

    for canal in voies:
        if canal in deja and not renvoyer:
            resultats.append({
                "canal": canal, "destinataire": "", "statut": "deja_envoye",
                "message": f"Situation inchangée, déjà envoyée le {deja[canal].strftime('%d/%m/%Y')}.",
            })
            continue

        if canal == "email":
            if not releve.emails:
                ignorer(canal, "Pas d'adresse e-mail au dossier.")
                continue
            destinataire = ", ".join(releve.emails)
            if moyens.smtp is None:
                ignorer(canal, "L'envoi d'e-mails n'est pas configuré (paramètres SMTP).", destinataire)
                continue
            try:
                await send_in_thread(
                    send_releve_situation_email,
                    smtp_host=moyens.smtp.host, smtp_port=moyens.smtp.port, smtp_user=moyens.smtp.user,
                    smtp_password=moyens.smtp.password, sender=moyens.smtp.sender, to_emails=releve.emails,
                    subject=releve.sujet, texte=releve.corps,
                    html_body=html_releve(releve),
                )
                consigner(canal, destinataire, "envoye")
            except Exception as exc:  # noqa: BLE001 — l'échec est consigné et rapporté
                logger.exception("tableau.releve.email_failed numero=%s", releve.numero_ordre)
                consigner(canal, destinataire, "echec", str(exc) or exc.__class__.__name__)

        elif canal == "whatsapp":
            if not releve.telephone:
                ignorer(canal, "Pas de numéro de téléphone exploitable.")
                continue
            if not moyens.whatsapp.enabled:
                ignorer(canal, "Le canal WhatsApp est désactivé.", releve.telephone)
                continue
            # Une erreur ici est consignée sur ce seul canal : elle ne doit pas
            # emporter l'entrée de l'e-mail déjà parti, sans quoi la garde
            # anti-doublon ne le verrait pas et une reprise le renverrait.
            try:
                nonce = uuid.uuid4().hex
                await notify_whatsapp(
                    db, None,
                    organisation_id=organisation_id, event_type=TABLEAU_SITUATION, entity_type=ENTITY_TYPE,
                    entity_id=nonce,
                    recipients=[Recipient(phone=releve.telephone, name=releve.nom, role="Membre")],
                    variables=variables_whatsapp(releve), settings=moyens.whatsapp, nonce=nonce,
                    session_factory=moyens.session_factory,
                )
                logs = (await db.execute(
                    select(NotificationLog)
                    .where(
                        NotificationLog.organisation_id == organisation_id,
                        NotificationLog.entity_type == ENTITY_TYPE,
                        NotificationLog.entity_id == nonce,
                    )
                    .execution_options(populate_existing=True)
                )).scalars().all()
            except Exception as exc:  # noqa: BLE001 — l'échec est consigné et rapporté
                logger.exception("tableau.releve.whatsapp_failed numero=%s", releve.numero_ordre)
                # La transaction est peut-être compromise : on repart propre, le
                # journal n'est pas encore dans la session (l'appelant l'ajoute).
                await db.rollback()
                consigner(canal, releve.telephone, "echec", str(exc) or exc.__class__.__name__)
                continue
            # Le message tel que le gabarit l'a rendu, preuve de ce que le membre a reçu.
            remis = next((log.message for log in logs if log.message), None)
            if logs and all(log.status == STATUS_SENT for log in logs):
                consigner(canal, releve.telephone, "envoye", corps=remis)
            else:
                erreur = next((log.error_message for log in logs if log.error_message), None) or "Envoi non abouti."
                consigner(canal, releve.telephone, "echec", erreur, corps=remis)
    return resultats, journal


async def envoyer(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    *,
    exercice: str | None,
    numero_ordre: str,
    canaux: list[str],
    renvoyer: bool = False,
) -> dict[str, Any]:
    voies = _voies(canaux)
    releve, exercice = await charger_releve(db, organisation_id, exercice, numero_ordre)
    if not releve.envoyable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=releve.raison or "Relevé non envoyable.")

    deja = _deja_envoye(await envois_du_membre(db, organisation_id, exercice, releve.numero_ordre), releve.empreinte)
    moyens = await _moyens(db, organisation_id, releve.organisation)
    resultats, journal = await _envoyer_releve(
        db, releve, voies, deja=deja, renvoyer=renvoyer, moyens=moyens,
        organisation_id=organisation_id, exercice=exercice, user_id=user.id,
    )
    db.add_all(journal)
    if journal:
        await record_tableau_audit(
            db, organisation_id=organisation_id, user_id=user.id, action="RELEVE_SITUATION_ENVOYE",
            target_type="membre", target_id=releve.numero_ordre,
            status="success" if all(j.statut == "envoye" for j in journal) else "partial",
            metadata_json={
                "exercice": exercice, "nom": releve.nom, "conclusion": releve.conclusion,
                "envois": [{"canal": j.canal, "destinataire": j.destinataire, "statut": j.statut} for j in journal],
            },
        )
    await db.commit()
    return {"numero_ordre": releve.numero_ordre, "resultats": resultats}


# ── Envoi en masse ──────────────────────────────────────────────────────────

MAX_LOT = 3000
#: Un lot qui n'a pas avancé depuis ce délai est tenu pour interrompu (redémarrage
#: du serveur) : il peut être repris là où il s'est arrêté.
DELAI_INTERRUPTION_S = 600
#: Respiration entre deux membres, pour ne pas saturer le SMTP ni WhatsApp.
PAUSE_ENTRE_MEMBRES_S = 0.2

LIBELLES_BLOCAGE = {
    "a_deliberer": "À délibérer : la commission n'a pas tranché",
    "sans_conclusion": "Sans conclusion : analyse à lancer",
    "sorti": "Sortis du Tableau",
    "sans_numero": "Sans N° d'ordre",
    "sans_contact": "Ni e-mail ni téléphone",
}


async def preparer_selection(
    db: AsyncSession,
    organisation_id: int,
    *,
    exercice: str | None,
    numeros: list[str] | None,
    filtres: dict[str, Any] | None,
    canaux: list[str],
) -> dict[str, Any]:
    """Ce que donnerait l'envoi : qui le recevra, qui est écarté et pourquoi."""
    releves, exercice = await releves_selection(db, organisation_id, exercice=exercice, numeros=numeros, filtres=filtres)
    voies = _canaux_connus(canaux) or list(CANAUX)
    envoyables = [r for r in releves if r.envoyable]
    bloques = Counter(r.blocage for r in releves if not r.envoyable)
    envois = await _envois_de_l_exercice(db, organisation_id, exercice)
    moyens = await _moyens(db, organisation_id, "")
    par_canal: dict[str, dict[str, int]] = {}
    for canal in voies:
        joignables = [r for r in envoyables if (r.emails if canal == "email" else r.telephone)]
        deja = sum(1 for r in joignables if canal in _deja_envoye(envois.get(r.numero_ordre, []), r.empreinte))
        par_canal[canal] = {"joignables": len(joignables), "deja_envoye": deja}
    exemple = next((r for r in envoyables if not r.en_regle), None) or (envoyables[0] if envoyables else None)
    return {
        "exercice": exercice,
        "total": len(releves),
        "envoyables": len(envoyables),
        "en_regle": sum(1 for r in envoyables if r.en_regle),
        "non_en_regle": sum(1 for r in envoyables if not r.en_regle),
        "bloques": [
            {"code": code, "libelle": LIBELLES_BLOCAGE.get(code, code), "nombre": nombre}
            for code, nombre in bloques.most_common()
        ],
        "par_canal": par_canal,
        "email_actif": moyens.smtp is not None,
        "whatsapp_actif": bool(moyens.whatsapp.enabled),
        "max": MAX_LOT,
        "exemple": {"nom": exemple.nom, "sujet": exemple.sujet, "corps": exemple.corps} if exemple else None,
    }


def _statut_effectif(lot: TableauReleveLot) -> str:
    """Un lot « en cours » qui n'avance plus depuis DELAI_INTERRUPTION_S est interrompu."""
    if lot.statut == "en_cours" and lot.updated_at:
        if (datetime.now(timezone.utc) - lot.updated_at).total_seconds() > DELAI_INTERRUPTION_S:
            return "interrompu"
    return lot.statut


def lot_payload(lot: TableauReleveLot, echecs: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": lot.id,
        "exercice": lot.exercice,
        "canaux": lot.canaux,
        "statut": _statut_effectif(lot),
        "total": lot.total,
        "traites": lot.traites,
        "envoyes": lot.envoyes,
        "echecs": lot.echecs,
        "deja_envoyes": lot.deja_envoyes,
        "ignores": lot.ignores,
        "created_at": lot.created_at,
        "termine_le": lot.termine_le,
        "erreurs": [
            {"numero_ordre": e.numero_ordre, "nom": e.nom, "canal": e.canal, "destinataire": e.destinataire, "erreur": e.erreur}
            for e in (echecs or [])
        ],
    }


async def creer_lot(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    *,
    exercice: str | None,
    numeros: list[str] | None,
    filtres: dict[str, Any] | None,
    canaux: list[str],
    renvoyer: bool,
) -> TableauReleveLot:
    """Enregistre le lot : seuls les membres envoyables y entrent, dans l'ordre de la Base."""
    voies = _voies(canaux)
    releves, exercice = await releves_selection(db, organisation_id, exercice=exercice, numeros=numeros, filtres=filtres)
    cibles = [r.numero_ordre for r in releves if r.envoyable]
    if not cibles:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aucun membre de la sélection ne peut recevoir sa situation.")
    if len(cibles) > MAX_LOT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{len(cibles)} membres : un envoi groupé en compte {MAX_LOT} au plus. Affinez le filtre.",
        )
    lot = TableauReleveLot(
        organisation_id=organisation_id, exercice=exercice, canaux=voies, renvoyer=renvoyer,
        numeros=cibles, total=len(cibles), statut="en_cours", cree_par=user.id,
    )
    db.add(lot)
    await db.flush()
    await record_tableau_audit(
        db, organisation_id=organisation_id, user_id=user.id, action="RELEVES_LOT_LANCE",
        target_type="lot_releves", target_id=lot.id,
        metadata_json={"exercice": exercice, "canaux": voies, "total": len(cibles), "renvoyer": renvoyer,
                       "selection": "numeros" if numeros is not None else "filtre", "filtres": filtres or {}},
    )
    await db.commit()
    await db.refresh(lot)
    return lot


async def lire_lot(db: AsyncSession, organisation_id: int, lot_id: int, *, verrou: bool = False) -> TableauReleveLot:
    requete = (
        select(TableauReleveLot).where(TableauReleveLot.id == lot_id, TableauReleveLot.organisation_id == organisation_id)
        .execution_options(populate_existing=True)
    )
    if verrou:
        requete = requete.with_for_update()
    lot = (await db.execute(requete)).scalar_one_or_none()
    if lot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envoi groupé introuvable.")
    return lot


async def echecs_du_lot(db: AsyncSession, lot: TableauReleveLot, limite: int = 100) -> list[Any]:
    """Les derniers échecs du lot, réduits à ce que le suivi affiche."""
    return list((await db.execute(
        select(TableauReleve.numero_ordre, TableauReleve.nom, TableauReleve.canal, TableauReleve.destinataire, TableauReleve.erreur)
        .where(TableauReleve.lot_id == lot.id, TableauReleve.statut == "echec")
        .order_by(TableauReleve.id.desc())
        .limit(limite)
    )).all())


async def reprendre_lot(db: AsyncSession, organisation_id: int, lot_id: int) -> TableauReleveLot:
    # Verrou : deux « Reprendre » simultanés ne lancent pas deux traitements du
    # même lot (chaque membre recevrait son relevé deux fois). Le second attend,
    # puis lit un lot « en cours » tout juste relancé.
    lot = await lire_lot(db, organisation_id, lot_id, verrou=True)
    if _statut_effectif(lot) != "interrompu":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cet envoi n'est pas interrompu.")
    lot.statut = "en_cours"
    lot.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lot)
    return lot


def _compter_membre(lot: TableauReleveLot, statuts: set[str]) -> None:
    """Un membre compte une fois, sous l'issue la plus grave de ses canaux.

    Un échec sur un canal compte en échec, même si l'autre est parti : le bilan
    ne dit pas « succès » quand un canal tombe. Un nouvel envoi à ce membre ne
    repartira que sur le canal manqué.
    """
    if "echec" in statuts:
        lot.echecs += 1
    elif "envoye" in statuts:
        lot.envoyes += 1
    elif "deja_envoye" in statuts:
        lot.deja_envoyes += 1
    else:
        lot.ignores += 1


async def traiter_lot(lot_id: int, organisation_id: int, session_factory=None) -> None:
    """Envoie le lot membre par membre, en arrière-plan. Chaque membre est validé à part :
    un arrêt en cours de route laisse un lot qui se reprend là où il s'est arrêté."""
    from app.core.tenant_context import get_current_tenant_id, set_current_tenant_id

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    # Une tâche de fond n'hérite pas du contexte tenant de la requête.
    precedent = get_current_tenant_id()
    set_current_tenant_id(organisation_id)
    try:
        async with session_factory() as db:
            lot = await lire_lot(db, organisation_id, lot_id)
            try:
                numeros = list(lot.numeros)
                releves, _ = await releves_selection(db, organisation_id, exercice=lot.exercice, numeros=numeros)
                par_numero = {r.numero_ordre: r for r in releves}
                envois = await _envois_de_l_exercice(db, organisation_id, lot.exercice)
                # Seul un relevé envoyable part, et il porte toujours l'organisation.
                organisation = next((r.organisation for r in releves if r.organisation), "")
                moyens = await _moyens(db, organisation_id, organisation, session_factory)
                voies = _canaux_connus(lot.canaux)
                for index in range(lot.traites, len(numeros)):
                    releve = par_numero.get(numeros[index])
                    if releve is None or not releve.envoyable:
                        # La situation a changé depuis le lancement (sortie, délibération…).
                        lot.ignores += 1
                    else:
                        try:
                            deja = _deja_envoye(envois.get(releve.numero_ordre, []), releve.empreinte)
                            resultats, journal = await _envoyer_releve(
                                db, releve, voies, deja=deja, renvoyer=lot.renvoyer, moyens=moyens,
                                organisation_id=organisation_id, exercice=lot.exercice, user_id=lot.cree_par, lot_id=lot.id,
                            )
                            db.add_all(journal)
                        except Exception:  # noqa: BLE001 — un membre en échec n'arrête pas le lot
                            logger.exception("tableau.releve.lot_membre_failed lot=%s numero=%s", lot_id, numeros[index])
                            # La transaction du membre est perdue ; le lot est relu
                            # (ses compteurs sont validés à chaque membre).
                            await db.rollback()
                            lot = await lire_lot(db, organisation_id, lot_id)
                            resultats = [{"statut": "echec"}]
                        if sa_inspect(lot).expired_attributes:
                            # La file WhatsApp annule sa propre transaction quand son
                            # commit échoue : le lot, expiré, est relu avant d'être compté.
                            lot = await lire_lot(db, organisation_id, lot_id)
                        _compter_membre(lot, {r["statut"] for r in resultats})
                    lot.traites = index + 1
                    lot.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    if PAUSE_ENTRE_MEMBRES_S:
                        await asyncio.sleep(PAUSE_ENTRE_MEMBRES_S)
                lot.statut = "termine"
                lot.termine_le = datetime.now(timezone.utc)
                lot.updated_at = lot.termine_le
                await record_tableau_audit(
                    db, organisation_id=organisation_id, user_id=lot.cree_par, action="RELEVES_LOT_TERMINE",
                    target_type="lot_releves", target_id=lot.id,
                    status="success" if not lot.echecs else "partial",
                    metadata_json={"envoyes": lot.envoyes, "echecs": lot.echecs,
                                   "deja_envoyes": lot.deja_envoyes, "ignores": lot.ignores},
                )
                await db.commit()
            except Exception:
                logger.exception("tableau.releve.lot_failed lot=%s", lot_id)
                await db.rollback()
                lot = await lire_lot(db, organisation_id, lot_id)
                lot.statut = "interrompu"
                await db.commit()
    finally:
        set_current_tenant_id(precedent)
