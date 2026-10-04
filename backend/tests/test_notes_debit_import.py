"""Import Excel des notes de débit des experts-comptables.

La feuille fait foi : une ligne par membre, une colonne par libellé, plus une
colonne « Arriérés ». Ces tests verrouillent ce qui en est lu, ce qui en est
refusé, et ce qui en est créé.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.encaissement_tarif import EncaissementTarif, normaliser_libelle
from app.models.expert_comptable import ExpertComptable
from app.models.note_debit_import import NoteDebitImport
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.services.notes_debit_import import (
    analyser,
    cle_numero_ordre,
    importer,
    lire_feuille,
    lire_montant,
)

# Les écritures comptables sont générées dans le flux : sans cet import, leurs
# tables manquent au schéma de test.
from app.modules.comptabilite import models as _compta_models  # noqa: F401


def _suffixe() -> str:
    return uuid.uuid4().hex[:6].upper()


def _classeur(lignes: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for ligne in lignes:
        ws.append(ligne)
    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


# ---------------------------------------------------------------------------
# Lecture, sans base
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brut, attendu",
    [
        (600, Decimal("600.00")),
        (450.5, Decimal("450.50")),
        ("1 500", Decimal("1500.00")),
        ("1.500,00", Decimal("1500.00")),
        ("1,500.00", Decimal("1500.00")),
        ("$600", Decimal("600.00")),
        ("600 USD", Decimal("600.00")),
        ("12,5", Decimal("12.50")),
        (None, None),
        ("", None),
        ("-", None),
    ],
)
def test_un_montant_se_lit_sous_toutes_ses_formes(brut, attendu):
    assert lire_montant(brut) == attendu


def test_une_cellule_en_toutes_lettres_n_est_pas_un_zero():
    """« exonéré » importé comme 0 effacerait une dette sans que personne l'ait décidé."""
    with pytest.raises(ValueError):
        lire_montant("exonéré")


def test_le_numero_d_ordre_se_rapproche_malgre_la_ponctuation():
    assert cle_numero_ordre("EC-0412") == cle_numero_ordre("ec 412") == "EC412"
    assert cle_numero_ordre(412.0) == "412"


def test_les_colonnes_se_classent_et_le_titre_est_saute():
    contenu = _classeur(
        [
            ["Notes de débit 2026 — Conseil provincial"],
            [],
            ["N°", "N° d'ordre", "Nom", "Province", "Cotisation 2026", "Pénalité AG", "Arriérés", "Total"],
            [1, "EC-1", "KABONGO", "Kinshasa", 600, 100, 450, 1150],
            [2, "EC-2", "LUBAMBA", "Kinshasa", 450, None, None, 450],
        ]
    )
    feuille = lire_feuille(contenu)

    assert feuille.ligne_entete == 3
    assert [c.libelle for c in feuille.colonnes] == ["Cotisation 2026", "Pénalité AG", "Arriérés"]
    assert [c.arrieres for c in feuille.colonnes] == [False, False, True]
    ignorees = {i["libelle"] for i in feuille.ignorees}
    assert {"N°", "Province", "Total"} <= ignorees
    # Le n° de ligne est celui du fichier : c'est là que l'utilisateur ira corriger.
    assert [n for n, _ in feuille.lignes] == [4, 5]


def test_une_feuille_sans_identite_est_refusee():
    with pytest.raises(HTTPException) as exc:
        lire_feuille(_classeur([["Cotisation", "Pénalité"], [600, 100]]))
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Analyse et import, avec la base
# ---------------------------------------------------------------------------


