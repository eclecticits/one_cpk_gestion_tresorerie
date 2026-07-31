"""Plans comptables par défaut : SYSCOHADA révisé et SYSCEBNL.

⚠️ Portée assumée : ceci est un **socle de démarrage** (comptes de base,
largement utilisés, numérotation officielle OHADA pour les postes retenus) —
PAS la codification exhaustive des ~300 comptes du plan complet. Avant mise en
production, un comptable qualifié doit compléter/valider le plan pour le
périmètre réel de l'organisation. Aucune écriture ne doit s'appuyer sur un
compte non revu par un humain (cf. dossier d'architecture, §6 — frontière IA).

Principe : chargement EXPLICITE (fonction appelée par un service de
provisioning), jamais un hook automatique — cf. contrainte C4 du dossier
d'architecture (le clonage inter-tenant ne doit pas générer de plan fantôme).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import ComptaCompte, ComptaReferentiel


@dataclass(frozen=True)
class CompteSeed:
    numero: str
    libelle: str
    nature: str  # ACTIF | PASSIF | CHARGE | PRODUIT | ENGAGEMENT
    sens_normal: str  # DEBIT | CREDIT
    is_collectif: bool = False
    is_auxiliaire: bool = False
    parent_numero: str | None = None
    classe: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "classe", self.numero[0])


# ── SYSCOHADA révisé — socle de démarrage ────────────────────────────────────
# Numérotation officielle pour les postes listés ; le reste du plan complet
# (jusqu'à la classe 9, comptabilité analytique/engagement) reste à compléter
# selon l'activité réelle de l'organisation.
SYSCOHADA_SEED: list[CompteSeed] = [
    # Classe 1 — Ressources durables
    CompteSeed("10", "Capital", "PASSIF", "CREDIT"),
    CompteSeed("101", "Capital social", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("106", "Réserves", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("110", "Report à nouveau (solde créditeur)", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("119", "Report à nouveau (solde débiteur)", "ACTIF", "DEBIT", parent_numero="10"),
    CompteSeed("12", "Résultat net de l'exercice", "PASSIF", "CREDIT"),
    CompteSeed("120", "Résultat net — bénéfice", "PASSIF", "CREDIT", parent_numero="12"),
    CompteSeed("129", "Résultat net — perte", "ACTIF", "DEBIT", parent_numero="12"),
    CompteSeed("16", "Emprunts et dettes assimilées", "PASSIF", "CREDIT"),
    CompteSeed("162", "Emprunts auprès des établissements de crédit", "PASSIF", "CREDIT", parent_numero="16"),
    CompteSeed("168", "Autres emprunts et dettes assimilées", "PASSIF", "CREDIT", parent_numero="16"),
    # Classe 2 — Immobilisations
    CompteSeed("21", "Immobilisations incorporelles", "ACTIF", "DEBIT"),
    CompteSeed("213", "Logiciels", "ACTIF", "DEBIT", parent_numero="21"),
    CompteSeed("22", "Terrains", "ACTIF", "DEBIT"),
    CompteSeed("23", "Bâtiments, installations techniques", "ACTIF", "DEBIT"),
    CompteSeed("24", "Matériel", "ACTIF", "DEBIT"),
    CompteSeed("2182", "Matériel de transport", "ACTIF", "DEBIT", parent_numero="24"),
    CompteSeed("2183", "Matériel informatique", "ACTIF", "DEBIT", parent_numero="24"),
    CompteSeed("2184", "Mobilier et matériel de bureau", "ACTIF", "DEBIT", parent_numero="24"),
    CompteSeed("28", "Amortissements des immobilisations", "ACTIF", "CREDIT"),
    CompteSeed("2813", "Amortissements des logiciels", "ACTIF", "CREDIT", parent_numero="28"),
    CompteSeed("2818", "Amortissements des autres immobilisations corporelles", "ACTIF", "CREDIT", parent_numero="28"),
    # Classe 4 — Tiers
    CompteSeed("40", "Fournisseurs et comptes rattachés", "PASSIF", "CREDIT", is_collectif=True),
    CompteSeed("401", "Fournisseurs, dettes en compte", "PASSIF", "CREDIT", parent_numero="40", is_collectif=True),
    CompteSeed("408", "Fournisseurs, factures non parvenues", "PASSIF", "CREDIT", parent_numero="40"),
    CompteSeed("41", "Clients et comptes rattachés", "ACTIF", "DEBIT", is_collectif=True),
    CompteSeed("411", "Clients", "ACTIF", "DEBIT", parent_numero="41", is_collectif=True),
    CompteSeed("418", "Clients, produits non encore facturés", "ACTIF", "DEBIT", parent_numero="41"),
    CompteSeed("42", "Personnel", "PASSIF", "CREDIT"),
    CompteSeed("421", "Personnel, rémunérations dues", "PASSIF", "CREDIT", parent_numero="42"),
    CompteSeed("43", "Organismes sociaux", "PASSIF", "CREDIT"),
    CompteSeed("431", "Sécurité sociale (CNSS)", "PASSIF", "CREDIT", parent_numero="43"),
    CompteSeed("44", "État et collectivités publiques", "PASSIF", "CREDIT"),
    CompteSeed("441", "État, impôts sur les bénéfices", "PASSIF", "CREDIT", parent_numero="44"),
    CompteSeed("442", "État, autres impôts et taxes", "PASSIF", "CREDIT", parent_numero="44"),
    CompteSeed("447", "État, impôts retenus à la source", "PASSIF", "CREDIT", parent_numero="44"),
    CompteSeed("46", "Débiteurs et créditeurs divers", "ACTIF", "DEBIT"),
    CompteSeed("47", "Débiteurs et créditeurs divers — régularisations", "ACTIF", "DEBIT"),
    CompteSeed("4713", "Virements de fonds (compte d'attente rapprochement bancaire)", "ACTIF", "DEBIT", parent_numero="47"),
    # Classe 5 — Trésorerie
    CompteSeed("51", "Valeurs à encaisser / Banques", "ACTIF", "DEBIT"),
    CompteSeed("512", "Banques", "ACTIF", "DEBIT", parent_numero="51"),
    CompteSeed("521", "Banques, comptes en devises", "ACTIF", "DEBIT", parent_numero="51"),
    CompteSeed("57", "Caisse", "ACTIF", "DEBIT"),
    CompteSeed("571", "Caisse siège", "ACTIF", "DEBIT", parent_numero="57"),
    # Classe 6 — Charges
    CompteSeed("60", "Achats et variations de stocks", "CHARGE", "DEBIT"),
    CompteSeed("605", "Autres achats", "CHARGE", "DEBIT", parent_numero="60"),
    CompteSeed("61", "Transports", "CHARGE", "DEBIT"),
    CompteSeed("612", "Transports sur ventes / missions", "CHARGE", "DEBIT", parent_numero="61"),
    CompteSeed("62", "Services extérieurs A", "CHARGE", "DEBIT"),
    CompteSeed("6132", "Locations", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("6152", "Entretien et réparations", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("6222", "Rémunérations d'intermédiaires et honoraires", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("625", "Déplacements, missions et réceptions", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("63", "Services extérieurs B", "CHARGE", "DEBIT"),
    CompteSeed("6281", "Frais de télécommunications", "CHARGE", "DEBIT", parent_numero="63"),
    CompteSeed("64", "Impôts et taxes", "CHARGE", "DEBIT"),
    CompteSeed("66", "Charges de personnel", "CHARGE", "DEBIT"),
    CompteSeed("661", "Rémunérations directes versées au personnel", "CHARGE", "DEBIT", parent_numero="66"),
    CompteSeed("664", "Charges sociales", "CHARGE", "DEBIT", parent_numero="66"),
    CompteSeed("68", "Dotations aux amortissements", "CHARGE", "DEBIT"),
    CompteSeed("6811", "Dotations aux amortissements d'exploitation", "CHARGE", "DEBIT", parent_numero="68"),
    # Classe 7 — Produits
    CompteSeed("70", "Ventes", "PRODUIT", "CREDIT"),
    CompteSeed("706", "Services vendus", "PRODUIT", "CREDIT", parent_numero="70"),
    CompteSeed("707", "Produits accessoires", "PRODUIT", "CREDIT", parent_numero="70"),
    CompteSeed("75", "Autres produits", "PRODUIT", "CREDIT"),
    CompteSeed("758", "Produits divers", "PRODUIT", "CREDIT", parent_numero="75"),
    CompteSeed("77", "Revenus financiers", "PRODUIT", "CREDIT"),
    CompteSeed("78", "Reprises d'amortissements et de provisions", "PRODUIT", "CREDIT"),
]

# ── SYSCEBNL (entités à but non lucratif) — socle de démarrage ──────────────
# Structure calquée sur SYSCOHADA (compatibilité voulue par l'OHADA), avec les
# libellés adaptés à un organisme à but non lucratif (fonds associatifs,
# cotisations, subventions) sur les classes 1 et 7.
SYSCEBNL_SEED: list[CompteSeed] = [
    # Classe 1 — Fonds associatifs
    CompteSeed("10", "Fonds associatifs", "PASSIF", "CREDIT"),
    CompteSeed("102", "Fonds associatifs sans droit de reprise", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("106", "Réserves", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("110", "Report à nouveau (solde créditeur)", "PASSIF", "CREDIT", parent_numero="10"),
    CompteSeed("119", "Report à nouveau (solde débiteur)", "ACTIF", "DEBIT", parent_numero="10"),
    CompteSeed("12", "Résultat net de l'exercice", "PASSIF", "CREDIT"),
    CompteSeed("120", "Résultat net — excédent", "PASSIF", "CREDIT", parent_numero="12"),
    CompteSeed("129", "Résultat net — déficit", "ACTIF", "DEBIT", parent_numero="12"),
    CompteSeed("14", "Subventions d'investissement", "PASSIF", "CREDIT"),
    CompteSeed("16", "Emprunts et dettes assimilées", "PASSIF", "CREDIT"),
    CompteSeed("168", "Autres emprunts et dettes assimilées", "PASSIF", "CREDIT", parent_numero="16"),
    # Classe 2 — Immobilisations (identique SYSCOHADA)
    CompteSeed("21", "Immobilisations incorporelles", "ACTIF", "DEBIT"),
    CompteSeed("213", "Logiciels", "ACTIF", "DEBIT", parent_numero="21"),
    CompteSeed("23", "Bâtiments, installations techniques", "ACTIF", "DEBIT"),
    CompteSeed("24", "Matériel", "ACTIF", "DEBIT"),
    CompteSeed("2183", "Matériel informatique", "ACTIF", "DEBIT", parent_numero="24"),
    CompteSeed("2184", "Mobilier et matériel de bureau", "ACTIF", "DEBIT", parent_numero="24"),
    CompteSeed("28", "Amortissements des immobilisations", "ACTIF", "CREDIT"),
    CompteSeed("2818", "Amortissements des autres immobilisations corporelles", "ACTIF", "CREDIT", parent_numero="28"),
    # Classe 4 — Tiers
    CompteSeed("40", "Fournisseurs et comptes rattachés", "PASSIF", "CREDIT", is_collectif=True),
    CompteSeed("401", "Fournisseurs, dettes en compte", "PASSIF", "CREDIT", parent_numero="40", is_collectif=True),
    CompteSeed("41", "Adhérents et comptes rattachés", "ACTIF", "DEBIT", is_collectif=True),
    CompteSeed("411", "Adhérents / cotisants", "ACTIF", "DEBIT", parent_numero="41", is_collectif=True),
    CompteSeed("42", "Personnel", "PASSIF", "CREDIT"),
    CompteSeed("421", "Personnel, rémunérations dues", "PASSIF", "CREDIT", parent_numero="42"),
    CompteSeed("43", "Organismes sociaux", "PASSIF", "CREDIT"),
    CompteSeed("431", "Sécurité sociale (CNSS)", "PASSIF", "CREDIT", parent_numero="43"),
    CompteSeed("44", "État et collectivités publiques", "PASSIF", "CREDIT"),
    CompteSeed("442", "État, autres impôts et taxes", "PASSIF", "CREDIT", parent_numero="44"),
    CompteSeed("447", "État, impôts retenus à la source", "PASSIF", "CREDIT", parent_numero="44"),
    CompteSeed("46", "Débiteurs et créditeurs divers", "ACTIF", "DEBIT"),
    CompteSeed("4713", "Virements de fonds (compte d'attente rapprochement bancaire)", "ACTIF", "DEBIT"),
    # Classe 5 — Trésorerie (identique SYSCOHADA)
    CompteSeed("51", "Valeurs à encaisser / Banques", "ACTIF", "DEBIT"),
    CompteSeed("512", "Banques", "ACTIF", "DEBIT", parent_numero="51"),
    CompteSeed("521", "Banques, comptes en devises", "ACTIF", "DEBIT", parent_numero="51"),
    CompteSeed("57", "Caisse", "ACTIF", "DEBIT"),
    CompteSeed("571", "Caisse siège", "ACTIF", "DEBIT", parent_numero="57"),
    # Classe 6 — Charges
    CompteSeed("60", "Achats", "CHARGE", "DEBIT"),
    CompteSeed("605", "Autres achats", "CHARGE", "DEBIT", parent_numero="60"),
    CompteSeed("62", "Services extérieurs A", "CHARGE", "DEBIT"),
    CompteSeed("6132", "Locations", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("6152", "Entretien et réparations", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("6222", "Rémunérations d'intermédiaires et honoraires", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("625", "Déplacements, missions et réceptions", "CHARGE", "DEBIT", parent_numero="62"),
    CompteSeed("63", "Services extérieurs B", "CHARGE", "DEBIT"),
    CompteSeed("6281", "Frais de télécommunications", "CHARGE", "DEBIT", parent_numero="63"),
    CompteSeed("64", "Impôts et taxes", "CHARGE", "DEBIT"),
    CompteSeed("65", "Autres charges", "CHARGE", "DEBIT"),
    CompteSeed("658", "Charges diverses de gestion courante", "CHARGE", "DEBIT", parent_numero="65"),
    CompteSeed("66", "Charges de personnel", "CHARGE", "DEBIT"),
    CompteSeed("661", "Rémunérations directes versées au personnel", "CHARGE", "DEBIT", parent_numero="66"),
    CompteSeed("664", "Charges sociales", "CHARGE", "DEBIT", parent_numero="66"),
    CompteSeed("68", "Dotations aux amortissements", "CHARGE", "DEBIT"),
    CompteSeed("6811", "Dotations aux amortissements d'exploitation", "CHARGE", "DEBIT", parent_numero="68"),
    # Classe 7 — Produits (adaptés à l'activité associative)
    CompteSeed("70", "Cotisations", "PRODUIT", "CREDIT"),
    CompteSeed("7071", "Cotisations des adhérents", "PRODUIT", "CREDIT", parent_numero="70"),
    CompteSeed("74", "Subventions d'exploitation", "PRODUIT", "CREDIT"),
    CompteSeed("75", "Autres produits", "PRODUIT", "CREDIT"),
    CompteSeed("758", "Produits divers", "PRODUIT", "CREDIT", parent_numero="75"),
    CompteSeed("77", "Revenus financiers", "PRODUIT", "CREDIT"),
    CompteSeed("78", "Reprises d'amortissements et de provisions", "PRODUIT", "CREDIT"),
]

PLANS_PAR_TYPE: dict[str, list[CompteSeed]] = {
    "SYSCOHADA": SYSCOHADA_SEED,
    "SYSCEBNL": SYSCEBNL_SEED,
}


async def seeder_referentiel(
    db: AsyncSession,
    *,
    organisation_id: int,
    type_referentiel: str,
    code: str,
    libelle: str,
    is_default: bool = False,
) -> ComptaReferentiel:
    """Crée un référentiel et charge son plan comptable de démarrage.

    Idempotent au niveau référentiel : si un référentiel du même code existe
    déjà pour l'organisation, il est retourné sans être rechargé (évite les
    doublons si la fonction est appelée deux fois par erreur).
    """
    seed = PLANS_PAR_TYPE.get(type_referentiel)
    if seed is None:
        raise ValueError(f"Type de référentiel inconnu ou sans plan de démarrage : {type_referentiel}")

    existing = await db.execute(
        select(ComptaReferentiel).where(
            ComptaReferentiel.organisation_id == organisation_id,
            ComptaReferentiel.code == code,
        )
    )
    referentiel = existing.scalar_one_or_none()
    if referentiel is not None:
        return referentiel

    referentiel = ComptaReferentiel(
        organisation_id=organisation_id,
        code=code,
        libelle=libelle,
        type_referentiel=type_referentiel,
        is_default=is_default,
        source_import="plan_de_demarrage_integre",
    )
    db.add(referentiel)
    await db.flush()

    comptes_par_numero: dict[str, ComptaCompte] = {}
    for item in seed:
        compte = ComptaCompte(
            organisation_id=organisation_id,
            referentiel_id=referentiel.id,
            numero=item.numero,
            libelle=item.libelle,
            classe=item.classe,
            nature=item.nature,
            sens_normal=item.sens_normal,
            is_collectif=item.is_collectif,
            is_auxiliaire=item.is_auxiliaire,
        )
        db.add(compte)
        comptes_par_numero[item.numero] = compte
    await db.flush()

    for item in seed:
        if item.parent_numero:
            comptes_par_numero[item.numero].parent_id = comptes_par_numero[item.parent_numero].id
    await db.flush()

    return referentiel
