"""Délibérations de la commission : mise en règle et retrait d'un membre, avec motif."""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest
from fastapi import HTTPException

import app.modules.tableau.service as tableau_service
from app.modules.tableau import deliberations, releves, verdict as verdict_engine
from app.modules.tableau.service import import_source_snapshot
from app.modules.tableau.sorties import declarer_sortie

NUMERO = "EC/16.99901"


def _xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.append(headers)
    for row in rows:
        wb.active.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def _membres(db, user):
    await import_source_snapshot(
        db, user, user.organisation_id, "pp-delib.xlsx",
        _xlsx(["N° Ordre", "Nom", "Statut", "N° impôt"], [
            [NUMERO, "KABONGO Jean", "salarié", None],
            ["EC/16.99902", "MBUYI Anne", "salarié", None],
        ]),
        "personnes_physiques", "2026", date(2026, 10, 31),
    )


async def _membre(db, user, numero=NUMERO, **filtres):
    base = await tableau_service.get_base_tableau(db, [user.organisation_id], exercice="2026", limit=50, **filtres)
    return next((m for m in base["membres_a_completer"] if m["numero_ordre"] == numero), None)


async def _deliberer(db, user, conclusion=verdict_engine.INSCRIT, motif="Cotisation régularisée après la date de situation", **extra):
    membre = await deliberations.situation_du_membre(db, user.organisation_id, "2026", NUMERO)
    return await deliberations.deliberer(
        db, user, user.organisation_id, "tenant",
        exercice=membre["exercice"], numero_ordre=membre["numero_ordre"], nom=membre["nom"],
        categorie=membre["categorie"], conclusion=conclusion,
        conclusion_automatique=membre["conclusion_automatique"],
        criteres=extra.pop("criteres", ["cotisation"]), motif=motif, **extra,
    )