async def _contexte(db):
    org = Organisation(nom="Notes ND", slug=f"nd-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(organisation_id=org.id, code=f"S{_suffixe()}", libelle="Trésorerie", is_active=True)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.VOTE)
    db.add_all([service, exercice])
    await db.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@ex.com",
        role="admin",
        organisation_id=org.id,
        service_id=service.id,
    )
    db.add(user)
    postes = {}
    for cle, libelle in (("cot", "Cotisations des membres"), ("pen", "Pénalités"), ("arr", "Arriérés de cotisations")):
        poste = BudgetPoste(
            organisation_id=org.id, exercice_id=exercice.id, code=f"R-{cle}-{_suffixe()}",
            libelle=libelle, type="RECETTE", active=True, montant_prevu=Decimal("100000"),
            montant_engage=0, montant_paye=0, is_deleted=False,
        )
        db.add(poste)
        postes[cle] = poste
    await db.flush()
    for poste in postes.values():
        db.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste.id, active=True))
    sfx = _suffixe()
    experts = {
        "ec": ExpertComptable(numero_ordre=f"EC-{sfx}1", nom_denomination="KABONGO Jean", type_ec="EC", active=True),
        "sal": ExpertComptable(numero_ordre=f"EC-{sfx}2", nom_denomination="LUBAMBA Paul", type_ec="EC", active=True),
        "sec": ExpertComptable(numero_ordre=f"SEC-{sfx}3", nom_denomination="CABINET XYZ", type_ec="SEC", active=True),
    }
    db.add_all(experts.values())
    await db.commit()
    return org, user, service, postes, experts


def _fichier(experts, *, inconnu: bool = False, total_faux: bool = False) -> bytes:
    lignes = [
        ["N° d'ordre", "Nom", "Cotisation 2026", "Pénalité AG", "Arriérés", "Total"],
        [experts["ec"].numero_ordre, "KABONGO", 600, 300, 450, 1350],
        [experts["sal"].numero_ordre, "LUBAMBA", 450, None, None, 999 if total_faux else 450],
        [experts["sec"].numero_ordre, "CABINET XYZ", 4200, None, 1500, 5700],
    ]
    if inconnu:
        lignes.append(["EC-INCONNU-999", "FANTOME", 600, None, None, 600])
    return _classeur(lignes)


def _postes_choisis(analyse_reponse_colonnes, postes) -> dict[str, int]:
    par_libelle = {"Cotisation 2026": postes["cot"].id, "Pénalité AG": postes["pen"].id, "Arriérés": postes["arr"].id}
    return {c["cle"]: par_libelle[c["libelle"]] for c in analyse_reponse_colonnes}


@pytest.mark.asyncio
async def test_l_analyse_signale_sans_rien_ecrire(db_session):
    db = db_session
    org, user, service, postes, experts = await _contexte(db)

    analyse = await analyser(
        db, tenant_id=org.id, user=user, contenu=_fichier(experts, inconnu=True, total_faux=True), service_id=service.id
    )

    statuts = {l.numero_ordre: l for l in analyse.lignes}
    assert statuts["EC-INCONNU-999"].statut == "erreur"
    assert any("Total du fichier" in a for a in statuts[experts["sal"].numero_ordre].avertissements)
    assert statuts[experts["ec"].numero_ordre].total == Decimal("1350.00")
    # Le poste d'arriérés se devine au libellé, faute de lien d'exercice précédent.
    arrieres = next(c for c in analyse.colonnes if c["arrieres"])
    assert arrieres["poste_suggere_id"] == postes["arr"].id
    nb = (await db.execute(select(Encaissement).where(Encaissement.organisation_id == org.id))).scalars().all()
    assert nb == []


