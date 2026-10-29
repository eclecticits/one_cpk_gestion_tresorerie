"""La caisse ne voit pas les sorties par banque.

Une sortie qui débite un compte bancaire n'existe pas pour le caissier : elle
n'est ni listée, ni comptée dans les totaux, ni annulable, ni attendue en
justificatif. Seule `sorties_fonds_banque` l'ouvre — et rien d'autre, ni le
nom du rôle ni `cancel_sortie_fonds`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.api.v1.endpoints.sorties_fonds import (
    lister_justificatifs_en_attente,
    list_sorties_fonds,
    update_sortie_statut,
)
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.rbac import Permission, Role, role_permissions
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.services import justificatifs

MOMENT = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


class _FakeRequest:
    headers: dict = {}
    client = None


@pytest_asyncio.fixture
async def registre(db_session):
    """Rôles et permissions sont globaux : on retire ce que le test a créé."""
    cree: dict[str, list[int]] = {"roles": [], "permissions": []}
    yield cree
    for role_id in cree["roles"]:
        await db_session.execute(update(User).where(User.role_id == role_id).values(role_id=None))
        await db_session.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
        await db_session.execute(delete(Role).where(Role.id == role_id))
    for permission_id in cree["permissions"]:
        await db_session.execute(
            role_permissions.delete().where(role_permissions.c.permission_id == permission_id))
        await db_session.execute(delete(Permission).where(Permission.id == permission_id))
    await db_session.commit()


async def _utilisateur(db, org, *, code: str, permissions: tuple[str, ...], registre: dict) -> User:
    role = Role(code=f"{code}-{uuid.uuid4().hex[:8]}", label=code)
    db.add(role)
    await db.flush()
    registre["roles"].append(role.id)
    for nom in permissions:
        permission = await db.scalar(select(Permission).where(Permission.code == nom))
        if permission is None:
            permission = Permission(code=nom, description=nom)
            db.add(permission)
            await db.flush()
            registre["permissions"].append(permission.id)
        await db.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission.id))
    user = User(
        id=uuid.uuid4(), email=f"c{uuid.uuid4().hex[:6]}@ex.com",
        role=code, role_id=role.id, prenom="Ada", nom="Byron", organisation_id=org.id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def contexte(db_session, registre):
    """Une sortie par la caisse, une par la banque, un caissier, un trésorier."""
    db = db_session
    org = Organisation(nom="Cloison", slug=f"cl-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    caissier = await _utilisateur(
        db, org, code="caissier", permissions=("menu_sorties_fonds", "cancel_sortie_fonds"), registre=registre)
    tresorier = await _utilisateur(
        db, org, code="tresorier", permissions=("menu_sorties_fonds", "cancel_sortie_fonds", "sorties_fonds_banque"),
        registre=registre)
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db.add(banque)
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("1000"), solde_actuel=Decimal("1000"),
        is_active=True, account_type="BANK",
    )
    db.add_all([
        compte,
        CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("1000"),
                       solde_cdf=Decimal("0"), est_ouverte=True),
    ])
    await db.flush()

    def _sortie(canal: str, montant: str) -> SortieFonds:
        return SortieFonds(
            organisation_id=org.id, type_sortie="autre", montant_paye=Decimal(montant),
            mode_paiement="cash" if canal == "CAISSE" else "virement", devise="USD", canal=canal,
            compte_bancaire_id=compte.id if canal == "BANQUE" else None,
            motif="Dépense", beneficiaire="Fournisseur", statut="VALIDE",
            date_paiement=MOMENT, created_by=tresorier.id,
            reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
            justificatif_statut=justificatifs.STATUT_ATTENDU,
        )

    par_caisse, par_banque = _sortie("CAISSE", "40"), _sortie("BANQUE", "300")
    db.add_all([par_caisse, par_banque])
    await db.commit()
    return org, caissier, tresorier, par_caisse, par_banque


async def _lister(db, org, user, **kwargs):
    parametres = dict(
        include=None, date_debut=None, date_fin=None, type_sortie=None,
        mode_paiement=None, canal=None, compte_bancaire_id=None, statut=None,
        requisition_id=None, requisition_numero=None, reference=None, numero=None,
        nature_mouvement=None, order=None, limit=100, offset=0, include_summary=True,
        user=user, tenant_id=org.id, db=db,
    )
    parametres.update(kwargs)
    return await list_sorties_fonds(**parametres)


@pytest.mark.asyncio
async def test_le_caissier_ne_voit_que_la_caisse(db_session, contexte):
    org, caissier, _, par_caisse, _ = contexte

    rendu = await _lister(db_session, org, caissier)

    assert [str(s.id) for s in rendu.items] == [str(par_caisse.id)]
    assert rendu.total == 1
    assert rendu.total_montant_paye == Decimal("40")


@pytest.mark.asyncio
async def test_le_tresorier_voit_les_deux_canaux(db_session, contexte):
    org, _, tresorier, _, _ = contexte

    rendu = await _lister(db_session, org, tresorier)

    assert rendu.total == 2
    assert rendu.total_montant_paye == Decimal("340")


@pytest.mark.asyncio
async def test_le_caissier_ne_peut_pas_demander_la_banque(db_session, contexte):
    org, caissier, _, _, _ = contexte

    with pytest.raises(HTTPException) as exc:
        await _lister(db_session, org, caissier, canal="BANQUE")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_une_sortie_par_banque_est_introuvable_pour_le_caissier(db_session, contexte):
    """Annuler suppose de la voir : `cancel_sortie_fonds` ne suffit pas."""
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    org, caissier, _, _, par_banque = contexte

    with pytest.raises(HTTPException) as exc:
        await update_sortie_statut(
            sortie_id=str(par_banque.id),
            payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur"),
            request=_FakeRequest(), user=caissier, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_justificatifs_attendus_filtres_par_canal(db_session, contexte):
    org, caissier, tresorier, par_caisse, _ = contexte

    vus_caisse = await lister_justificatifs_en_attente(db=db_session, user=caissier, tenant_id=org.id)
    vus_tresorerie = await lister_justificatifs_en_attente(db=db_session, user=tresorier, tenant_id=org.id)

    assert [str(s.id) for s in vus_caisse] == [str(par_caisse.id)]
    assert len(vus_tresorerie) == 2
