"""Un retour en trésorerie doit se voir : au budget, et sur l'export.

Rendre un reliquat n'est pas un geste symbolique. Tant que le retour n'a pas
diminué le poste budgétaire, la dépense reste comptée deux fois — une fois
sortie, jamais revenue — et l'export signé annonce plus de dépenses qu'il n'y en
a eu. Ce fichier vérifie la chaîne entière, du retour enregistré jusqu'à la
ligne négative du classeur.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.exports import construire_classeur_sorties_fonds
from app.api.v1.endpoints.retours_caisse import create_retour_caisse
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.service import Service
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.retour_caisse import RetourCaisseCreate

MOMENT = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)


async def _contexte(db):
    org = Organisation(nom="Retours", slug=f"ret-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.VOTE)
    service = Service(
        organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Secrétariat", is_active=True
    )
    user = User(
        id=uuid.uuid4(),
        email=f"ret-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        organisation_id=org.id,
    )
    db.add_all([exercice, service, user])
    db.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("10000"), solde_cdf=0))
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"II.{uuid.uuid4().hex[:3]}",
        libelle="Frais de mission",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("100000"),
        montant_engage=Decimal("0"),
        # La sortie a déjà été payée : c'est ce montant que le retour doit
        # ramener en arrière.
        montant_paye=Decimal("1000"),
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    sortie = SortieFonds(
        organisation_id=org.id,
        type_sortie="requisition",
        montant_paye=Decimal("1000"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Avance de mission",
        beneficiaire="Agent en mission",
        statut="VALIDE",
        date_paiement=MOMENT,
        created_by=user.id,
        budget_poste_id=poste.id,
        service_id=service.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )
    db.add(sortie)
    await db.commit()
    return org, user, poste, sortie


class _FausseRequete:
    """`get_request_ip` lit l'en-tête ; le journal n'a pas besoin de plus."""

    headers: dict = {}
    client = None


@pytest.mark.asyncio
async def test_le_retour_diminue_le_poste_budgetaire(db_session):
    """Sans cet ajustement, l'argent revient en caisse mais le budget continue
    de compter une dépense qui n'a pas eu lieu."""
    org, user, poste, sortie = await _contexte(db_session)

    await create_retour_caisse(
        payload=RetourCaisseCreate(
            sortie_fonds_id=sortie.id,
            montant=Decimal("400"),
            type_retour="reliquat_avance",
            motif="Reliquat de mission",
        ),
        request=_FausseRequete(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    rafraichi = (
        await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))
    ).scalar_one()
    await db_session.refresh(rafraichi)
    assert rafraichi.montant_paye == Decimal("600.00")  # 1000 payés − 400 rendus


@pytest.mark.asyncio
async def test_le_retour_apparait_en_negatif_dans_l_export(db_session):
    """C'est la ligne que la comptabilité cherche : la dépense brute, puis ce
    qui en est revenu. Sans elle, le classeur signé annonce plus de dépenses
    qu'il n'y en a eu."""
    org, user, _poste, sortie = await _contexte(db_session)
    await create_retour_caisse(
        payload=RetourCaisseCreate(
            sortie_fonds_id=sortie.id,
            montant=Decimal("400"),
            type_retour="reliquat_avance",
            motif="Reliquat de mission",
        ),
        request=_FausseRequete(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    classeur, _nom = await construire_classeur_sorties_fonds(db_session, org.id)
    feuille = classeur["Sorties"]
    lignes = [[c.value for c in ligne] for ligne in feuille.iter_rows()]
    retours = [l for l in lignes if any(isinstance(v, str) and "RETOUR" in v for v in l)]

    assert retours, "l'export ne contient aucune ligne de retour"
    montants = [v for v in retours[0] if isinstance(v, (int, float)) and v < 0]
    assert montants and Decimal(str(montants[0])) == Decimal("-400")


@pytest.mark.asyncio
async def test_un_retour_sans_poste_ne_touche_pas_au_budget(db_session):
    """`ajuste_budget=False` rend l'argent sans corriger l'imputation : la
    trésorerie remonte, le budget reste tel quel. C'est un choix, pas un oubli —
    mais il explique un retour « invisible » au budget."""
    org, user, poste, sortie = await _contexte(db_session)

    retour = await create_retour_caisse(
        payload=RetourCaisseCreate(
            sortie_fonds_id=sortie.id,
            montant=Decimal("400"),
            type_retour="correction",
            ajuste_budget=False,
            motif="Correction sans imputation",
        ),
        request=_FausseRequete(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    rafraichi = (
        await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))
    ).scalar_one()
    await db_session.refresh(rafraichi)
    assert rafraichi.montant_paye == Decimal("1000.00")  # inchangé
    assert retour.ajuste_budget is False


@pytest.mark.asyncio
async def test_le_retour_est_bien_enregistre(db_session):
    """La table doit porter la ligne : c'est d'elle que vivent l'export, le
    calcul budgétaire et le suivi de trésorerie."""
    org, user, _poste, sortie = await _contexte(db_session)
    await create_retour_caisse(
        payload=RetourCaisseCreate(
            sortie_fonds_id=sortie.id,
            montant=Decimal("250.50"),
            type_retour="trop_percu",
            motif="Trop perçu",
        ),
        request=_FausseRequete(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    lignes = (
        await db_session.execute(
            select(RetourCaisse).where(RetourCaisse.organisation_id == org.id)
        )
    ).scalars().all()

    assert len(lignes) == 1
    assert lignes[0].montant == Decimal("250.50")
    assert lignes[0].statut == "VALIDE"