@pytest.mark.asyncio
async def test_l_import_cree_une_note_par_ligne_et_une_ligne_par_colonne(db_session):
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    contenu = _fichier(experts, inconnu=True)
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)

    resultat = await importer(
        db, tenant_id=org.id, user=user, fichier="nd_2026.xlsx", contenu=contenu,
        service_id=service.id, postes=_postes_choisis(analyse.colonnes, postes),
    )

    assert resultat["nb_notes"] == 3
    assert resultat["nb_lignes_ecartees"] == 1  # le n° inconnu
    assert Decimal(resultat["montant_total"]) == Decimal("7500.00")
    assert Decimal(resultat["montant_arrieres"]) == Decimal("1950.00")

    notes = (
        await db.execute(select(Encaissement).where(Encaissement.organisation_id == org.id))
    ).scalars().all()
    par_expert = {n.expert_comptable_id: n for n in notes}
    sec = par_expert[experts["sec"].id]
    assert sec.type_client == "sec"
    assert sec.statut_paiement == "non_paye"
    assert sec.montant_paye == Decimal("0.00")
    assert sec.numero_recu.startswith("ND-")
    assert sec.note_debit_import_id == uuid.UUID(resultat["import_id"])
    assert par_expert[experts["ec"].id].type_client == "expert_comptable"

    articles = (
        await db.execute(
            select(EncaissementArticle)
            .where(EncaissementArticle.encaissement_id == par_expert[experts["ec"].id].id)
            .order_by(EncaissementArticle.sort_order)
        )
    ).scalars().all()
    assert [(a.libelle, a.montant, a.budget_poste_id) for a in articles] == [
        ("Cotisation 2026", Decimal("600.00"), postes["cot"].id),
        ("Pénalité AG", Decimal("300.00"), postes["pen"].id),
        ("Arriérés", Decimal("450.00"), postes["arr"].id),
    ]
    enregistrement = await db.get(NoteDebitImport, uuid.UUID(resultat["import_id"]))
    assert enregistrement.organisation_id == org.id and enregistrement.nb_notes == 3


@pytest.mark.asyncio
async def test_reimporter_le_meme_fichier_ne_double_pas_les_dettes(db_session):
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    contenu = _fichier(experts)
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    choix = _postes_choisis(analyse.colonnes, postes)
    await importer(db, tenant_id=org.id, user=user, fichier="a.xlsx", contenu=contenu, service_id=service.id, postes=choix)

    seconde = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    assert all(l.doublon for l in seconde.lignes)

    with pytest.raises(HTTPException) as exc:
        await importer(db, tenant_id=org.id, user=user, fichier="a.xlsx", contenu=contenu, service_id=service.id, postes=choix)
    assert exc.value.status_code == 400
    nb = (await db.execute(select(Encaissement).where(Encaissement.organisation_id == org.id))).scalars().all()
    assert len(nb) == 3


