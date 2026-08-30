"""Ce qui attend un validateur, et ce qui n'a rien à y faire.

Cette route est interrogée en boucle par l'interface et déclenche un signal
sonore. Deux façons de la rater : compter trop — le signal sonne pour du
travail qui n'est pas le sien, et on apprend à l'ignorer — ou compter trop peu,
et le dossier attend sans que personne ne le sache.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.api.v1.endpoints.alertes import resume_a_valider
from app.models.organisation import Organisation
from app.models.rbac import Permission, Role, role_permissions
from app.models.remboursement_transport import RemboursementTransport
from app.models.requisition import Requisition
from app.models.user import User


async def _org(db):
    org = Organisation(nom="Alertes", slug=f"al-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


@pytest_asyncio.fixture
async def registre(db_session):
    """`roles` et `permissions` sont GLOBALES : ce qu'un test y laisse, les
    autres le voient. `test_secretariat_module` affirme par exemple que la table
    des permissions ne contient que des codes secrétariat — une affirmation
    qu'un test voisin fait tomber sans jamais toucher au secrétariat, et
    seulement quand l'ordre d'exécution les croise."""
    cree: dict[str, list[int]] = {"roles": [], "permissions": []}
    yield cree
    for role_id in cree["roles"]:
        await db_session.execute(
            update(User).where(User.role_id == role_id).values(role_id=None))
        await db_session.execute(
            role_permissions.delete().where(role_permissions.c.role_id == role_id))
        await db_session.execute(delete(Role).where(Role.id == role_id))
    for permission_id in cree["permissions"]:
        await db_session.execute(
            role_permissions.delete().where(role_permissions.c.permission_id == permission_id))
        await db_session.execute(delete(Permission).where(Permission.id == permission_id))
    await db_session.commit()


async def _valideur(db, org, registre, *, avec_droit=True):
    """Un utilisateur dont le droit de valider vient d'une PERMISSION, pas du rôle."""
    role = Role(code=f"r-{uuid.uuid4().hex[:8]}", label="Rôle d'essai")
    db.add(role)
    await db.flush()
    registre["roles"].append(role.id)
    if avec_droit:
        code = "can_verify_technical"
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=code)
            db.add(permission)
            await db.flush()
            registre["permissions"].append(permission.id)
        await db.execute(
            role_permissions.insert().values(role_id=role.id, permission_id=permission.id))
    user = User(
        id=uuid.uuid4(), email=f"v{uuid.uuid4().hex[:6]}@ex.com",
        # Rôle volontairement neutre : c'est la permission qui doit décider.
        role="validateur", role_id=role.id,
        prenom="Alan", nom="Turing", organisation_id=org.id,
    )
    db.add(user)
    await db.commit()
    return user


async def _requisition(db, org, *, statut, quand=None, transport=False):
    req = Requisition(
        organisation_id=org.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Dossier", mode_paiement="cash", type_requisition="classique",
        status=statut, montant_total=Decimal("100"), devise="USD",
    )
    if quand is not None:
        req.created_at = quand
    db.add(req)
    await db.flush()
    if transport:
        db.add(RemboursementTransport(
            organisation_id=org.id, requisition_id=req.id,
            numero_remboursement=f"RT-{uuid.uuid4().hex[:8]}",
            instance="Commission", type_reunion="ordinaire",
            nature_reunion="Séance", lieu="Kinshasa",
            date_reunion=datetime.now(timezone.utc), montant_total=Decimal("50"),
        ))
    await db.commit()
    return req


@pytest.mark.asyncio
async def test_seuls_les_dossiers_qui_attendent_un_validateur_sont_comptes(db_session, registre):
    """`AUTORISEE` et `APPROUVEE` ont DÉJÀ été validées : elles attendent la caisse.

    Les compter ferait sonner l'alerte pour le travail de quelqu'un d'autre —
    la façon la plus sûre de rendre un signal inaudible.
    """
    org = await _org(db_session)
    user = await _valideur(db_session, org, registre)
    for statut in ("EN_ATTENTE", "EN_ATTENTE_COMMISSION", "PENDING_VALIDATION_IMPORT"):
        await _requisition(db_session, org, statut=statut)
    for statut in ("AUTORISEE", "APPROUVEE", "PAYEE", "REJETEE"):
        await _requisition(db_session, org, statut=statut)

    resume = await resume_a_valider(user=user, tenant_id=org.id, db=db_session)
    assert resume["nb"] == 3


@pytest.mark.asyncio
async def test_les_dossiers_de_transport_sont_distingues(db_session, registre):
    """Ils n'ont pas d'état propre : ils suivent la réquisition qui les porte."""
    org = await _org(db_session)
    user = await _valideur(db_session, org, registre)
    await _requisition(db_session, org, statut="EN_ATTENTE", transport=True)
    await _requisition(db_session, org, statut="EN_ATTENTE")

    resume = await resume_a_valider(user=user, tenant_id=org.id, db=db_session)
    assert (resume["nb"], resume["dont_transport"]) == (2, 1)


@pytest.mark.asyncio
async def test_l_horodatage_rendu_est_celui_de_la_derniere_arrivee(db_session, registre):
    """C'est lui qui distingue « il y a du travail » de « il vient d'en arriver ».

    Sans cette distinction, l'interface sonnerait à chaque tour d'horloge tant
    qu'une pile n'est pas vidée.
    """
    org = await _org(db_session)
    user = await _valideur(db_session, org, registre)
    ancien = datetime.now(timezone.utc) - timedelta(days=2)
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _requisition(db_session, org, statut="EN_ATTENTE", quand=ancien)
    await _requisition(db_session, org, statut="EN_ATTENTE", quand=recent)

    resume = await resume_a_valider(user=user, tenant_id=org.id, db=db_session)
    assert resume["dernier"] is not None
    assert abs((datetime.fromisoformat(resume["dernier"]) - recent).total_seconds()) < 2


@pytest.mark.asyncio
async def test_qui_ne_valide_pas_recoit_des_zeros_et_non_une_erreur(db_session, registre):
    """L'interface interroge cette route pour tout le monde.

    Refuser bruyamment obligerait chaque écran à savoir d'avance qui a le droit
    de demander — et ferait remonter des 403 dans la console de gens qui n'ont
    rien demandé.
    """
    org = await _org(db_session)
    sans_droit = await _valideur(db_session, org, registre, avec_droit=False)
    await _requisition(db_session, org, statut="EN_ATTENTE")

    resume = await resume_a_valider(user=sans_droit, tenant_id=org.id, db=db_session)
    assert resume == {"nb": 0, "dont_transport": 0, "dernier": None, "peut_valider": False}


@pytest.mark.asyncio
async def test_les_dossiers_d_une_autre_organisation_ne_comptent_pas(db_session, registre):
    org = await _org(db_session)
    voisine = await _org(db_session)
    user = await _valideur(db_session, org, registre)
    await _requisition(db_session, voisine, statut="EN_ATTENTE")

    resume = await resume_a_valider(user=user, tenant_id=org.id, db=db_session)
    assert resume["nb"] == 0
