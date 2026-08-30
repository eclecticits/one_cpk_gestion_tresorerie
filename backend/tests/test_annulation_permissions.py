"""Qui peut annuler une opération financière ?

`20260428_fin_cancel` a créé `cancel_sortie_fonds` et `cancel_encaissement`
sans les attribuer à aucun rôle, et la route d'annulation d'une sortie portait
en plus un `require_roles(["admin", "tresorerie", "comptabilite"])` dont les
deux derniers codes n'existent pas — les rôles réels sont `tresorier` et
`comptable`. Résultat : la permission dédiée n'était jamais atteinte, et seuls
les comptes `admin` annulaient, par court-circuit de rôle.

Ces tests verrouillent la règle qui remplace tout ça : **la permission décide,
et elle seule**. Un rôle qui la porte annule, quel que soit son nom ; un rôle
qui ne la porte pas est refusé, quel que soit son nom.

Ils verrouillent aussi la décision d'organisation, portée par
`20260902_annul_secr_compta` : **annulent l'administrateur, le secrétaire
exécutif et le comptable**. Pas le caissier — celui qui saisit ne défait pas —
ni le trésorier, qui valide.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.api.v1.endpoints.sorties_fonds import update_sortie_statut
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.rbac import Permission, Role, role_permissions
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

MOMENT = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


class _FakeRequest:
    headers: dict = {}
    client = None


@pytest_asyncio.fixture
async def registre(db_session):
    """Ce que le test insère dans les tables GLOBALES, retiré après lui.

    `roles` et `permissions` n'ont pas de colonne `organisation_id` : une ligne
    laissée là est visible par tous les autres tests. `test_secretariat_module`
    affirme par exemple que la table des permissions ne contient QUE des codes
    secrétariat — une affirmation qu'un test voisin fait tomber sans jamais
    toucher au secrétariat, et seulement quand l'ordre d'exécution les croise.
    """
    cree: dict[str, list[int]] = {"roles": [], "permissions": []}
    yield cree
    for role_id in cree["roles"]:
        # Détacher d'abord les utilisateurs : `users.role_id` porte une clé
        # étrangère sans ON DELETE, et les supprimer eux cascaderait sur les
        # opérations qu'ils ont créées.
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


async def _permission(db, code: str, registre: dict) -> Permission:
    existante = await db.scalar(select(Permission).where(Permission.code == code))
    if existante is not None:
        # Déjà en place : ce n'est pas à ce test de la retirer.
        return existante
    permission = Permission(code=code, description=code)
    db.add(permission)
    await db.flush()
    registre["permissions"].append(permission.id)
    return permission


async def _role(db, *, code: str, permissions: tuple[str, ...], registre: dict) -> Role:
    role = Role(code=f"{code}-{uuid.uuid4().hex[:8]}", label=code)
    db.add(role)
    await db.flush()
    registre["roles"].append(role.id)
    for nom in permissions:
        permission = await _permission(db, nom, registre)
        await db.execute(
            role_permissions.insert().values(role_id=role.id, permission_id=permission.id)
        )
    return role


async def _contexte(db, *, role_utilisateur: str, permissions: tuple[str, ...], registre: dict):
    """Une organisation, un compte, une caisse, et un utilisateur au rôle donné."""
    org = Organisation(nom="Annulation", slug=f"an-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    role = await _role(db, code=role_utilisateur, permissions=permissions, registre=registre)
    user = User(
        id=uuid.uuid4(), email=f"a{uuid.uuid4().hex[:6]}@ex.com",
        # `role` est la chaîne libre que lisait `require_roles` ; `role_id` porte
        # les vraies permissions. Les deux sont volontairement dissociés ici.
        role=role_utilisateur, role_id=role.id,
        prenom="Ada", nom="Byron", organisation_id=org.id,
    )
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db.add_all([user, banque])
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
    await db.commit()
    return org, user


async def _sortie(db, org, user):
    sortie = SortieFonds(
        organisation_id=org.id, type_sortie="autre", montant_paye=Decimal("60"),
        mode_paiement="cash", devise="USD", canal="CAISSE",
        motif="Dépense", beneficiaire="Fournisseur", statut="VALIDE",
        date_paiement=MOMENT, created_by=user.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )
    db.add(sortie)
    await db.commit()
    await db.refresh(sortie)
    return sortie


async def _annuler(db, org, user, sortie):
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    return await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Saisie en double"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )


@pytest.mark.asyncio
async def test_un_role_porteur_de_la_permission_peut_annuler(db_session, registre):
    """Le nom du rôle ne décide plus, la permission décide.

    Le rôle utilisé ici ne figurait dans aucune liste en dur : il annule parce
    qu'il porte `cancel_sortie_fonds`, et pour aucune autre raison. C'est ce qui
    rend le droit attribuable sans toucher au code.
    """
    org, user = await _contexte(
        db_session, role_utilisateur="controleur", permissions=("cancel_sortie_fonds",), registre=registre)
    sortie = await _sortie(db_session, org, user)

    rendu = await _annuler(db_session, org, user, sortie)
    assert rendu.statut == "ANNULEE"
    assert rendu.motif_annulation == "Saisie en double"


@pytest.mark.parametrize("role_habilite", ["secretaire_executif", "comptable"])
@pytest.mark.asyncio
async def test_les_roles_habilites_annulent(db_session, registre, role_habilite):
    """Le secrétaire exécutif et le comptable, tels que la migration les dote.

    Ils portaient déjà `view_cancelled_financial_operations` : ils peuvent donc
    relire ce qu'ils annulent. Un droit d'annuler sans droit de voir aurait fait
    disparaître l'opération de l'écran de celui qui vient de l'annuler.
    """
    org, user = await _contexte(
        db_session, role_utilisateur=role_habilite,
        permissions=("menu_sorties_fonds", "cancel_sortie_fonds",
                     "view_cancelled_financial_operations"),
        registre=registre)
    sortie = await _sortie(db_session, org, user)

    rendu = await _annuler(db_session, org, user, sortie)
    assert rendu.statut == "ANNULEE"


@pytest.mark.asyncio
async def test_le_caissier_n_annule_rien(db_session, registre):
    """Décision d'organisation : celui qui saisit ne défait pas.

    Le caissier porte le menu et le droit d'exécuter un paiement, jamais celui
    d'annuler. Ce test échouera le jour où quelqu'un lui accordera
    `cancel_sortie_fonds` — c'est exactement ce qu'on veut qu'il fasse.
    """
    org, user = await _contexte(
        db_session, role_utilisateur="caissier",
        permissions=("menu_sorties_fonds", "can_execute_payment"), registre=registre)
    sortie = await _sortie(db_session, org, user)

    with pytest.raises(HTTPException) as erreur:
        await _annuler(db_session, org, user, sortie)
    assert erreur.value.status_code == 403
    assert "cancel_sortie_fonds" in str(erreur.value.detail)


@pytest.mark.asyncio
async def test_un_role_sans_la_permission_est_refuse(db_session, registre):
    """Y compris un rôle dont le nom ressemble à ceux de l'ancienne liste.

    `comptable` aurait été refusé par l'ancienne liste (qui disait
    « comptabilite ») ; il l'est toujours, mais pour la bonne raison.
    """
    org, user = await _contexte(
        db_session, role_utilisateur="comptable", permissions=("menu_sorties_fonds",), registre=registre)
    sortie = await _sortie(db_session, org, user)

    with pytest.raises(HTTPException) as erreur:
        await _annuler(db_session, org, user, sortie)
    assert erreur.value.status_code == 403
    assert "cancel_sortie_fonds" in str(erreur.value.detail)


@pytest.mark.asyncio
async def test_l_admin_annule_toujours_sans_permission_explicite(db_session, registre):
    """Le court-circuit de rôle d'`_user_has_permission` reste en place : le
    retrait de `require_roles` ne devait rien retirer à personne."""
    org, user = await _contexte(db_session, role_utilisateur="admin", permissions=(), registre=registre)
    sortie = await _sortie(db_session, org, user)

    rendu = await _annuler(db_session, org, user, sortie)
    assert rendu.statut == "ANNULEE"


@pytest.mark.asyncio
async def test_le_tresorier_reste_refuse_tant_qu_il_n_a_pas_la_permission(db_session, registre):
    """La séparation des tâches n'est pas défaite par ce changement : c'est le
    caissier qui reçoit le droit d'annuler, pas tous les profils financiers."""
    org, user = await _contexte(
        db_session, role_utilisateur="tresorier",
        permissions=("can_verify_technical", "can_validate_final", "menu_sorties_fonds"),
        registre=registre)
    sortie = await _sortie(db_session, org, user)

    with pytest.raises(HTTPException) as erreur:
        await _annuler(db_session, org, user, sortie)
    assert erreur.value.status_code == 403
