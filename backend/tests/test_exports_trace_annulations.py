"""Ce qui est annulé ou supprimé se voit dans l'export, et ne compte pas.

Une annulation défait l'effet d'une opération, pas son existence. Les exports
retiraient les lignes annulées : la trace — qui, quand, pourquoi — disparaissait
avec elles, alors que c'est elle qu'un contrôle vient chercher. Ces tests
verrouillent la règle commune : la ligne reste, grisée et barrée, avec son
motif ; les totaux n'en tiennent pas compte ; un onglet la rassemble avec les
autres opérations défaites.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.exports import (
    TRACE_HEADERS,
    construire_classeur_encaissements,
    construire_classeur_requisitions,
    construire_classeur_sorties_fonds,
    inclure_trace_pour,
)
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

HEADER_ROW = 4
QUAND = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)


async def _org_et_auteur(db_session, role: str = "admin"):
    org = Organisation(nom="Trace", slug=f"trace-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"trace-{uuid.uuid4().hex[:6]}@example.com",
        nom="MUKENDI",
        prenom="Paul",
        role=role,
        organisation_id=org.id,
    )
    db_session.add(user)
    await db_session.flush()
    return org, user


def _lignes(ws) -> list[dict]:
    """Les lignes de données, par en-tête, jusqu'à la ligne TOTAL exclue."""
    entetes = [c.value for c in ws[HEADER_ROW]]
    lignes = []
    for row in ws.iter_rows(min_row=HEADER_ROW + 1):
        if row[0].value == "TOTAL":
            break
        lignes.append({h: c for h, c in zip(entetes, row)})
    return lignes


def _total(ws, entete: str):
    entetes = [c.value for c in ws[HEADER_ROW]]
    col = entetes.index(entete)
    for row in ws.iter_rows(min_row=HEADER_ROW + 1):
        if row[0].value == "TOTAL":
            return row[col].value, ws.cell(row=row[0].row + 1, column=1).value
    raise AssertionError("ligne TOTAL absente")


def _encaissement(org, **kw) -> Encaissement:
    base = dict(
        organisation_id=org.id,
        type_client="personne_physique",
        client_nom="MUELA Joyeux",
        libelle="Cotisation annuelle",
        montant=Decimal("500"),
        montant_total=Decimal("500"),
        montant_paye=Decimal("500"),
        montant_percu=Decimal("500"),
        devise_perception="USD",
        canal="CAISSE",
        statut_paiement="complet",
        mode_paiement="cash",
        est_proforma=False,
        is_deleted=False,
        statut_operation="ACTIVE",
        date_encaissement=QUAND,
    )
    base.update(kw)
    return Encaissement(**base)


@pytest.mark.asyncio
async def test_une_note_annulee_reste_dans_l_export_sans_compter(db_session):
    org, user = await _org_et_auteur(db_session)
    active = _encaissement(org, numero_recu="ND-T-1")
    annulee = _encaissement(
        org,
        numero_recu="ND-T-2",
        montant=Decimal("3989"),
        montant_total=Decimal("3989"),
        montant_paye=Decimal("0"),
        montant_percu=Decimal("0"),
        statut_paiement="non_paye",
        statut_operation="ANNULEE",
        motif_annulation="erreur de saisie",
        annulee_le=QUAND,
        annulee_par_id=user.id,
    )
    db_session.add_all([active, annulee])
    await db_session.flush()

    wb, _ = await construire_classeur_encaissements(db_session, org.id, inclure_annulations=True)
    ws = wb["Encaissements"]
    lignes = {l["N° Note de débit"].value: l for l in _lignes(ws)}

    assert set(lignes) == {"ND-T-1", "ND-T-2"}, "la note annulée doit rester dans la liste"
    trace = lignes["ND-T-2"]
    assert trace["Statut"].value == "ANNULÉ"
    assert trace[TRACE_HEADERS[0]].value == "erreur de saisie"
    assert trace[TRACE_HEADERS[1]].value
    assert trace[TRACE_HEADERS[2]].value == "Paul MUKENDI"
    assert trace["Client"].font.strike, "une ligne annulée se lit barrée"
    assert not lignes["ND-T-1"]["Client"].font.strike

    total, note = _total(ws, "Montant total (USD)")
    assert total == pytest.approx(500.0), "le total ne compte que l'active"
    assert note and "1 annulée" in note and "3 989,00" in note

    journal = _lignes(wb["Journal des annulations"])
    assert [l["Référence"].value for l in journal] == ["ND-T-2"]
    assert journal[0]["Motif"].value == "erreur de saisie"


@pytest.mark.asyncio
async def test_sans_la_trace_l_export_reste_celui_des_actives(db_session):
    org, user = await _org_et_auteur(db_session)
    db_session.add_all([
        _encaissement(org, numero_recu="ND-A-1"),
        _encaissement(org, numero_recu="ND-A-2", statut_operation="ANNULEE"),
    ])
    await db_session.flush()

    wb, _ = await construire_classeur_encaissements(db_session, org.id, inclure_annulations=False)

    assert [l["N° Note de débit"].value for l in _lignes(wb["Encaissements"])] == ["ND-A-1"]
    assert "Journal des annulations" not in wb.sheetnames


