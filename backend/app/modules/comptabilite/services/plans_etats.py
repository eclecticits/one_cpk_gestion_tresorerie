"""Structures d'états financiers de démarrage (Lot 5).

Ces jeux décrivent, en DONNÉES, la présentation des états pour les deux plans
livrés. Ils sont modifiables par l'organisation : le moteur de calcul ne
connaît aucun numéro de compte.

⚠️ Les rattachements se font par **préfixe de numéro de compte**, ce qui est
la façon naturelle de décrire un état OHADA (par classes et sous-classes)
mais suppose que le plan soit numéroté proprement. Deux conséquences :

1. Les comptes « parents » structurels (21, 24, 62…) ne sont volontairement
   pas rattachés : ils ne devraient jamais recevoir d'écriture directe.
2. Le plan de démarrage numérote le matériel en 218x tout en le rattachant
   hiérarchiquement à 24. Les immobilisations corporelles portent donc le
   préfixe « 218 » en plus de 22/23/24.

Le contrôle de couverture (`comptes_non_couverts`) existe précisément pour
détecter ces cas : tout compte mouvementé qui n'entre dans aucun poste est
signalé, plutôt que de disparaître silencieusement d'un état.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaPosteEtat,
    ComptaPosteEtatCompte,
    ComptaReferentiel,
)


@dataclass(frozen=True)
class RattachementSeed:
    prefixe: str
    signe: int = 1
    filtre_solde: str = "TOUS"
    colonne: str = "BRUT"


@dataclass(frozen=True)
class PosteSeed:
    code: str
    libelle: str
    sens_normal: str = "DEBIT"
    est_total: bool = False
    signe: int = 1
    parent_code: str | None = None
    niveau: int = 1
    comptes: tuple[RattachementSeed, ...] = field(default_factory=tuple)


# ── Bilan — actif ────────────────────────────────────────────────────────────
# Sens DEBIT partout : la valeur affichée est (débit − crédit).

BILAN_ACTIF: list[PosteSeed] = [
    PosteSeed("AI", "Immobilisations incorporelles", niveau=2, parent_code="TOTAL_IMMO", comptes=(
        RattachementSeed("213"),
        RattachementSeed("2813", signe=-1, colonne="AMORTISSEMENT"),
    )),
    PosteSeed("AC", "Immobilisations corporelles", niveau=2, parent_code="TOTAL_IMMO", comptes=(
        RattachementSeed("22"), RattachementSeed("23"), RattachementSeed("24"),
        RattachementSeed("218"),
        RattachementSeed("2818", signe=-1, colonne="AMORTISSEMENT"),
    )),
    PosteSeed("TOTAL_IMMO", "ACTIF IMMOBILISÉ", est_total=True, niveau=1, parent_code="TOTAL_ACTIF"),

    PosteSeed("BX", "Créances clients / adhérents", niveau=2, parent_code="TOTAL_CIRCULANT", comptes=(
        RattachementSeed("41", filtre_solde="DEBITEUR"),
    )),
    PosteSeed("BZ", "Autres créances", niveau=2, parent_code="TOTAL_CIRCULANT", comptes=(
        RattachementSeed("40", filtre_solde="DEBITEUR"),
        RattachementSeed("42", filtre_solde="DEBITEUR"),
        RattachementSeed("43", filtre_solde="DEBITEUR"),
        RattachementSeed("44", filtre_solde="DEBITEUR"),
        RattachementSeed("46", filtre_solde="DEBITEUR"),
        RattachementSeed("47", filtre_solde="DEBITEUR"),
    )),
    PosteSeed("TOTAL_CIRCULANT", "ACTIF CIRCULANT", est_total=True, niveau=1, parent_code="TOTAL_ACTIF"),

    PosteSeed("BQ", "Banques", niveau=2, parent_code="TOTAL_TRESO", comptes=(
        RattachementSeed("51", filtre_solde="DEBITEUR"),
        RattachementSeed("52", filtre_solde="DEBITEUR"),
    )),
    PosteSeed("BS", "Caisse", niveau=2, parent_code="TOTAL_TRESO", comptes=(
        RattachementSeed("57", filtre_solde="DEBITEUR"),
    )),
    PosteSeed("TOTAL_TRESO", "TRÉSORERIE ACTIF", est_total=True, niveau=1, parent_code="TOTAL_ACTIF"),

    PosteSeed("TOTAL_ACTIF", "TOTAL ACTIF", est_total=True, niveau=0),
]


# ── Bilan — passif ───────────────────────────────────────────────────────────
# Sens CREDIT partout : la valeur affichée est (crédit − débit).
#
# Aucun `signe=-1` n'est nécessaire ici : l'orientation CREDIT du poste inverse
# déjà les soldes débiteurs. Un report à nouveau débiteur (119) ou une perte
# (129) ressortent donc spontanément en négatif, c'est-à-dire en diminution des
# capitaux propres — la présentation OHADA. Ajouter un signe négatif les
# ferait au contraire AUGMENTER les capitaux propres.
# Le `signe` ne sert qu'à contredire l'orientation du poste : en pratique, la
# colonne AMORTISSEMENT du bilan actif.

def _bilan_passif(libelle_fonds: str, prefixe_fonds: str) -> list[PosteSeed]:
    return [
        PosteSeed("CA", libelle_fonds, "CREDIT", niveau=2, parent_code="TOTAL_CP", comptes=(
            RattachementSeed(prefixe_fonds),
        )),
        PosteSeed("CB", "Réserves", "CREDIT", niveau=2, parent_code="TOTAL_CP", comptes=(
            RattachementSeed("106"),
        )),
        PosteSeed("CC", "Report à nouveau", "CREDIT", niveau=2, parent_code="TOTAL_CP", comptes=(
            RattachementSeed("110"), RattachementSeed("119"),
        )),
        PosteSeed("CD", "Résultat de l'exercice", "CREDIT", niveau=2, parent_code="TOTAL_CP", comptes=(
            RattachementSeed("120"), RattachementSeed("129"),
        )),
        PosteSeed("CE", "Subventions d'investissement", "CREDIT", niveau=2, parent_code="TOTAL_CP", comptes=(
            RattachementSeed("14"),
        )),
        PosteSeed("TOTAL_CP", "CAPITAUX PROPRES", "CREDIT", est_total=True, niveau=1, parent_code="TOTAL_PASSIF"),

        PosteSeed("DA", "Emprunts et dettes financières", "CREDIT", niveau=2, parent_code="TOTAL_DETTES", comptes=(
            RattachementSeed("16"),
        )),
        PosteSeed("DB", "Fournisseurs", "CREDIT", niveau=2, parent_code="TOTAL_DETTES", comptes=(
            RattachementSeed("40", filtre_solde="CREDITEUR"),
        )),
        PosteSeed("DC", "Dettes sociales et fiscales", "CREDIT", niveau=2, parent_code="TOTAL_DETTES", comptes=(
            RattachementSeed("42", filtre_solde="CREDITEUR"),
            RattachementSeed("43", filtre_solde="CREDITEUR"),
            RattachementSeed("44", filtre_solde="CREDITEUR"),
        )),
        PosteSeed("DD", "Autres dettes", "CREDIT", niveau=2, parent_code="TOTAL_DETTES", comptes=(
            RattachementSeed("41", filtre_solde="CREDITEUR"),
            RattachementSeed("46", filtre_solde="CREDITEUR"),
            RattachementSeed("47", filtre_solde="CREDITEUR"),
        )),
        PosteSeed("TOTAL_DETTES", "DETTES", "CREDIT", est_total=True, niveau=1, parent_code="TOTAL_PASSIF"),

        PosteSeed("DE", "Trésorerie passif (découverts)", "CREDIT", niveau=1, parent_code="TOTAL_PASSIF", comptes=(
            RattachementSeed("51", filtre_solde="CREDITEUR"),
            RattachementSeed("52", filtre_solde="CREDITEUR"),
            RattachementSeed("57", filtre_solde="CREDITEUR"),
        )),

        PosteSeed("TOTAL_PASSIF", "TOTAL PASSIF", "CREDIT", est_total=True, niveau=0),
    ]


# ── Compte de résultat ───────────────────────────────────────────────────────

def _resultat(postes_produits: tuple[PosteSeed, ...]) -> list[PosteSeed]:
    return [
        *postes_produits,
        PosteSeed("TOTAL_PRODUITS", "TOTAL DES PRODUITS", "CREDIT", est_total=True, niveau=1,
                  parent_code="RESULTAT_NET"),

        PosteSeed("RA", "Achats", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("60"),
        )),
        PosteSeed("RB", "Transports", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("61"),
        )),
        PosteSeed("RC", "Services extérieurs", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("62"), RattachementSeed("63"),
        )),
        PosteSeed("RD", "Impôts et taxes", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("64"),
        )),
        PosteSeed("RE", "Autres charges", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("65"),
        )),
        PosteSeed("RF", "Charges de personnel", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("66"),
        )),
        PosteSeed("RG", "Dotations aux amortissements", niveau=2, parent_code="TOTAL_CHARGES", comptes=(
            RattachementSeed("68"),
        )),
        PosteSeed("TOTAL_CHARGES", "TOTAL DES CHARGES", est_total=True, niveau=1,
                  parent_code="RESULTAT_NET", signe=-1),

        PosteSeed("RESULTAT_NET", "RÉSULTAT NET DE L'EXERCICE", "CREDIT", est_total=True, niveau=0),
    ]


PRODUITS_SYSCOHADA: tuple[PosteSeed, ...] = (
    PosteSeed("PA", "Ventes et services", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("70"),
    )),
    PosteSeed("PB", "Autres produits", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("75"),
    )),
    PosteSeed("PC", "Revenus financiers", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("77"),
    )),
    PosteSeed("PD", "Reprises de provisions", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("78"),
    )),
)

PRODUITS_SYSCEBNL: tuple[PosteSeed, ...] = (
    PosteSeed("PA", "Cotisations des adhérents", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("70"),
    )),
    PosteSeed("PB", "Subventions d'exploitation", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("74"),
    )),
    PosteSeed("PC", "Autres produits", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("75"),
    )),
    PosteSeed("PD", "Revenus financiers", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("77"),
    )),
    PosteSeed("PE", "Reprises de provisions", "CREDIT", niveau=2, parent_code="TOTAL_PRODUITS", comptes=(
        RattachementSeed("78"),
    )),
)


# ── Soldes intermédiaires de gestion ─────────────────────────────────────────
# Chaque solde est une FEUILLE qui agrège directement ses comptes avec leurs
# signes, et non un total de lignes filles : un SIG s'appuie sur le solde
# précédent, ce qu'une hiérarchie à parent unique ne sait pas exprimer.

SIG: list[PosteSeed] = [
    PosteSeed("SIG_MARGE", "Marge sur activité", "CREDIT", niveau=1, comptes=(
        RattachementSeed("70"), RattachementSeed("74"),
        RattachementSeed("60"),
    )),
    PosteSeed("SIG_VA", "Valeur ajoutée", "CREDIT", niveau=1, comptes=(
        RattachementSeed("70"), RattachementSeed("74"),
        RattachementSeed("60"), RattachementSeed("61"),
        RattachementSeed("62"), RattachementSeed("63"),
    )),
    PosteSeed("SIG_EBE", "Excédent brut d'exploitation", "CREDIT", niveau=1, comptes=(
        RattachementSeed("70"), RattachementSeed("74"),
        RattachementSeed("60"), RattachementSeed("61"),
        RattachementSeed("62"), RattachementSeed("63"),
        RattachementSeed("64"), RattachementSeed("66"),
    )),
    PosteSeed("SIG_EXPLOIT", "Résultat d'exploitation", "CREDIT", niveau=1, comptes=(
        RattachementSeed("70"), RattachementSeed("74"), RattachementSeed("75"),
        RattachementSeed("78"),
        RattachementSeed("60"), RattachementSeed("61"),
        RattachementSeed("62"), RattachementSeed("63"),
        RattachementSeed("64"), RattachementSeed("65"),
        RattachementSeed("66"), RattachementSeed("68"),
    )),
    PosteSeed("SIG_NET", "Résultat net", "CREDIT", niveau=0, comptes=(
        RattachementSeed("70"), RattachementSeed("74"), RattachementSeed("75"),
        RattachementSeed("77"), RattachementSeed("78"),
        RattachementSeed("60"), RattachementSeed("61"),
        RattachementSeed("62"), RattachementSeed("63"),
        RattachementSeed("64"), RattachementSeed("65"),
        RattachementSeed("66"), RattachementSeed("68"),
    )),
]


# ── Tableau de variation de trésorerie ───────────────────────────────────────
# Les valeurs de cet état sont des VARIATIONS de solde sur la période, pas des
# soldes (cf. moteur de calcul). Ce n'est pas le TAFIRE complet OHADA, qui
# exige des retraitements hors périmètre (cessions d'immobilisations,
# ventilation des dotations non décaissées).

FLUX: list[PosteSeed] = [
    PosteSeed("FA", "Résultat de l'exercice", "CREDIT", niveau=2, parent_code="FLUX_ACTIVITE", comptes=(
        RattachementSeed("120"), RattachementSeed("129"),
    )),
    PosteSeed("FB", "Dotations aux amortissements (non décaissées)", "CREDIT", niveau=2,
              parent_code="FLUX_ACTIVITE", comptes=(RattachementSeed("28"),)),
    PosteSeed("FC", "Variation des créances", "CREDIT", niveau=2, parent_code="FLUX_ACTIVITE", comptes=(
        RattachementSeed("41"), RattachementSeed("46"),
        RattachementSeed("47"),
    )),
    PosteSeed("FD", "Variation des dettes d'exploitation", "CREDIT", niveau=2,
              parent_code="FLUX_ACTIVITE", comptes=(
        RattachementSeed("40"), RattachementSeed("42"), RattachementSeed("43"),
        RattachementSeed("44"),
    )),
    PosteSeed("FLUX_ACTIVITE", "FLUX DE L'ACTIVITÉ", "CREDIT", est_total=True, niveau=1,
              parent_code="FLUX_TRESORERIE"),

    PosteSeed("FE", "Acquisitions d'immobilisations", "CREDIT", niveau=2,
              parent_code="FLUX_INVESTISSEMENT", comptes=(
        RattachementSeed("21"), RattachementSeed("22"),
        RattachementSeed("23"), RattachementSeed("24"),
        RattachementSeed("218"),
    )),
    PosteSeed("FLUX_INVESTISSEMENT", "FLUX D'INVESTISSEMENT", "CREDIT", est_total=True, niveau=1,
              parent_code="FLUX_TRESORERIE"),

    PosteSeed("FF", "Fonds propres et subventions", "CREDIT", niveau=2, parent_code="FLUX_FINANCEMENT",
              comptes=(
        RattachementSeed("10"), RattachementSeed("14"),
    )),
    PosteSeed("FG", "Emprunts", "CREDIT", niveau=2, parent_code="FLUX_FINANCEMENT", comptes=(
        RattachementSeed("16"),
    )),
    PosteSeed("FLUX_FINANCEMENT", "FLUX DE FINANCEMENT", "CREDIT", est_total=True, niveau=1,
              parent_code="FLUX_TRESORERIE"),

    PosteSeed("FLUX_TRESORERIE", "VARIATION DE TRÉSORERIE", "CREDIT", est_total=True, niveau=0),
]


def _etats_pour(type_referentiel: str) -> dict[str, list[PosteSeed]]:
    if type_referentiel == "SYSCEBNL":
        return {
            "BILAN_ACTIF": BILAN_ACTIF,
            "BILAN_PASSIF": _bilan_passif("Fonds associatifs", "10"),
            "RESULTAT": _resultat(PRODUITS_SYSCEBNL),
            "SIG": SIG,
            "FLUX": FLUX,
        }
    return {
        "BILAN_ACTIF": BILAN_ACTIF,
        "BILAN_PASSIF": _bilan_passif("Capital", "10"),
        "RESULTAT": _resultat(PRODUITS_SYSCOHADA),
        "SIG": SIG,
        "FLUX": FLUX,
    }


async def seeder_etats_financiers(
    db: AsyncSession, *, organisation_id: int, referentiel_id: int
) -> dict:
    """Charge les structures d'états d'un référentiel.

    Idempotent au niveau du référentiel : si des postes existent déjà, rien
    n'est recréé — le paramétrage affiné par l'organisation ne doit jamais
    être écrasé par un simple rejeu du provisionnement.
    """
    existant = await db.execute(
        select(ComptaPosteEtat.id).where(
            ComptaPosteEtat.organisation_id == organisation_id,
            ComptaPosteEtat.referentiel_id == referentiel_id,
        ).limit(1)
    )
    if existant.scalar_one_or_none() is not None:
        return {"deja_existant": True, "postes_crees": 0}

    referentiel = await db.get(ComptaReferentiel, referentiel_id)
    if referentiel is None:
        raise ValueError(f"Référentiel #{referentiel_id} introuvable.")

    etats = _etats_pour(referentiel.type_referentiel)
    nb_postes = 0

    for type_etat, seeds in etats.items():
        # Deux passes : les postes d'abord (le parent d'une ligne peut être
        # déclaré après elle dans la liste), les liens ensuite.
        par_code: dict[str, ComptaPosteEtat] = {}
        for ordre, seed in enumerate(seeds, start=1):
            poste = ComptaPosteEtat(
                organisation_id=organisation_id,
                referentiel_id=referentiel_id,
                type_etat=type_etat,
                code=seed.code,
                libelle=seed.libelle,
                ordre=ordre,
                niveau=seed.niveau,
                est_total=seed.est_total,
                sens_normal=seed.sens_normal,
                signe=seed.signe,
            )
            db.add(poste)
            par_code[seed.code] = poste
            nb_postes += 1
        await db.flush()

        for seed in seeds:
            poste = par_code[seed.code]
            if seed.parent_code:
                parent = par_code.get(seed.parent_code)
                if parent is None:
                    raise ValueError(
                        f"Poste parent « {seed.parent_code} » introuvable pour {type_etat}/{seed.code}."
                    )
                poste.parent_id = parent.id
            for rattachement in seed.comptes:
                db.add(
                    ComptaPosteEtatCompte(
                        organisation_id=organisation_id,
                        poste_etat_id=poste.id,
                        prefixe_compte=rattachement.prefixe,
                        signe=rattachement.signe,
                        filtre_solde=rattachement.filtre_solde,
                        colonne=rattachement.colonne,
                    )
                )
        await db.flush()

    return {"deja_existant": False, "postes_crees": nb_postes}
