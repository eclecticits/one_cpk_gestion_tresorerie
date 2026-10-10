"""Un retour en trésorerie apparaît le jour où l'argent revient.

Scénario d'origine : une avance de transport de 100 est décaissée le 15/09 ;
le 01/10, 30 non utilisés sont rendus. Les données passées ne bougent pas : la
sortie reste au 15/09 avec ses 100. Le retour, lui, doit se voir le 01/10 :
le résumé le comptait déjà, mais aucune liste ne le montrait, et le relevé de
trésorerie l'ignorait — son solde divergeait de celui de la caisse.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.reports import journal_tresorerie, retours, summary
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

AVANCE_LE = datetime(2026, 9, 15, 10, tzinfo=timezone.utc)
RETOUR_LE = datetime(2026, 10, 1, 11, tzinfo=timezone.utc)


async def _avance_puis_retour(db):
    org = Organisation(nom="Retours", slug=f"ret-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"r{uuid.uuid4().hex[:6]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    avance = SortieFonds(
        organisation_id=org.id,
        type_sortie="autre",
        reference_numero=f"SF-{uuid.uuid4().hex[:6]}",
        montant_paye=Decimal("100"),
        date_paiement=AVANCE_LE,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        motif="Remboursement transport réunion",
        beneficiaire="Participants",
    )
    db.add(avance)
    await db.flush()
    db.add(
        RetourCaisse(
            organisation_id=org.id,
            sortie_fonds_id=avance.id,
            type_retour="reliquat_avance",
            reference_numero=f"RT-{uuid.uuid4().hex[:6]}",
            motif="Transport non utilisé",
            montant=Decimal("30"),
            devise="USD",
            canal="CAISSE",
            mode="cash",
            date_retour=RETOUR_LE,
            statut="VALIDE",
        )
    )
    await db.commit()
    return org, user, avance


@pytest.fixture
def sans_cache(monkeypatch):
    async def no_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.reports.cache_get", no_cache)
    monkeypatch.setattr("app.api.v1.endpoints.reports.cache_set", no_cache)


@pytest.mark.asyncio
async def test_le_retour_figure_au_jour_ou_l_argent_revient(db_session, sans_cache):
    org, user, avance = await _avance_puis_retour(db_session)

    jour = await retours(date_debut="2026-10-01", date_fin="2026-10-01", user=user, db=db_session, tenant_id=org.id)
    assert len(jour) == 1
    ligne = jour[0]
    assert ligne.montant == Decimal("30")
    # La ligne rappelle la sortie qu'elle corrige, sans la modifier.
    assert ligne.sortie_reference == avance.reference_numero
    assert ligne.sortie_date == AVANCE_LE
    assert ligne.sortie_montant == Decimal("100")
    assert ligne.reste_a_justifier_apres == Decimal("70")

    # Le jour de l'avance ne montre aucun retour.
    assert await retours(date_debut="2026-09-15", date_fin="2026-09-15", user=user, db=db_session, tenant_id=org.id) == []

    resume = await summary(date_debut="2026-10-01", date_fin="2026-10-01", user=user, db=db_session, tenant_id=org.id)
    assert sum((l.montant for l in jour), Decimal("0")) == resume.stats.totals.retours_total


@pytest.mark.asyncio
async def test_le_releve_porte_le_retour_a_sa_date_et_dans_son_solde(db_session):
    org, user, avance = await _avance_puis_retour(db_session)

    releve = await journal_tresorerie(
        canal="CAISSE", devise="USD", date_debut="2026-09-01", date_fin="2026-10-31",
        user=user, db=db_session, tenant_id=org.id,
    )
    lignes = {l.type_operation: l for l in releve.lignes}
    assert lignes["SORTIE"].date == AVANCE_LE and lignes["SORTIE"].sortie == Decimal("100")
    assert lignes["RETOUR"].date == RETOUR_LE and lignes["RETOUR"].entree == Decimal("30")
    assert avance.reference_numero in lignes["RETOUR"].libelle and "15/09/2026" in lignes["RETOUR"].libelle
    assert releve.solde_final == releve.solde_initial - Decimal("70")

    # Un relevé qui commence après le retour l'a dans son solde de départ.
    apres = await journal_tresorerie(
        canal="CAISSE", devise="USD", date_debut="2026-10-02", date_fin="2026-10-31",
        user=user, db=db_session, tenant_id=org.id,
    )
    assert apres.solde_initial == releve.solde_final


@pytest.mark.asyncio
async def test_le_journal_dit_qui_a_recu_et_qui_a_rendu(db_session):
    """Le comptable lisait le motif seul : la parenthèse nomme la personne."""
    org, user, _avance = await _avance_puis_retour(db_session)

    releve = await journal_tresorerie(
        canal="CAISSE", devise="USD", date_debut="2026-09-01", date_fin="2026-10-31",
        user=user, db=db_session, tenant_id=org.id,
    )
    lignes = {l.type_operation: l for l in releve.lignes}

    sortie = lignes["SORTIE"]
    assert sortie.libelle == "Remboursement transport réunion (payé à Participants)"
    assert sortie.libelle_base == "Remboursement transport réunion"
    assert sortie.precision == "payé à Participants"
    assert sortie.tiers == "Participants"

    retour = lignes["RETOUR"]
    assert retour.libelle.startswith("Retour en trésorerie — Transport non utilisé (rendu par Participants · sur ")
    assert retour.tiers == "Participants"