@pytest.mark.asyncio
async def test_un_poste_manquant_n_importe_rien(db_session):
    """Tout ou rien : une colonne sans poste bloque l'import entier, pas seulement ses lignes."""
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    contenu = _classeur(
        [
            ["N° d'ordre", "Nom", "Frais divers"],
            [experts["ec"].numero_ordre, "KABONGO", 50],
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await importer(db, tenant_id=org.id, user=user, fichier="b.xlsx", contenu=contenu, service_id=service.id, postes={})
    assert "Frais divers" in exc.value.detail
    nb = (await db.execute(select(NoteDebitImport).where(NoteDebitImport.organisation_id == org.id))).scalars().all()
    assert nb == []


@pytest.mark.asyncio
async def test_le_tarif_regle_donne_le_poste_et_la_quantite(db_session):
    """Un libellé tarifé s'impute sur le poste du tarif ; 300 à 100 l'unité, c'est 3 × 100."""
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    db.add(
        EncaissementTarif(
            organisation_id=org.id, libelle="Pénalité AG", libelle_normalise=normaliser_libelle("Pénalité AG"),
            montant=Decimal("100"), devise="USD", budget_poste_code=postes["pen"].code, is_active=True,
        )
    )
    await db.commit()
    contenu = _classeur(
        [
            ["N° d'ordre", "Nom", "Pénalité AG"],
            [experts["ec"].numero_ordre, "KABONGO", 300],
            [experts["sal"].numero_ordre, "LUBAMBA", 150],
        ]
    )
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    (colonne,) = analyse.colonnes
    assert colonne["poste_impose"] and colonne["poste_suggere_id"] == postes["pen"].id
    lubamba = next(l for l in analyse.lignes if l.expert.id == experts["sal"].id)
    assert any("tarif" in a for a in lubamba.avertissements)

    await importer(db, tenant_id=org.id, user=user, fichier="c.xlsx", contenu=contenu, service_id=service.id, postes={})

    articles = {
        n.expert_comptable_id: a
        for n, a in (
            await db.execute(
                select(Encaissement, EncaissementArticle)
                .join(EncaissementArticle, EncaissementArticle.encaissement_id == Encaissement.id)
                .where(Encaissement.organisation_id == org.id)
            )
        ).all()
    }
    kabongo = articles[experts["ec"].id]
    assert (kabongo.quantite, kabongo.prix_unitaire, kabongo.tarif_force) == (Decimal("3.00"), Decimal("100.00"), False)
    # 150 ne tombe pas juste : le montant du fichier est retenu, et l'écart se sait.
    lub = articles[experts["sal"].id]
    assert (lub.montant, lub.tarif_force) == (Decimal("150.00"), True)


@pytest.mark.asyncio
async def test_la_liste_retrouve_les_notes_d_un_import_et_totalise_la_selection(db_session):
    from app.api.v1.endpoints.notes_debit import lister_notes

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    contenu = _fichier(experts)
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    resultat = await importer(
        db, tenant_id=org.id, user=user, fichier="d.xlsx", contenu=contenu,
        service_id=service.id, postes=_postes_choisis(analyse.colonnes, postes),
    )

    async def lister(**params):
        defauts = dict(q=None, statut="impayees", type_client=None, import_id=None, limit=2, offset=0)
        return await lister_notes(**{**defauts, **params}, tenant_id=org.id, user=user, db=db)

    page = await lister(import_id=uuid.UUID(resultat["import_id"]))
    # Deux lignes sur la page, mais les totaux portent sur les trois notes.
    assert len(page["items"]) == 2 and page["total"] == 3
    assert Decimal(page["totaux"]["reste_du"]) == Decimal("7500.00")

    seules_sec = await lister(type_client="sec")
    assert [n["expert"]["id"] for n in seules_sec["items"]] == [str(experts["sec"].id)]

    par_nom = await lister(q="LUBAMBA")
    assert par_nom["total"] == 1 and par_nom["items"][0]["reste_du"] == "450.00"


# ---------------------------------------------------------------------------
# Lot 2 : fiche, impression, relevé, mise en demeure
# ---------------------------------------------------------------------------


async def _importer_fichier(db, org, user, service, postes, experts):
    contenu = _fichier(experts)
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    return await importer(
        db, tenant_id=org.id, user=user, fichier="lot2.xlsx", contenu=contenu,
        service_id=service.id, postes=_postes_choisis(analyse.colonnes, postes),
    )


@pytest.mark.asyncio
async def test_la_fiche_raconte_l_emission_et_les_versements(db_session):
    from app.api.v1.endpoints.notes_debit import fiche_note
    from app.models.caisse_centrale import CaisseCentrale
    from app.services.encaissement_payments import record_encaissement_payment

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=0, est_ouverte=True))
    await db.commit()
    resultat = await _importer_fichier(db, org, user, service, postes, experts)
    note_id = next(n["id"] for n in resultat["notes"] if n["nom"] == "KABONGO Jean")
    await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=uuid.UUID(note_id), montant=Decimal("600"),
        mode_paiement="cash", reference=None, notes=None, user_id=user.id,
    )
    await db.commit()

    fiche = await fiche_note(note_id=uuid.UUID(note_id), tenant_id=org.id, user=user, db=db)

    assert [a["libelle"] for a in fiche["articles"]] == ["Cotisation 2026", "Pénalité AG", "Arriérés"]
    assert fiche["statut_paiement"] == "partiel" and fiche["reste_du"] == "750.00"
    assert fiche["nb_paiements"] == 1
    assert fiche["import"]["fichier"] == "lot2.xlsx"
    types = [e["type"] for e in fiche["historique"]]
    assert types[0] == "emission" and "paiement" in types
    assert "lot2.xlsx" in fiche["historique"][0]["libelle"]


@pytest.mark.asyncio
async def test_un_import_s_imprime_d_un_bloc(db_session):
    from app.api.v1.endpoints.notes_debit import documents_a_imprimer

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    resultat = await _importer_fichier(db, org, user, service, postes, experts)

    documents = await documents_a_imprimer(
        ids=None, import_id=uuid.UUID(resultat["import_id"]), tenant_id=org.id, user=user, db=db
    )

    assert len(documents["notes"]) == 3
    sec = next(n for n in documents["notes"] if n["type_client"] == "sec")
    assert [(a["libelle"], a["montant"]) for a in sec["articles"]] == [
        ("Cotisation 2026", "4200.00"), ("Arriérés", "1500.00"),
    ]
    assert "comptes" in documents


