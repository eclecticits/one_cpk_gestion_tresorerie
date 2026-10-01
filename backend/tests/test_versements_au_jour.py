"""Un complément de paiement apparaît le jour où il est versé.

Scénario d'origine : une note de 100 est payée 40 le 10, puis complétée de 60
le 15. Le détail du rapport et l'export Excel listaient les NOTES à leur date
d'émission avec leur cumul payé : le 15, aucune ligne alors que le total du
résumé comptait bien 60 ; le 10, une ligne de 100 alors que 40 seulement
étaient entrés. Le relevé de trésorerie, lui, regroupait la note sur la date
de son premier versement : sur une période couvrant les deux jours, le
complément était ramené au 10.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.exports import construire_classeur_encaissements
from app.api.v1.endpoints.reports import journal_tresorerie, summary, versements
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.payment_history import PaymentHistory
from app.models.user import User

ACOMPTE_LE = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
COMPLEMENT_LE = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)


async def _note_payee_en_deux_fois(db):
    org = Organisation(nom="Versements", slug=f"vers-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"v{uuid.uuid4().hex[:6]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    note = Encaissement(
        organisation_id=org.id,
        numero_recu=f"ND-{uuid.uuid4().hex[:6]}",
        type_client="personne_physique",
        client_nom="Client Partiel",
        libelle="Prestation",
        montant=Decimal("100"),
        montant_total=Decimal("100"),
        montant_paye=Decimal("100"),
        montant_percu=Decimal("100"),
        devise_perception="USD",
        taux_change_applique=Decimal("1"),
        canal="CAISSE",
        statut_paiement="complet",
        statut_operation="ACTIVE",
        mode_paiement="cash",
        date_encaissement=ACOMPTE_LE,
    )
    db.add(note)
    await db.flush()
    for montant, le in ((Decimal("40"), ACOMPTE_LE), (Decimal("60"), COMPLEMENT_LE)):
        db.add(
            PaymentHistory(
                organisation_id=org.id,
                encaissement_id=note.id,
                montant=montant,
                devise="USD",
                canal="CAISSE",
                mode_paiement="cash",
                date_paiement=le,
                statut="ACTIF",
            )
        )
    await db.commit()
    return org, user, note


@pytest.fixture
def sans_cache(monkeypatch):
    async def no_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.reports.cache_get", no_cache)
    monkeypatch.setattr("app.api.v1.endpoints.reports.cache_set", no_cache)


@pytest.mark.asyncio
async def test_le_complement_figure_au_jour_de_son_versement(db_session, sans_cache):
    org, user, note = await _note_payee_en_deux_fois(db_session)

    jour = await versements(
        date_debut="2026-09-15", date_fin="2026-09-15", user=user, db=db_session, tenant_id=org.id
    )
    assert [(l.numero_recu, l.montant_paye, l.nature_versement) for l in jour] == [
        (note.numero_recu, Decimal("60"), "Solde")
    ]
    assert jour[0].rang == 2 and jour[0].nombre_versements == 2
    assert jour[0].reste_apres == Decimal("0")

    # Le jour de l'acompte ne montre que l'acompte, pas l'argent reçu ensuite.
    veille = await versements(
        date_debut="2026-09-10", date_fin="2026-09-10", user=user, db=db_session, tenant_id=org.id
    )
    assert [(l.montant_paye, l.nature_versement, l.reste_apres) for l in veille] == [
        (Decimal("40"), "Acompte", Decimal("60"))
    ]


@pytest.mark.asyncio
async def test_le_detail_somme_exactement_le_total_du_resume(db_session, sans_cache):
    org, user, _note = await _note_payee_en_deux_fois(db_session)

    for debut, fin in (("2026-09-10", "2026-09-10"), ("2026-09-15", "2026-09-15"), ("2026-09-01", "2026-09-30")):
        lignes = await versements(date_debut=debut, date_fin=fin, user=user, db=db_session, tenant_id=org.id)
        resume = await summary(date_debut=debut, date_fin=fin, user=user, db=db_session, tenant_id=org.id)
        assert sum((l.montant_paye for l in lignes), Decimal("0")) == resume.stats.totals.encaissements_total


@pytest.mark.asyncio
async def test_le_releve_ne_ramene_plus_le_complement_au_jour_de_l_acompte(db_session):
    org, user, note = await _note_payee_en_deux_fois(db_session)

    releve = await journal_tresorerie(
        canal="CAISSE",
        devise="USD",
        date_debut="2026-09-01",
        date_fin="2026-09-30",
        user=user,
        db=db_session,
        tenant_id=org.id,
    )
    entrees = [(l.date, l.entree) for l in releve.lignes if l.type_operation == "ENCAISSEMENT"]
    assert sorted(entrees) == [(ACOMPTE_LE, Decimal("40")), (COMPLEMENT_LE, Decimal("60"))]
    complement = next(l for l in releve.lignes if l.date == COMPLEMENT_LE)
    assert "Solde 2/2" in complement.libelle and note.numero_recu in complement.libelle


@pytest.mark.asyncio
async def test_l_export_excel_porte_le_complement_dans_la_feuille_versements(db_session):
    org, _user, note = await _note_payee_en_deux_fois(db_session)

    classeur, _nom = await construire_classeur_encaissements(
        db_session, org.id, date_debut="2026-09-15", date_fin="2026-09-15"
    )
    # La note, émise le 10, n'est pas dans la liste des notes du 15…
    assert "Versements" in classeur.sheetnames
    valeurs = [
        cellule
        for ligne in classeur["Versements"].iter_rows(values_only=True)
        for cellule in ligne
    ]
    # … mais son complément est bien dans la feuille des versements du jour.
    assert note.numero_recu in valeurs
    assert "Solde (2/2)" in valeurs
    assert 60 in valeurs or 60.0 in valeurs
