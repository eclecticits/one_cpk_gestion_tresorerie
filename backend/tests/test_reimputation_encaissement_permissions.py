"""Qui peut corriger le poste budgétaire d'un encaissement ?

Décision : les mêmes qu'annuler un encaissement — l'administrateur, le
secrétaire exécutif et le comptable. Pas le caissier, qui saisit, ni le
trésorier, qui valide. Comme pour l'annulation, la permission décide, pas le
nom du rôle.
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
async def test_l_admin_corrige_sans_permission_explicite(db_session, registre):
    user = await _utilisateur(db_session, role_utilisateur="admin", permissions=(), registre=registre)
    assert await _peut_reimputer(db_session, user)
