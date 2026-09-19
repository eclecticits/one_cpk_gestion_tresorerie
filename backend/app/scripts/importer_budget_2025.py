"""Reprend les prévisions du budget 2025 du CPK, rangées dans la nomenclature 2026.

Source : « 04112025 EXECUTION BUDGET ONEC CPK 2025 VF v171025 2200_Edition VF.xlsx »
(onglets « 2. Exécution_Recettes_2025 » et « 3. Exécution_dépenses 2025 »).

La comparaison « Budget N-1 » de l'écran Budget rapproche les deux exercices PAR
CODE. Or le classeur 2025 ne code presque aucune ligne de détail, et les rares
codes qu'il porte ont changé de sens : son II.2.10.1 (rencontres
internationales) est l'Impression pins de 2026. Importer le fichier tel quel
comparerait des choses sans rapport, et rien ne le signalerait.

Chaque ligne 2025 reçoit donc le code de son équivalent 2026, choisi pour son
SENS, en gardant son libellé et son montant 2025 :
- une ligne 2025 qui en couvre plusieurs en 2026 (EC PP, ventilé depuis en
  cabinet / indépendant / salariés) prend un code à part (`.0`) sous son
  chapitre : le chapitre se compare exactement, le détail 2026 affiche « — »
  plutôt qu'une ventilation inventée ;
- une ligne disparue en 2026 (toutes à 0) prend un code libre du chapitre ;
- l'ancien chapitre « AUTRES » (II.2.10) retrouve ses lignes là où 2026 les a
  rangées : II.2.10, II.2.12 (honoraires) et II.2.13 (voyages, représentations).

Prévisions seules : ni engagé ni payé. L'exercice est créé « Clôturé », pour
qu'aucune opération ne puisse y être imputée.

Les totaux sont vérifiés contre ceux du fichier AVANT toute écriture.

Lecture seule par défaut :
  docker compose exec backend python -m app.scripts.importer_budget_2025 --org cpk
  docker compose exec backend python -m app.scripts.importer_budget_2025 --org cpk --execute
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.organisation import Organisation

ANNEE = 2025

#: Totaux du fichier source : les lignes importées doivent y retomber au centime.
TOTAL_RECETTES_FICHIER = Decimal("540352.00")
TOTAL_DEPENSES_FICHIER = Decimal("567233.29")

# (code 2026, code parent, libellé 2025, montant 2025, remarque)
# Un montant `None` désigne un chapitre : il vaut la somme de ses lignes.
RECETTES: list[tuple[str, str | None, str, Decimal | None, str]] = [
    ("I", None, "RECETTES", None, ""),
    ("I.0", "I", "Report 2024", Decimal("170213"), "Hors calculs, comme le report de 2026"),
    ("I.1", "I", "EMPRUNTS", None, ""),
    ("I.1.1", "I.1", "Emprunt auprès des IF", Decimal("0"), ""),
    ("I.1.2", "I.1", "Emprunt auprès des autres organismes", Decimal("0"), ""),
    ("I.2", "I", "SUBSIDES", None, ""),
    ("I.2.1", "I.2", "Etat", Decimal("0"), ""),
    ("I.2.2", "I.2", "Autres organismes", Decimal("0"), ""),
    ("I.3", "I", "COTISATION ANNUELLE", None, ""),
    ("I.3.0", "I.3", "EC PP (non ventilé en 2025 : en cabinet, indépendant, salariés)", Decimal("162180"),
     "Une ligne en 2025, trois en 2026 (I.3.1 à I.3.3) : comparée au niveau du chapitre"),
    ("I.3.4", "I.3", "Arriérés de Cotisation EC 2020-2023 (et 2024)", Decimal("9000"),
     "Fusion des deux lignes d'arriérés 2025 ; celle de 2024 était vide"),
    ("I.3.5", "I.3", "Sociétés d'Experts-Comptables", Decimal("122287"), ""),
    ("I.3.6", "I.3", "Suppléments du CA", Decimal("123385"), ""),
    ("I.3.7", "I.3", "Sociétés d'Experts-Comptables nouvellement inscrit", Decimal("10200"), ""),
    ("I.3.8", "I.3", "Stagiaires", Decimal("0"), ""),
    ("I.4", "I", "AGREMENTS & PRODUITS CONNEXES", None, ""),
    ("I.4.1", "I.4", "Inscription au tableau des Experts-Comptables", Decimal("0"),
     "Rapprochée de « Frais de dossier candidats à insc direct » (2026)"),
    ("I.4.2", "I.4", "Inscription au tableau des Sociétés d'Experts-Comptables", Decimal("24000"), ""),
    ("I.4.3", "I.4", "Frais Prestation de serment EC (quote-part)", Decimal("0"), "Sans équivalent en 2026"),
    ("I.4.4", "I.4", "Cartes de membre (quote-part)", Decimal("0"), "Sans équivalent en 2026"),
    ("I.5", "I", "STAGE ET PARTICIPATION AUX EXAMENS", None, ""),
    ("I.5.1", "I.5", "Dépôt de dossier des impétrants", Decimal("0"), ""),
    ("I.5.2", "I.5", "Admission / Stage (inscription aux examens)", Decimal("0"), ""),
    ("I.5.3", "I.5", "Sessions / Stage", Decimal("0"), ""),
    ("I.5.4", "I.5", "Examen d'aptitude professionnelle (Jury / Stage)", Decimal("0"), ""),
    ("I.5.5", "I.5", "Admission à l'Ordre / PP étrangère", Decimal("0"), ""),
    ("I.6", "I", "FORMATIONS", None, ""),
    ("I.6.1", "I.6", "Organisation Formations, séminaires, conférence etc.", Decimal("86000"), ""),
    ("I.7", "I", "AUTRES PRODUITS", None, ""),
    ("I.7.1", "I.7", "Produits de vente de brochures (Annuaires, pins, fanion, etc.)", Decimal("1000"), ""),
    ("I.7.2", "I.7", "Contribution du Conseil National aux loyers", Decimal("0"), ""),
    ("I.7.3", "I.7", "Location Espace bureau", Decimal("800"), ""),
    ("I.7.4", "I.7", "Pénalité pour absence aux assemblées générales", Decimal("1000"), ""),
    ("I.7.5", "I.7", "Pourcentage vente ouvrage pour tiers", Decimal("500"), ""),
    ("I.7.6", "I.7", "Retour caisse et banque", Decimal("0"), "Sans équivalent en 2026"),
    ("I.7.7", "I.7", "Remboursement CN", Decimal("0"), "Sans équivalent en 2026"),
]

DEPENSES: list[tuple[str, str | None, str, Decimal | None, str]] = [
    ("II", None, "DEPENSES", None, ""),
    ("II.1", "II", "DEPENSES D'INVESTISSEMENT", None, ""),
    ("II.1.1", "II.1", "Acquisition des ouvrages disponibles pour les EC", Decimal("10000"), ""),
    ("II.1.2", "II.1", "Acquisition Matériels & Mobiliers de bureau, matériels informatiques et autres",
     Decimal("5000"), ""),
    ("II.1.4", "II.1", "Cloisonnement Bureau", Decimal("0"), "Sans équivalent en 2026"),
    ("II.2", "II", "DEPENSES DE FONCTIONNEMENT", None, ""),
    ("II.2.1", "II.2", "COTISATION ANNUELLE AU CN (PER CAPITA)", None, ""),
    ("II.2.1.0", "II.2.1", "EC-PP (non ventilé en 2025 : en cabinet, indépendant, salariés)", Decimal("54060"),
     "Une ligne en 2025, trois en 2026 (II.2.1.1 à II.2.1.3) : comparée au niveau du chapitre"),
    ("II.2.1.4", "II.2.1", "Arriérés de Cotisation EC (2020,2021,2022 & 2023)", Decimal("3000"), ""),
    ("II.2.1.5", "II.2.1", "Sociétés d'Experts-Comptables", Decimal("81891"),
     "81 890,99999 dans le fichier ; « commit » saisi par erreur dans la colonne des codes"),
    ("II.2.1.6", "II.2.1", "Supplément CA", Decimal("0"), ""),
    ("II.2.1.7", "II.2.1", "Sociétés d'Experts-Comptables nouvellement inscrit", Decimal("3400"), ""),
    ("II.2.1.8", "II.2.1", "Stagiaires", Decimal("0"), ""),
    ("II.2.1.9", "II.2.1", "Frais d'inscription de SEC", Decimal("8000"), ""),
    ("II.2.1.10", "II.2.1", "Reversement vente carte", Decimal("0"), "Sans équivalent en 2026"),
    ("II.2.2", "II.2", "ASSEMBLEES PROVINCIALES (2 AP)", None, ""),
    ("II.2.2.1", "II.2.2", "Location salle", Decimal("5000"), ""),
    ("II.2.2.2", "II.2.2", "Déjeuner + Pause-café", Decimal("18000"), ""),
    ("II.2.2.3", "II.2.2", "Presse", Decimal("1650"), ""),
    ("II.2.2.4", "II.2.2", "Fournitures et autres", Decimal("1500"), ""),
    ("II.2.2.5", "II.2.2", "Protocole", Decimal("1000"), ""),
    ("II.2.2.6", "II.2.2", "Enseignes (Bâches, Badges, Roll up)", Decimal("1500"), ""),
    ("II.2.2.7", "II.2.2", "Autres", Decimal("1350"), ""),
    ("II.2.3", "II.2", "ORGANISATION DU STAGE", None, ""),
    ("II.2.3.1", "II.2.3",
     "Organisation Examens de stage (honoraires prof, motivation surveillants, impression questionnaires, "
     "location salle & frais connexes)", Decimal("20280"), ""),
    ("II.2.3.2", "II.2.3", "Inscription directe des EC au tableau", Decimal("0"),
     "Rangée sous II.2.1 en 2025, sous II.2.3 en 2026"),
    ("II.2.3.3", "II.2.3",
     "Organisation de portes ouvertes + Tenue des Conférences débats dans les Universités, Instituts "
     "supérieurs et autres Institutions publiques, privées et partenaires institutionnels",
     Decimal("15680"), ""),
    ("II.2.3.4", "II.2.3", "Suivi évolution stagiaires", Decimal("4500"), ""),
    ("II.2.4", "II.2", "JOURNEE ACADEMIQUES. SEMINAIRES, (FORMATION)", None, ""),
    ("II.2.4.1", "II.2.4", "Organisation Formation, séminaires, Conférences etc.", Decimal("51100"), ""),
    ("II.2.5", "II.2", "REUNIONS AU CONSEIL PROVINCIAL", None, ""),
    ("II.2.5.1", "II.2.5", "Réunions du Bureau (12 réunions)", Decimal("7200"), ""),
    ("II.2.5.2", "II.2.5", "Réunions du Conseil (12 réunions)", Decimal("18000"), ""),
    ("II.2.5.3", "II.2.5", "Réunions des Commissions Provinciales Permanentes (CPP) (min 12 réunions)",
     Decimal("24000"), ""),
    ("II.2.5.4", "II.2.5", "Commissions Ad hoc", Decimal("0"), ""),
    ("II.2.5.5", "II.2.5", "Autres", Decimal("2880"), "« Autres invités » en 2026"),
    ("II.2.6", "II.2", "LOYERS & CHARGES LOCATIVES", None, ""),
    ("II.2.6.1", "II.2.6", "Loyers bureau CPK", Decimal("43790.40"), ""),
    ("II.2.6.2", "II.2.6", "Loyers espace de travail + bibliothèque", Decimal("0"), ""),
    ("II.2.6.3", "II.2.6", "Charges locatives (retenue locative)", Decimal("7862.40"), ""),
    ("II.2.6.4", "II.2.6", "Autres charges (Electricité, eau, carburant générateur, etc.)", Decimal("0"), ""),
    ("II.2.7", "II.2", "TRANSPORT & COMMUNICATION", None, ""),
    ("II.2.7.1", "II.2.7", "Courses pour compte du CPK", Decimal("1500"), ""),
    ("II.2.7.2", "II.2.7", "Frais de communication", Decimal("8000"), ""),
    ("II.2.7.3", "II.2.7", "Abonnement internet", Decimal("2400"), ""),
    ("II.2.8", "II.2", "ASSISTANCE SOCIALE", None, ""),
    ("II.2.8.1", "II.2.8", "Aides en cas de décès d'EC ou conjoint(e)", Decimal("4500"), ""),
    ("II.2.9", "II.2", "CHARGES DU PERSONNEL", None, ""),
    ("II.2.9.1", "II.2.9", "Salaires Personnel d'appoint", Decimal("44700"), ""),
    ("II.2.9.2", "II.2.9", "Charges sociales et fiscales", Decimal("6000"), ""),
    # L'ancien chapitre « AUTRES » (82 472,49) est réparti comme 2026 l'a fait.
    ("II.2.10", "II.2", "AUTRES", None, "Ancien II.2.10 réparti entre II.2.10, II.2.12 et II.2.13"),
    ("II.2.10.1", "II.2.10", "Impression pins, fanions et autres", Decimal("1000"), "Ancien II.2.10.6"),
    ("II.2.10.2", "II.2.10", "Fournitures & consommables de Bureau", Decimal("3500"), "Ancien II.2.10.7"),
    ("II.2.10.3", "II.2.10",
     "Petite collation (sucre, thé, café, lait, jus, eau, etc.)+casse croute pendant les réunions",
     Decimal("3500"), "Ancien II.2.10.8"),
    ("II.2.10.4", "II.2.10", "Produits d'entretien et de nettoyage", Decimal("1500"), "Ancien II.2.10.9"),
    ("II.2.10.5", "II.2.10", "Frais bancaires et autres", Decimal("2500"), "Ancien II.2.10.10"),
    ("II.2.10.6", "II.2.10", "Petites réparations", Decimal("1000"), "Ancien II.2.10.11"),
    ("II.2.10.7", "II.2.10", "Petits matériels", Decimal("1000"), "Ancien II.2.10.12"),
    ("II.2.10.8", "II.2.10", "Carburant véhicule", Decimal("0"), "Ancien II.2.10.13"),
    ("II.2.10.9", "II.2.10", "Entretien Véhicule", Decimal("0"), "Ancien II.2.10.14"),
    ("II.2.11", "II.2", "Imprévus", Decimal("27017"), "27 017,000000000004 dans le fichier"),
    ("II.2.12", "II.2", "HONORAIRES & AUTRES PRESTATIONS EXTERIEURES", None, "Chapitre créé en 2026"),
    ("II.2.12.1", "II.2.12", "Honoraires CAC et autres prestations extérieures", Decimal("5000"),
     "Ancien II.2.10.5"),
    ("II.2.13", "II.2", "VOYAGES, REPRESENTATIONS & AUTRES FRAIS ASSIMILES", None, "Chapitre créé en 2026"),
    ("II.2.13.1", "II.2.13", "Participation aux rencontres internationales (PAFA, FIDEF, OEC France, etc.)",
     Decimal("10000"), "Ancien II.2.10.1"),
    ("II.2.13.2", "II.2.13", "Frais de représentation des invités aux organisations de l'Ordre",
     Decimal("10000"), "Ancien II.2.10.2"),
    ("II.2.13.3", "II.2.13", "Participations aux Organisations Nationales", Decimal("5000"), "Ancien II.2.10.3"),
    ("II.2.13.4", "II.2.13", "Participations aux Assemblées générales (Conseil national)",
     Decimal("38472.49"), "Ancien II.2.10.4 ; 38 472,489… dans le fichier"),
]

#: Hors calculs, comme le report de l'exercice suivant.
HORS_CALCULS = {"I.0"}


def montants(lignes) -> dict[str, Decimal]:
    """Montant de chaque code, chapitres compris (somme de leurs lignes)."""
    enfants: dict[str | None, list[str]] = {}
    brut: dict[str, Decimal | None] = {}
    for code, parent, _, montant, _ in lignes:
        enfants.setdefault(parent, []).append(code)
        brut[code] = montant

    resultat: dict[str, Decimal] = {}

    def total(code: str) -> Decimal:
        if code in resultat:
            return resultat[code]
        valeur = brut[code]
        if valeur is None:
            valeur = sum(
                (total(e) for e in enfants.get(code, []) if e not in HORS_CALCULS), Decimal("0")
            )
        resultat[code] = valeur
        return valeur

    for code in brut:
        total(code)
    return resultat


def verifier() -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    rec, dep = montants(RECETTES), montants(DEPENSES)
    if rec["I"] != TOTAL_RECETTES_FICHIER:
        raise SystemExit(f"Recettes : {rec['I']} au lieu de {TOTAL_RECETTES_FICHIER} (fichier).")
    if dep["II"] != TOTAL_DEPENSES_FICHIER:
        raise SystemExit(f"Dépenses : {dep['II']} au lieu de {TOTAL_DEPENSES_FICHIER} (fichier).")
    return rec, dep


async def importer(slug: str, execute: bool) -> None:
    rec, dep = verifier()
    print(f"Totaux conformes au fichier : recettes {rec['I']}, dépenses {dep['II']}.")

    async with SessionLocal() as db:
        db.info["skip_tenant_scope"] = True
        org = (await db.execute(select(Organisation).where(Organisation.slug == slug))).scalar_one()
        existant = (
            await db.execute(
                select(BudgetExercice).where(
                    BudgetExercice.organisation_id == org.id, BudgetExercice.annee == ANNEE
                )
            )
        ).scalar_one_or_none()
        if existant is not None:
            postes = (
                await db.execute(
                    select(BudgetPoste.id).where(
                        BudgetPoste.exercice_id == existant.id, BudgetPoste.is_deleted.is_(False)
                    ).limit(1)
                )
            ).first()
            if postes is not None:
                raise SystemExit(
                    f"L'exercice {ANNEE} de {slug} a déjà des postes : rien n'est écrasé."
                )
            exercice = existant
        else:
            exercice = BudgetExercice(annee=ANNEE, statut=StatutBudget.CLOTURE, organisation_id=org.id)
            db.add(exercice)
            await db.flush()
        exercice.statut = StatutBudget.CLOTURE

        par_code: dict[str, BudgetPoste] = {}
        for type_, lignes, totaux in (("RECETTE", RECETTES, rec), ("DEPENSE", DEPENSES, dep)):
            for code, parent, libelle, _, _ in lignes:
                poste = BudgetPoste(
                    organisation_id=org.id,
                    exercice_id=exercice.id,
                    code=code,
                    libelle=libelle,
                    parent_code=parent,
                    parent_id=par_code[parent].id if parent else None,
                    type=type_,
                    montant_prevu=totaux[code],
                    montant_engage=0,
                    montant_paye=0,
                    inclure_dans_calculs=code not in HORS_CALCULS,
                    active=True,
                    is_deleted=False,
                )
                db.add(poste)
                await db.flush()
                par_code[code] = poste

        print(f"{org.nom} : exercice {ANNEE} « Clôturé », {len(par_code)} postes.")
        if execute:
            await db.commit()
            print("Écrit.")
        else:
            await db.rollback()
            print("[lecture seule] rien n'est écrit. --execute pour écrire.")


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--org", default="cpk", help="slug de l'organisation (défaut : cpk)")
    parseur.add_argument("--execute", action="store_true")
    args = parseur.parse_args()
    asyncio.run(importer(args.org, args.execute))


if __name__ == "__main__":
    main()