@pytest.mark.asyncio
async def test_la_mise_en_demeure_porte_sur_tout_ce_que_le_membre_doit(db_session):
    from app.api.v1.endpoints.notes_debit import MiseEnDemeurePayload, fiche_note, mettre_en_demeure

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    await _importer_fichier(db, org, user, service, postes, experts)

    releve = await mettre_en_demeure(
        expert_id=experts["sec"].id, payload=MiseEnDemeurePayload(delai_jours=15),
        tenant_id=org.id, user=user, db=db,
    )

    assert Decimal(releve["total_du"]) == Decimal("5700.00")
    assert releve["delai_jours"] == 15 and releve["echeance"]
    fiche = await fiche_note(note_id=uuid.UUID(releve["notes"][0]["id"]), tenant_id=org.id, user=user, db=db)
    assert fiche["nb_mises_en_demeure"] == 1
    assert any(e["type"] == "mise_en_demeure" for e in fiche["historique"])


@pytest.mark.asyncio
async def test_on_ne_met_pas_en_demeure_un_membre_qui_ne_doit_rien(db_session):
    from app.api.v1.endpoints.notes_debit import MiseEnDemeurePayload, mettre_en_demeure

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    with pytest.raises(HTTPException) as exc:
        await mettre_en_demeure(
            expert_id=experts["ec"].id, payload=MiseEnDemeurePayload(), tenant_id=org.id, user=user, db=db
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Lot 3 : tableau de bord, régularité pour le Tableau
# ---------------------------------------------------------------------------


async def _avec_caisse(db, org):
    from app.models.caisse_centrale import CaisseCentrale

    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=0, est_ouverte=True))
    await db.commit()


async def _payer(db, org, user, note_id, montant):
    from app.services.encaissement_payments import record_encaissement_payment

    await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=uuid.UUID(note_id), montant=Decimal(str(montant)),
        mode_paiement="cash", reference=None, notes=None, user_id=user.id,
    )
    await db.commit()


@pytest.mark.asyncio
async def test_le_tableau_de_bord_totalise_l_exercice(db_session):
    from datetime import datetime, timezone

    from app.api.v1.endpoints.notes_debit import tableau_de_bord

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    await _avec_caisse(db, org)
    resultat = await _importer_fichier(db, org, user, service, postes, experts)
    lubamba = next(n["id"] for n in resultat["notes"] if n["nom"] == "LUBAMBA Paul")
    await _payer(db, org, user, lubamba, 450)

    bord = await tableau_de_bord(annee=datetime.now(timezone.utc).year, tenant_id=org.id, user=user, db=db)

    kpi = bord["kpi"]
    assert Decimal(kpi["emis"]) == Decimal("7500.00")
    assert Decimal(kpi["encaisse"]) == Decimal("450.00")
    assert Decimal(kpi["reste_total"]) == Decimal("7050.00")
    assert kpi["taux_recouvrement"] == 6.0
    assert kpi["membres_non_en_regle"] == 2  # LUBAMBA a soldé
    # 300 de pénalité sur la note de KABONGO, intacte : due en entier.
    assert Decimal(kpi["penalites_dues"]) == Decimal("300.00")
    assert {t["type_client"] for t in bord["par_type"]} == {"expert_comptable", "sec"}
    assert bord["par_libelle"][0]["libelle"] == "Cotisation 2026"
    assert bord["top_debiteurs"][0]["nom"] == "CABINET XYZ"
    assert sum(t["nb"] for t in bord["anciennete"]) == 2


