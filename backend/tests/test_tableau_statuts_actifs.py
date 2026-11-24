"""Statut « Actif » déclaré à la main : une société inactive, un EC corrigé."""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest
from fastapi import HTTPException

import app.modules.tableau.service as tableau_service
from app.modules.tableau import statuts_actifs
from app.modules.tableau.service import import_source_snapshot

SEC = "SEC/16.99951"
EC = "EC/16.99952"


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
        db, user, user.organisation_id, "pm-actif.xlsx",
        _xlsx(["N° Ordre", "Société", "Numéro impôt"], [[SEC, "ALPHA AUDIT SARL", "A1"]]),
        "personnes_morales", "2026", date(2026, 10, 31),
    )
    await import_source_snapshot(
        db, user, user.organisation_id, "pp-actif.xlsx",
        _xlsx(["N° Ordre", "Nom", "Statut", "N° impôt", "Actif"], [[EC, "KABONGO Jean", "salarié", None, "oui"]]),
        "personnes_physiques", "2026", date(2026, 10, 31),
    )


async def _ligne(db, user, numero, **filtres):
    base = await tableau_service.get_base_tableau(db, [user.organisation_id], exercice="2026", limit=50, **filtres)
    return next((m for m in base["membres_a_completer"] if m["numero_ordre"] == numero), None)


async def _declarer(db, user, numero, actif, motif="Pas d'adresse identifiable"):
    membre = await statuts_actifs.situation_du_membre(db, user.organisation_id, "2026", numero)
    return await statuts_actifs.declarer(
        db, user, user.organisation_id, "tenant", membre=membre, actif=actif, date_effet=date(2026, 11, 1), motif=motif,
    )


async def _actives(db, user, personne, actif):
    return (await tableau_service.get_stats_tableau(db, user.organisation_id, personne=personne, actif=actif))["membres_base"]


async def test_une_societe_est_active_par_defaut_puis_inactive_sur_declaration(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    societe = await _ligne(db_session, admin_isole, SEC)
    assert (societe["actif"], societe["statut_actif"]) == (True, None)
    assert await _actives(db_session, admin_isole, "morale", "oui") == 1

    declaration = await _declarer(db_session, admin_isole, SEC, False)
    societe = await _ligne(db_session, admin_isole, SEC)
    assert societe["actif"] is False
    assert societe["statut_actif"]["libelle"].startswith("Inactive depuis le 01/11/2026")
    # Écartée des comptes « Actifs », mais toujours jugée.
    assert (await _actives(db_session, admin_isole, "morale", "oui"), await _actives(db_session, admin_isole, "morale", "non")) == (0, 1)
    assert societe["conclusion"] is not None
    assert await _ligne(db_session, admin_isole, SEC, actif=False) is not None
    assert await _ligne(db_session, admin_isole, SEC, actif=True) is None

    await statuts_actifs.annuler(db_session, admin_isole, admin_isole.organisation_id, declaration.id, "Adresse retrouvée")
    assert (await _ligne(db_session, admin_isole, SEC))["actif"] is True
    historique = await statuts_actifs.historique(db_session, admin_isole.organisation_id, SEC)
    assert [h["motif_annulation"] for h in historique] == ["Adresse retrouvée"]


async def test_la_declaration_prime_sur_le_fichier_d_un_ec(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    assert (await _ligne(db_session, admin_isole, EC))["actif"] is True
    with pytest.raises(HTTPException) as deja:
        await _declarer(db_session, admin_isole, EC, True, motif="Reprise")
    assert "déjà actif" in deja.value.detail

    declaration = await _declarer(db_session, admin_isole, EC, False, motif="Erreur du fichier des membres")
    assert declaration.actif_fichier is True
    assert (await _ligne(db_session, admin_isole, EC))["actif"] is False
    assert await _actives(db_session, admin_isole, "physique", "oui") == 0

    # Une nouvelle déclaration remplace la précédente.
    await _declarer(db_session, admin_isole, EC, True, motif="Reprise d'activité déclarée")
    historique = await statuts_actifs.historique(db_session, admin_isole.organisation_id, EC)
    assert [h["actif"] for h in historique] == [True, False]
    assert historique[1]["motif_annulation"] == "Remplacée par une nouvelle déclaration"


async def test_refus_motif_vide_et_date_future(db_session, admin_isole):
    await _membres(db_session, admin_isole)
    membre = await statuts_actifs.situation_du_membre(db_session, admin_isole.organisation_id, "2026", SEC)
    for motif, date_effet in ((" ", date(2026, 11, 1)), ("Motif", date(2099, 1, 1))):
        with pytest.raises(HTTPException) as refus:
            await statuts_actifs.declarer(
                db_session, admin_isole, admin_isole.organisation_id, "tenant",
                membre=membre, actif=False, date_effet=date_effet, motif=motif,
            )
        assert refus.value.status_code == 422