async def test_la_mise_en_regle_prime_sur_le_calcul_et_le_garde(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    avant = await _membre(db_session, admin_isole)
    assert avant["conclusion"] == verdict_engine.NON_INSCRIT

    await _deliberer(db_session, admin_isole, reference_seance="Séance du 20/11/2026")
    apres = await _membre(db_session, admin_isole)
    assert apres["conclusion"] == verdict_engine.INSCRIT
    assert apres["deliberation"]["verdict_automatique"] == verdict_engine.NON_INSCRIT
    assert apres["deliberation"]["criteres"] == ["cotisation"]
    assert "Séance du 20/11/2026" in apres["conclusion_motif"]
    assert apres["deliberation"]["diverge"] is False
    # L'autre membre n'est pas touché.
    assert (await _membre(db_session, admin_isole, "EC/16.99902"))["deliberation"] is None

    # Le tableau de bord compte comme la Base.
    stats = await tableau_service.get_stats_tableau(db_session, admin_isole.organisation_id, actif="tous")
    assert (stats["en_regle"], stats["non_en_regle"]) == (1, 1)
    # Filtre « Délibérés ».
    assert [m["numero_ordre"] for m in (await tableau_service.get_base_tableau(
        db_session, [admin_isole.organisation_id], exercice="2026", deliberation="oui",
    ))["membres_a_completer"]] == [NUMERO]


async def test_une_nouvelle_deliberation_remplace_la_precedente_et_la_revocation_rend_la_main(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    premiere = await _deliberer(db_session, admin_isole)
    seconde = await _deliberer(db_session, admin_isole, conclusion=verdict_engine.A_DELIBERER, motif="Pièce à examiner")
    assert (await _membre(db_session, admin_isole))["conclusion"] == verdict_engine.A_DELIBERER

    await deliberations.revoquer(db_session, admin_isole, admin_isole.organisation_id, seconde.id, "Décision prise par erreur")
    membre = await _membre(db_session, admin_isole)
    assert membre["conclusion"] == verdict_engine.NON_INSCRIT
    assert membre["deliberation"] is None

    historique = await deliberations.historique(db_session, admin_isole.organisation_id, "2026", NUMERO)
    assert [(h["id"], h["motif_revocation"]) for h in historique] == [
        (seconde.id, "Décision prise par erreur"),
        (premiere.id, "Remplacée par une nouvelle délibération"),
    ]
    with pytest.raises(HTTPException) as deja:
        await deliberations.revoquer(db_session, admin_isole, admin_isole.organisation_id, seconde.id, "Encore")
    assert deja.value.status_code == 409


async def test_refus_motif_vide_conclusion_inchangee_sans_numero_et_membre_sorti(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    with pytest.raises(HTTPException) as sans_motif:
        await _deliberer(db_session, admin_isole, motif="   ")
    assert sans_motif.value.status_code == 422
    with pytest.raises(HTTPException) as inchange:
        await _deliberer(db_session, admin_isole, conclusion=verdict_engine.NON_INSCRIT)
    assert "rien à délibérer" in inchange.value.detail
    with pytest.raises(HTTPException) as sans_numero:
        await deliberations.situation_du_membre(db_session, admin_isole.organisation_id, "2026", "  ")
    assert sans_numero.value.status_code == 422

    await declarer_sortie(
        db_session, admin_isole, admin_isole.organisation_id, "tenant",
        numero_ordre=NUMERO, nom="KABONGO Jean", categorie="EC Salarié",
        situation="DEMISSIONNAIRE", date_effet=date(2026, 6, 1),
    )
    with pytest.raises(HTTPException) as sorti:
        await deliberations.situation_du_membre(db_session, admin_isole.organisation_id, "2026", NUMERO)
    assert "sorti" in sorti.value.detail


async def test_un_reimport_ne_fait_pas_disparaitre_la_deliberation(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    await _deliberer(db_session, admin_isole)
    await import_source_snapshot(
        db_session, admin_isole, admin_isole.organisation_id, "pp-delib-v2.xlsx",
        _xlsx(["N° Ordre", "Nom", "Statut", "N° impôt"], [[NUMERO, "KABONGO Jean", "salarié", None]]),
        "personnes_physiques", "2026", date(2026, 11, 30),
    )
    assert (await _membre(db_session, admin_isole))["conclusion"] == verdict_engine.INSCRIT


def test_le_releve_d_un_retrait_cite_le_motif_de_la_commission():
    membre = {
        "numero_ordre": NUMERO, "nom": "KABONGO Jean", "categorie": "EC Salarié", "email": "k@example.cd",
        "conclusion": verdict_engine.NON_INSCRIT, "cotisation_etat": "payee", "formation_etat": "atteint",
        "deliberation": {"motif": "Paiement annulé ou rejeté"},
    }
    releve = releves.construire_releve(
        membre, exercice="2026", reglages=verdict_engine.TableauReglages(), organisation="Conseil",
    )
    assert releve.motifs == ["Décision de la Commission Tableau : Paiement annulé ou rejeté."]


def test_une_societe_se_voit_proposer_le_retrait_faute_d_adresse():
    societe = deliberations.motifs_suggeres("Société")["retrait"]
    assert societe[0] == "Pas d'adresse identifiable"
    assert "Pas d'adresse identifiable" not in deliberations.motifs_suggeres("EC Cabinet")["retrait"]


async def test_le_lot_delibere_chacun_et_nomme_ceux_qu_il_ecarte(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    await _deliberer(db_session, admin_isole)  # NUMERO est déjà en règle par délibération.
    resultat = await deliberations.deliberer_lot(
        db_session, admin_isole, admin_isole.organisation_id,
        exercice="2026", numeros=[NUMERO, "EC/16.99902", "EC/16.99999"], filtres=None,
        conclusion=verdict_engine.INSCRIT, criteres=[], motif="Cas de force majeure",
        reference_seance="Séance du 24/11/2026",
    )
    assert [m["numero_ordre"] for m in resultat["deliberes"]] == ["EC/16.99902"]
    assert [(m["numero_ordre"], m["raison"]) for m in resultat["ecartes"]] == [(NUMERO, "Déjà délibéré dans ce sens")]
    second = await _membre(db_session, admin_isole, "EC/16.99902")
    assert (second["conclusion"], second["deliberation"]["motif"]) == (verdict_engine.INSCRIT, "Cas de force majeure")


async def test_le_lot_suit_le_filtre_de_la_base(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    resultat = await deliberations.deliberer_lot(
        db_session, admin_isole, admin_isole.organisation_id,
        exercice="2026", numeros=None, filtres={"recherche": "MBUYI"},
        conclusion=verdict_engine.A_DELIBERER, criteres=["cotisation"], motif="Pièce à examiner",
    )
    assert [m["nom"] for m in resultat["deliberes"]] == ["MBUYI Anne"]
    assert (await _membre(db_session, admin_isole))["deliberation"] is None
    with pytest.raises(HTTPException):
        await deliberations.deliberer_lot(
            db_session, admin_isole, admin_isole.organisation_id,
            exercice="2026", numeros=[NUMERO], filtres=None,
            conclusion=verdict_engine.INSCRIT, criteres=[], motif=" ",
        )
