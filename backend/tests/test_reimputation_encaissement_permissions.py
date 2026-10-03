"""Qui peut corriger le poste budgétaire d'un encaissement ?

C'est une permission à attribution explicite : personne ne la tient de sa
fonction, administrateur compris. Elle se règle rôle par rôle dans
Paramètres → Permissions. Par défaut : le secrétaire exécutif et le comptable,
comme pour l'annulation — ni le caissier, qui saisit, ni le trésorier, qui
valide. Seul le super-administrateur, qui règle ces droits, la tient d'office.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.deps import has_permission
from app.models.user import User

from test_annulation_permissions import _role, registre  # noqa: F401 — fixture partagée

CODE = "treso.encaissements.reimputer"
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migration(nom: str):
    spec = importlib.util.spec_from_file_location(nom, VERSIONS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _utilisateur(db, *, role_utilisateur: str, permissions: tuple[str, ...], registre: dict) -> User:
    role = await _role(db, code=role_utilisateur, permissions=permissions, registre=registre)
    user = User(
        id=uuid.uuid4(), email=f"r{uuid.uuid4().hex[:6]}@ex.com",
        role=role_utilisateur, role_id=role.id, prenom="Ada", nom="Byron",
    )
    db.add(user)
    await db.flush()
    return user


async def _peut_reimputer(db, user) -> bool:
    try:
        await has_permission(CODE)(user=user, db=db)
    except HTTPException as erreur:
        assert erreur.status_code == 403
        return False
    return True


def test_les_roles_sont_ceux_qui_annulent():
    """Le droit suit celui d'annuler : si l'un change, l'autre doit être revu."""
    reimputer = _migration("20261003_reimput_enc_roles")
    annuler = _migration("20260902_annulation_secretaire_comptable")
    assert set(reimputer.ROLES) == set(annuler.ROLES) == {"secretaire_executif", "comptable"}
    assert "caissier" not in reimputer.ROLES and "tresorier" not in reimputer.ROLES


@pytest.mark.asyncio
async def test_la_migration_accorde_le_droit_aux_roles_designes(db_session, registre):
    migration = _migration("20261003_reimput_enc_roles")
    habilite = await _utilisateur(db_session, role_utilisateur="comptable", permissions=(), registre=registre)
    temoin = await _utilisateur(db_session, role_utilisateur="caissier", permissions=(), registre=registre)
    code_habilite = (await db_session.execute(text("SELECT code FROM roles WHERE id = :id"), {"id": habilite.role_id})).scalar_one()
    # La permission existe déjà en base (migration précédente) ou est créée ici.
    await _role(db_session, code="porteur", permissions=(CODE,), registre=registre)

    for requete, params in migration.instructions(roles=(code_habilite,)):
        await db_session.execute(text(requete), params)
    await db_session.flush()

    assert await _peut_reimputer(db_session, habilite)
    assert not await _peut_reimputer(db_session, temoin)


@pytest.mark.parametrize("role_habilite", ["secretaire_executif", "comptable"])
@pytest.mark.asyncio
async def test_les_roles_habilites_corrigent(db_session, registre, role_habilite):
    user = await _utilisateur(db_session, role_utilisateur=role_habilite, permissions=(CODE,), registre=registre)
    assert await _peut_reimputer(db_session, user)


@pytest.mark.parametrize(
    ("role_refuse", "permissions"),
    [
        ("caissier", ("menu_encaissements", "treso.encaissements.create")),
        ("tresorier", ("menu_encaissements", "can_validate_final")),
    ],
)
@pytest.mark.asyncio
async def test_le_caissier_et_le_tresorier_ne_corrigent_pas(db_session, registre, role_refuse, permissions):
    """Celui qui saisit ne défait pas ; celui qui valide non plus."""
    user = await _utilisateur(db_session, role_utilisateur=role_refuse, permissions=permissions, registre=registre)
    assert not await _peut_reimputer(db_session, user)


