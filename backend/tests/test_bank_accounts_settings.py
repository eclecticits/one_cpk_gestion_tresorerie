from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.banques import create_compte_bancaire, update_compte_bancaire
from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.banque import CompteBancaireCreate, CompteBancaireUpdate


pytestmark = pytest.mark.asyncio


async def _ctx(db_session):
    suffix = uuid.uuid4().hex[:10]
    org = Organisation(nom=f"Org banques {suffix}", slug=f"org-bank-{suffix}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    user = User(email=f"bank-{suffix}@example.com", role="admin", organisation_id=org.id, active=True)
    banque = Banque(organisation_id=org.id, nom=f"TMB {suffix}", code="TMB", is_active=True)
    other_banque = Banque(organisation_id=org.id, nom=f"RAWBANK {suffix}", code="RAW", is_active=True)
    db_session.add_all([user, banque, other_banque])
    await db_session.commit()
    return org, user, banque, other_banque


async def test_create_complete_bank_account_separates_numero_and_rib(db_session):
    org, user, banque, _ = await _ctx(db_session)

    out = await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            agence_bancaire="Agence principale",
            intitule=" ORDRE NATIONAL DES EXPERTS COMPTABLES ",
            numero_compte=" 10000572352 ",
            devise="USD",
            rib="00017110001000057235224",
            identifiant_client="10729774",
            code_swift_bic="tmbccd3l",
            compte_comptable_associe="512",
            journal_comptable_associe="BQUSD",
            solde_initial=Decimal("125.50"),
            is_active=True,
            is_principal=True,
            observations="Compte TMB USD",
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert out.numero_compte == "10000572352"
    assert out.rib == "00017110001000057235224"
    assert out.rib != out.numero_compte
    assert out.code_swift_bic == "TMBCCD3L"
    assert out.solde_initial == Decimal("125.50")
    assert out.solde_actuel == Decimal("125.50")
    assert out.is_principal is True


async def test_create_bank_account_with_required_fields_only(db_session):
    org, user, banque, _ = await _ctx(db_session)

    out = await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            intitule="Compte minimal",
            numero_compte="MIN-001",
            devise="CDF",
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert out.rib is None
    assert out.solde_initial == Decimal("0")
    assert out.solde_actuel == Decimal("0")
    assert out.is_active is True


async def test_duplicate_numero_is_scoped_by_bank_and_currency(db_session):
    org, user, banque, other_banque = await _ctx(db_session)
    payload = {
        "intitule": "Compte USD",
        "numero_compte": "DUP-001",
        "devise": "USD",
    }

    await create_compte_bancaire(
        CompteBancaireCreate(banque_id=banque.id, **payload),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        await create_compte_bancaire(
            CompteBancaireCreate(banque_id=banque.id, **payload),
            tenant_id=org.id,
            user=user,
            db=db_session,
        )
    assert exc.value.status_code == 409

    same_number_other_bank = await create_compte_bancaire(
        CompteBancaireCreate(banque_id=other_banque.id, **payload),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert same_number_other_bank.numero_compte == "DUP-001"


async def test_rib_duplicate_is_rejected_when_present(db_session):
    org, user, banque, other_banque = await _ctx(db_session)

    await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            intitule="Compte 1",
            numero_compte="RIB-001",
            devise="USD",
            rib="RIB-UNIQUE-001",
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        await create_compte_bancaire(
            CompteBancaireCreate(
                banque_id=other_banque.id,
                intitule="Compte 2",
                numero_compte="RIB-002",
                devise="USD",
                rib="RIB-UNIQUE-001",
            ),
            tenant_id=org.id,
            user=user,
            db=db_session,
        )
    assert exc.value.status_code == 409


async def test_update_bank_account_and_prevent_direct_current_balance_change(db_session):
    org, user, banque, _ = await _ctx(db_session)
    account = await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            intitule="Compte avant",
            numero_compte="UPD-001",
            devise="USD",
            solde_initial=Decimal("10"),
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    updated = await update_compte_bancaire(
        account.id,
        CompteBancaireUpdate(intitule="Compte apres", rib="RIB-UPD-001", code_swift_bic="abcddddd"),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert updated.intitule == "Compte apres"
    assert updated.rib == "RIB-UPD-001"
    assert updated.code_swift_bic == "ABCDDDDD"
    assert updated.solde_actuel == Decimal("10")

    with pytest.raises(ValueError):
        CompteBancaireUpdate(solde_actuel=Decimal("999"))


async def test_principal_account_switch_demotes_previous_account(db_session):
    org, user, banque, _ = await _ctx(db_session)
    first = await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            intitule="Principal 1",
            numero_compte="PRI-001",
            devise="USD",
            is_principal=True,
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    second = await create_compte_bancaire(
        CompteBancaireCreate(
            banque_id=banque.id,
            intitule="Principal 2",
            numero_compte="PRI-002",
            devise="USD",
            is_principal=True,
        ),
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    res = await db_session.execute(select(CompteBancaire).where(CompteBancaire.id.in_([first.id, second.id])))
    rows = {row.id: row for row in res.scalars().all()}
    assert rows[first.id].is_principal is False
    assert rows[second.id].is_principal is True
