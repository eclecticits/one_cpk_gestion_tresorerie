"""Une note qui mêle deux postes se lit poste par poste, au budget comme à l'export.

Le paiement répartissait déjà chaque versement entre les postes des articles
(cf. test_encaissement_repartition). Mais l'écran Budget, l'export du budget et
l'export des encaissements relisaient la note par son seul poste d'en-tête :
toute la recette apparaissait sur un poste, et l'export n'en montrait qu'une
ligne.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks

from app.api.v1.endpoints.budget import _active_recettes_by_poste
from app.api.v1.endpoints.exports import _parts_par_article, construire_classeur_encaissements
from app.schemas.payment import EncaissementArticleCreate, EncaissementCreate
from app.services.budget_execution import recettes_realisees_par_poste
from app.services.encaissement_payments import record_encaissement_payment

from test_encaissement_repartition import _contexte


def test_les_parts_somment_a_la_note_au_centime():
    articles = [
        {"libelle": "A", "montant": Decimal("10"), "poste_id": 1, "poste_label": "P1"},
        {"libelle": "B", "montant": Decimal("10"), "poste_id": 2, "poste_label": "P2"},
        {"libelle": "C", "montant": Decimal("10"), "poste_id": None, "poste_label": ""},
    ]
    parts = _parts_par_article(
        articles,
        poste_entete_id=9,
        poste_entete_label="P9",
        libelle_note="Note",
        montant_total=Decimal("10"),
        montant_paye=Decimal("10"),
        montant_percu=Decimal("10"),
    )
    assert [p["poste_label"] for p in parts] == ["P1", "P2", "P9"]
    assert [p["poste_id"] for p in parts] == [1, 2, 9]
    assert sum(p["montant_total"] for p in parts) == Decimal("10.00")
    assert sum(p["montant_paye"] for p in parts) == Decimal("10.00")


def test_une_note_sans_article_reste_une_ligne():
    parts = _parts_par_article(
        [],
        poste_entete_id=9,
        poste_entete_label="P9",
        libelle_note="Note",
        montant_total=Decimal("50"),
        montant_paye=Decimal("20"),
        montant_percu=Decimal("20"),
    )
    assert len(parts) == 1
    assert parts[0]["libelle"] == "Note"
    assert parts[0]["montant_total"] == Decimal("50.00")


async def _note_deux_postes(db, monkeypatch):
    from app.api.v1.endpoints.encaissements import create_encaissement

    async def faux_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", faux_recu)
    org, user, service, (cotisations, frais) = await _contexte(db)
    note = await create_encaissement(
        payload=EncaissementCreate(
            type_client="personne_physique", client_sexe="M",
            client_nom="Cabinet ABC",
            libelle="Cotisation et inscription",
            montant=Decimal("400"),
            montant_total=Decimal("400"),
            montant_paye=Decimal("0"),
            mode_paiement="cash",
            canal="CAISSE",
            service_id=service.id,
            budget_poste_id=cotisations.id,
            articles=[
                EncaissementArticleCreate(
                    libelle="Cotisation annuelle", quantite=1, prix_unitaire=Decimal("300"),
                    montant=Decimal("300"), budget_poste_id=cotisations.id,
                ),
                EncaissementArticleCreate(
                    libelle="Frais d'inscription", quantite=1, prix_unitaire=Decimal("100"),
                    montant=Decimal("100"), budget_poste_id=frais.id,
                ),
            ],
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.commit()
    await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=uuid.UUID(str(note["id"])), montant=Decimal("400"),
        mode_paiement="cash", reference=None, notes=None, user_id=user.id,
    )
    await db.commit()
    return org, service, cotisations, frais, note


@pytest.mark.asyncio
async def test_le_budget_credite_chaque_poste_de_sa_part(db_session, monkeypatch):
    org, service, cotisations, frais, _note = await _note_deux_postes(db_session, monkeypatch)

    attendu = {cotisations.id: Decimal("300"), frais.id: Decimal("100")}
    assert await recettes_realisees_par_poste(
        db_session, organisation_id=org.id, poste_ids=[cotisations.id, frais.id]
    ) == attendu
    # L'écran Budget (et sa vue par service) lit la même chose.
    assert await _active_recettes_by_poste(
        db_session, tenant_id=org.id, poste_ids=[cotisations.id, frais.id]
    ) == attendu
    assert await _active_recettes_by_poste(
        db_session, tenant_id=org.id, poste_ids=[cotisations.id, frais.id], service_id=service.id
    ) == attendu


def _lignes_de_la_note(classeur, numero):
    feuille = classeur["Encaissements"]
    lignes = list(feuille.iter_rows(values_only=True))
    entete_index = next(i for i, ligne in enumerate(lignes) if ligne and "Poste budgétaire" in ligne)
    entetes = lignes[entete_index]
    col = {nom: entetes.index(nom) for nom in entetes if nom}
    return [
        {nom: ligne[i] for nom, i in col.items()}
        for ligne in lignes[entete_index + 1:]
        if ligne and numero in ligne
    ], col


@pytest.mark.asyncio
async def test_l_export_donne_une_ligne_par_article(db_session, monkeypatch):
    org, _service, cotisations, frais, note = await _note_deux_postes(db_session, monkeypatch)

    classeur, _nom = await construire_classeur_encaissements(db_session, org.id)
    lignes, _col = _lignes_de_la_note(classeur, note["numero_recu"])

    assert len(lignes) == 2
    par_poste = {ligne["Poste budgétaire"]: ligne for ligne in lignes}
    assert set(par_poste) == {
        f"{cotisations.code} - {cotisations.libelle}",
        f"{frais.code} - {frais.libelle}",
    }
    cotis = par_poste[f"{cotisations.code} - {cotisations.libelle}"]
    assert cotis["Libellé"] == "Cotisation annuelle"
    assert cotis["Montant total (USD)"] == 300
    assert cotis["Montant payé (USD)"] == 300
    assert par_poste[f"{frais.code} - {frais.libelle}"]["Montant payé (USD)"] == 100


@pytest.mark.asyncio
async def test_le_filtre_par_poste_ne_garde_que_ses_lignes(db_session, monkeypatch):
    org, _service, _cotisations, frais, note = await _note_deux_postes(db_session, monkeypatch)

    # Le poste de l'article, pas celui de l'en-tête : la note doit sortir.
    classeur, _nom = await construire_classeur_encaissements(db_session, org.id, budget_poste_id=frais.id)
    lignes, _col = _lignes_de_la_note(classeur, note["numero_recu"])

    assert len(lignes) == 1
    assert lignes[0]["Poste budgétaire"] == f"{frais.code} - {frais.libelle}"
    assert lignes[0]["Montant payé (USD)"] == 100