@pytest.mark.asyncio
async def test_l_admin_ne_la_tient_pas_de_son_role(db_session, registre):
    """Le court-circuit administrateur ne l'ouvre pas : il faut l'avoir reçue."""
    user = await _utilisateur(db_session, role_utilisateur="admin", permissions=(), registre=registre)
    assert not await _peut_reimputer(db_session, user)
    # Il garde en revanche tout le reste : le court-circuit vaut pour les autres codes.
    await has_permission("cancel_encaissement")(user=user, db=db_session)


@pytest.mark.asyncio
async def test_l_admin_l_a_quand_son_role_l_a_recue(db_session, registre):
    user = await _utilisateur(db_session, role_utilisateur="admin", permissions=(CODE,), registre=registre)
    assert await _peut_reimputer(db_session, user)


@pytest.mark.asyncio
async def test_le_super_admin_la_tient_d_office(db_session, registre):
    user = await _utilisateur(db_session, role_utilisateur="super_admin", permissions=(), registre=registre)
    assert await _peut_reimputer(db_session, user)


@pytest.mark.asyncio
async def test_le_menu_ne_la_donne_a_l_admin_que_s_il_l_a_recue(db_session, registre):
    """L'interface affiche le bouton d'après `permissions`, pas d'après `is_admin`."""
    from app.api.v1.endpoints.permissions import get_menu_permissions

    sans = await _utilisateur(db_session, role_utilisateur="admin", permissions=(), registre=registre)
    menu = await get_menu_permissions(user=sans, db=db_session)
    assert menu["is_admin"] is True
    assert CODE in menu["explicit_permissions"]
    assert CODE not in menu["permissions"]

    avec = await _utilisateur(db_session, role_utilisateur="admin", permissions=(CODE,), registre=registre)
    assert CODE in (await get_menu_permissions(user=avec, db=db_session))["permissions"]


@pytest.mark.asyncio
async def test_regler_le_role_admin_ne_touche_qu_aux_permissions_explicites(db_session, registre):
    """Cocher la case pour l'administrateur ne doit pas effacer ses autres droits."""
    from app.api.v1.endpoints.admin import update_role_permissions
    from app.models.rbac import Permission, Role, role_permissions
    from app.schemas.rbac import RolePermissionsPayload
    from sqlalchemy import select

    from test_annulation_permissions import _FakeRequest, _permission

    admin = (await db_session.execute(select(Role).where(Role.code == "admin"))).scalar_one_or_none()
    if admin is None:
        admin = Role(code="admin", label="Administrateur")
        db_session.add(admin)
        await db_session.flush()
        registre["roles"].append(admin.id)
    autre = await _permission(db_session, "cancel_encaissement", registre)
    await _permission(db_session, CODE, registre)

    async def codes() -> set[str]:
        res = await db_session.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == admin.id)
        )
        return {row[0] for row in res.all()}

    avant = await codes()
    if autre.code not in avant:
        await db_session.execute(role_permissions.insert().values(role_id=admin.id, permission_id=autre.id))
    super_admin = await _utilisateur(db_session, role_utilisateur="super_admin", permissions=(), registre=registre)
    try:
        # L'écran envoie la case explicite cochée, plus des codes qu'il ne
        # devrait pas pouvoir régler pour l'admin : ceux-là sont ignorés.
        await update_role_permissions(
            payload=RolePermissionsPayload(roles=[{"role_id": admin.id, "permission_codes": [CODE]}]),
            request=_FakeRequest(), current_user=super_admin, db=db_session,
        )
        apres = await codes()
        assert CODE in apres
        assert autre.code in apres, "les autres droits de l'admin ne sont pas effacés"

        await update_role_permissions(
            payload=RolePermissionsPayload(roles=[{"role_id": admin.id, "permission_codes": []}]),
            request=_FakeRequest(), current_user=super_admin, db=db_session,
        )
        apres = await codes()
        assert CODE not in apres
        assert autre.code in apres
    finally:
        # Le rôle admin est global : on lui rend exactement ses droits d'avant.
        await db_session.execute(role_permissions.delete().where(role_permissions.c.role_id == admin.id))
        for code in avant:
            perm = (await db_session.execute(select(Permission).where(Permission.code == code))).scalar_one()
            await db_session.execute(role_permissions.insert().values(role_id=admin.id, permission_id=perm.id))
        await db_session.commit()
