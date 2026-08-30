"""Le super administrateur peut tout, sans exception et sans entretien.

La garantie n'est pas *donnée* au super_admin, elle est *structurelle* : chaque
porte de contrôle le laisse passer sur son rôle, **avant** toute lecture de la
table des permissions. Il n'a donc besoin d'aucune ligne dans
`role_permissions` — et c'est ce qui fait qu'une permission créée demain, ou un
rôle inventé l'an prochain, lui est acquis sans qu'on y touche.

L'alternative — lui attribuer toutes les permissions en base — aurait exigé une
migration à chaque nouveau code, et une seule oubliée aurait creusé un trou
silencieux.

Ces tests verrouillent les deux moitiés de la promesse :

1. **elle tient aujourd'hui** : un super_admin sans `role_id` et sans aucune
   permission franchit toutes les gardes, y compris sur des codes qui n'existent
   pas ;
2. **elle tiendra demain** : toute fonction de garde ajoutée plus tard doit
   porter le court-circuit. Le dernier test le vérifie sur le source.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import has_any_permission, has_permission, require_module, require_roles
from app.api.v1.endpoints.dossiers_requisition import _get_user_permission_codes
from app.api.v1.endpoints.encaissements import _user_has_permission as perm_encaissements
from app.api.v1.endpoints.hr import _user_has_permission as perm_hr
from app.api.v1.endpoints.ordres_decaissement import _user_has_permission as perm_ordres
from app.api.v1.endpoints.permissions import get_menu_permissions
from app.api.v1.endpoints.sorties_fonds import _user_has_permission as perm_sorties
from app.core.permissions import ALL_MENUS
from app.models.organisation import Organisation
from app.models.user import User
from app.services.service_access import has_module_menu_access, user_has_permission

#: Un code qui n'existe nulle part — ni en base, ni dans le catalogue. Il tient
#: lieu de « permission inventée l'an prochain ».
CODE_INEXISTANT = "permission_qui_n_existe_pas_encore"


async def _super_admin(db):
    """Un super administrateur DÉPOURVU de tout : ni rôle RBAC, ni permission.

    C'est le point du test : s'il passe quand même, c'est que la garantie ne
    dépend d'aucune donnée à entretenir.
    """
    org = Organisation(nom="Omnipotence", slug=f"sa-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(
        id=uuid.uuid4(), email=f"sa{uuid.uuid4().hex[:6]}@ex.com",
        role="super_admin", role_id=None,
        prenom="Grace", nom="Hopper", organisation_id=org.id,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


# ---------------------------------------------------------------------------
# 1. La promesse tient aujourd'hui
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toutes_les_fonctions_de_controle_le_laissent_passer(db_session):
    user = await _super_admin(db_session)

    for nom, fonction in (
        ("service_access.user_has_permission", user_has_permission),
        ("sorties_fonds._user_has_permission", perm_sorties),
        ("encaissements._user_has_permission", perm_encaissements),
        ("hr._user_has_permission", perm_hr),
        ("ordres_decaissement._user_has_permission", perm_ordres),
    ):
        assert await fonction(db_session, user, CODE_INEXISTANT) is True, nom

    assert await has_module_menu_access(db_session, user, "menu_qui_n_existe_pas") is True
    assert await _get_user_permission_codes(user, db_session) == {"*"}


@pytest.mark.asyncio
async def test_les_dependances_de_route_le_laissent_passer(db_session):
    """Y compris `require_roles([])`, dont la liste n'autorise personne."""
    user = await _super_admin(db_session)

    assert await has_permission(CODE_INEXISTANT)(user=user, db=db_session) is user
    assert await has_any_permission([CODE_INEXISTANT])(user=user, db=db_session) is user
    assert await require_roles([])(user=user) is user
    assert await require_module("module_qui_n_existe_pas")(user=user, db=db_session) is user


@pytest.mark.asyncio
async def test_l_interface_lui_ouvre_tous_les_menus(db_session):
    """Le backend peut bien tout autoriser : si `/permissions/menu` ne le dit
    pas, le frontend masque les boutons et l'utilisateur reste bloqué."""
    user = await _super_admin(db_session)

    reponse = await get_menu_permissions(user=user, db=db_session)
    assert reponse["is_admin"] is True
    assert set(reponse["menus"]) == set(ALL_MENUS)


@pytest.mark.asyncio
async def test_un_role_inconnu_ne_passe_pas(db_session):
    """Le contre-test : sans le rôle, rien de tout cela n'est accordé.

    Sinon les tests ci-dessus passeraient même si les gardes ne gardaient rien.
    """
    user = await _super_admin(db_session)
    user.role = "role_invente_par_un_client"
    await db_session.commit()

    assert await user_has_permission(db_session, user, CODE_INEXISTANT) is False
    assert await perm_sorties(db_session, user, CODE_INEXISTANT) is False
    with pytest.raises(HTTPException) as erreur:
        await has_permission(CODE_INEXISTANT)(user=user, db=db_session)
    assert erreur.value.status_code == 403


# ---------------------------------------------------------------------------
# 2. La promesse tiendra demain
# ---------------------------------------------------------------------------


def test_toute_garde_future_doit_porter_le_court_circuit():
    """Garde-fou de convention, sur le source.

    Une fonction de garde ajoutée plus tard sans court-circuit creuserait un
    trou qu'aucun test métier ne révélerait — le super_admin cesserait de passer
    à un seul endroit, et seulement pour ce chemin-là.

    La règle : toute fonction dont le nom annonce une garde
    (`*has_permission*`, `*require_*`, `*is_admin*`) **et qui reçoit un
    utilisateur** doit mentionner `super_admin`, ou déléguer à un assistant qui
    le fait (`_is_admin`, `_is_admin_user`).

    Le paramètre `user` est ce qui distingue une garde d'accès d'une simple
    validation : `require_requisition_lines` vérifie une réquisition,
    `is_admin_host` un nom d'hôte — ni l'une ni l'autre ne décide de ce qu'une
    personne a le droit de faire. Ce n'est pas une preuve, c'est un filet sur la
    convention de nommage du dépôt, à élargir si la convention change.
    """
    import ast
    import pathlib

    racine = pathlib.Path(__file__).resolve().parents[1] / "app"
    marqueurs = ("super_admin", "_is_admin(", "_is_admin_user(")
    manquantes: list[str] = []

    for fichier in racine.rglob("*.py"):
        source = fichier.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nom = noeud.name.lower()
            est_une_garde = (
                "has_permission" in nom or nom.startswith("require_") or "is_admin" in nom
            )
            if not est_une_garde:
                continue
            # Une garde d'accès reçoit la personne dont elle juge les droits —
            # dans sa propre signature, ou dans la dépendance qu'elle fabrique.
            parametres: set[str] = set()
            for interne in ast.walk(noeud):
                if isinstance(interne, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parametres.update(a.arg for a in interne.args.args)
                    parametres.update(a.arg for a in interne.args.kwonlyargs)
            if not parametres & {"user", "current_user"}:
                continue

            corps = ast.get_source_segment(source, noeud) or ""
            if not any(marqueur in corps for marqueur in marqueurs):
                manquantes.append(f"{fichier.relative_to(racine.parent)}::{noeud.name}")

    assert not manquantes, (
        "Ces gardes ne laissent pas passer le super administrateur :\n  "
        + "\n  ".join(sorted(manquantes))
    )