@pytest.mark.asyncio
async def test_la_regularite_distingue_en_regle_debiteur_et_sans_note(db_session):
    from datetime import datetime, timezone

    from app.api.v1.endpoints.notes_debit import regularite_membres

    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    await _avec_caisse(db, org)
    contenu = _classeur(
        [
            ["N° d'ordre", "Nom", "Cotisation 2026"],
            [experts["ec"].numero_ordre, "KABONGO", 600],
            [experts["sal"].numero_ordre, "LUBAMBA", 450],
        ]
    )
    analyse = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id)
    resultat = await importer(
        db, tenant_id=org.id, user=user, fichier="r.xlsx", contenu=contenu, service_id=service.id,
        postes={analyse.colonnes[0]["cle"]: postes["cot"].id},
    )
    await _payer(db, org, user, next(n["id"] for n in resultat["notes"] if n["nom"] == "LUBAMBA Paul"), 450)

    annee = datetime.now(timezone.utc).year
    ids = ",".join(str(experts[k].id) for k in ("ec", "sal", "sec"))
    reponse = await regularite_membres(expert_ids=ids, annee=annee, tenant_id=org.id, user=user, db=db)

    membres = reponse["membres"]
    assert reponse["tableau"] == annee + 1
    assert membres[str(experts["ec"].id)]["statut"] == "non_en_regle"
    assert membres[str(experts["ec"].id)]["reste_du"] == "600.00"
    assert membres[str(experts["sal"].id)]["statut"] == "en_regle"
    assert membres[str(experts["sec"].id)]["statut"] == "sans_note"


# ---------------------------------------------------------------------------
# Catégories d'import (onglets, comme l'import national des experts)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_onglet_ec_refuse_une_sec_et_l_onglet_sec_un_expert(db_session):
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    contenu = _fichier(experts)

    onglet_ec = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id, categorie="ec")
    erreurs_ec = {l.expert.id: l.statut for l in onglet_ec.lignes}
    assert erreurs_ec[experts["sec"].id] == "erreur"
    assert erreurs_ec[experts["ec"].id] != "erreur"

    onglet_sec = await analyser(db, tenant_id=org.id, user=user, contenu=contenu, service_id=service.id, categorie="sec")
    statuts_sec = {l.expert.id: l.statut for l in onglet_sec.lignes}
    assert statuts_sec[experts["sec"].id] != "erreur"
    assert statuts_sec[experts["ec"].id] == "erreur"


@pytest.mark.asyncio
async def test_l_onglet_penalites_signale_une_colonne_qui_n_en_est_pas_une(db_session):
    db = db_session
    org, user, service, postes, experts = await _contexte(db)
    analyse = await analyser(
        db, tenant_id=org.id, user=user, contenu=_fichier(experts), service_id=service.id, categorie="penalites"
    )
    avertis = {c["libelle"]: c["avertissement"] for c in analyse.colonnes}
    assert avertis["Pénalité AG"] is None and avertis["Arriérés"] is None
    assert avertis["Cotisation 2026"]


@pytest.mark.asyncio
async def test_les_notes_d_un_conseil_n_existent_pas_pour_un_autre(db_session):
    """Chaque tenant est indépendant : ni ses notes, ni ses doublons ne débordent."""
    from app.api.v1.endpoints.notes_debit import lister_notes

    db = db_session
    org_a, user_a, service_a, postes_a, experts = await _contexte(db)
    contenu = _fichier(experts)
    analyse = await analyser(db, tenant_id=org_a.id, user=user_a, contenu=contenu, service_id=service_a.id)
    await importer(
        db, tenant_id=org_a.id, user=user_a, fichier="a.xlsx", contenu=contenu,
        service_id=service_a.id, postes=_postes_choisis(analyse.colonnes, postes_a),
    )

    org_b, user_b, service_b, postes_b, _ = await _contexte(db)
    vue_b = await lister_notes(
        q=None, statut="toutes", type_client=None, import_id=None, limit=50, offset=0,
        tenant_id=org_b.id, user=user_b, db=db,
    )
    assert vue_b["total"] == 0
    # Les mêmes membres, dans l'autre conseil : rien n'y est encore émis.
    analyse_b = await analyser(db, tenant_id=org_b.id, user=user_b, contenu=contenu, service_id=service_b.id)
    assert not any(l.doublon for l in analyse_b.lignes)