@pytest.mark.asyncio
async def test_la_trace_suit_le_droit_de_voir_les_annulees(db_session):
    """Un export ne montre pas plus que l'écran."""
    _, admin = await _org_et_auteur(db_session, role="admin")
    _, sans_droit = await _org_et_auteur(db_session, role="caissier")

    assert await inclure_trace_pour(db_session, admin, True) is True
    assert await inclure_trace_pour(db_session, admin, False) is False
    assert await inclure_trace_pour(db_session, sans_droit, True) is False


@pytest.mark.asyncio
async def test_une_sortie_ou_un_retour_annule_reste_sans_compter(db_session):
    org, user = await _org_et_auteur(db_session)
    valide = SortieFonds(
        organisation_id=org.id,
        type_sortie="directe",
        montant_paye=Decimal("100"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Collation",
        beneficiaire="Traiteur",
        statut="VALIDE",
        date_paiement=QUAND,
        created_by=user.id,
        reference="SF-VALIDE",
    )
    annulee = SortieFonds(
        organisation_id=org.id,
        type_sortie="directe",
        montant_paye=Decimal("70"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Transport",
        beneficiaire="Chauffeur",
        statut="ANNULEE",
        motif_annulation="doublon",
        annulee_le=QUAND,
        annulee_par_id=user.id,
        date_paiement=QUAND,
        created_by=user.id,
        reference="SF-ANNULEE",
    )
    db_session.add_all([valide, annulee])
    await db_session.flush()
    retour_annule = RetourCaisse(
        organisation_id=org.id,
        sortie_fonds_id=valide.id,
        type_retour="reliquat_avance",
        montant=Decimal("30"),
        devise="USD",
        canal="CAISSE",
        mode="cash",
        statut="ANNULEE",
        motif_annulation="saisi à tort",
        annulee_le=QUAND,
        annulee_par_id=user.id,
        date_retour=QUAND,
        reference_numero="RET-ANNULE",
        created_by=user.id,
    )
    db_session.add(retour_annule)
    await db_session.flush()

    wb, _ = await construire_classeur_sorties_fonds(db_session, org.id, inclure_annulations=True)
    ws = wb["Sorties"]
    lignes = {l["Référence"].value: l for l in _lignes(ws)}

    assert {"SF-VALIDE", "SF-ANNULEE", "RET-ANNULE"} <= set(lignes)
    assert lignes["SF-ANNULEE"][TRACE_HEADERS[0]].value == "doublon"
    assert lignes["SF-ANNULEE"]["Motif"].font.strike
    total, note = _total(ws, "Montant payé (USD)")
    assert total == pytest.approx(100.0), "ni la sortie ni le retour annulés ne comptent"
    assert note and "2 annulées" in note

    journal = {l["Référence"].value for l in _lignes(wb["Journal des annulations"])}
    assert journal == {"SF-ANNULEE", "RET-ANNULE"}


@pytest.mark.asyncio
async def test_une_requisition_rejetee_ou_supprimee_reste_sans_compter(db_session):
    org, user = await _org_et_auteur(db_session)

    def _req(numero, montant, **kw):
        return Requisition(
            organisation_id=org.id,
            numero_requisition=numero,
            objet=f"Objet {numero}",
            montant_total=Decimal(montant),
            mode_paiement="cash",
            created_by=user.id,
            **kw,
        )

    db_session.add_all([
        _req("REQ-T-1", "200", status="PAYEE"),
        _req("REQ-T-2", "900", status="REJETEE", motif_rejet="hors budget"),
        _req(
            "REQ-T-3", "50", status="BROUILLON",
            is_deleted=True, deleted_at=QUAND, deleted_by=user.id,
        ),
    ])
    await db_session.flush()

    wb, _ = await construire_classeur_requisitions(db_session, org.id, inclure_annulations=True)
    ws = wb["Réquisitions"]
    lignes = {l["N° Réquisition"].value: l for l in _lignes(ws)}

    assert set(lignes) == {"REQ-T-1", "REQ-T-2", "REQ-T-3"}
    assert lignes["REQ-T-2"][TRACE_HEADERS[0]].value == "hors budget"
    assert lignes["REQ-T-3"][TRACE_HEADERS[2]].value == "Paul MUKENDI"
    total, note = _total(ws, "Montant total (USD)")
    assert total == pytest.approx(200.0)
    assert note and "1 rejetée" in note and "1 supprimée" in note

    # Sans la trace : la supprimée disparaît, la rejetée reste listée mais ne
    # compte toujours pas.
    wb, _ = await construire_classeur_requisitions(db_session, org.id, inclure_annulations=False)
    lignes = {l["N° Réquisition"].value for l in _lignes(wb["Réquisitions"])}
    assert lignes == {"REQ-T-1", "REQ-T-2"}
    assert _total(wb["Réquisitions"], "Montant total (USD)")[0] == pytest.approx(200.0)
