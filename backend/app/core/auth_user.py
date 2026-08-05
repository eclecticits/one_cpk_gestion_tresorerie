from __future__ import annotations

"""Identité de l'appelant résolue par ``get_current_user``.

Le contexte d'authentification est mis en cache (Redis) pour éviter de rejouer
les requêtes rôle/permissions/services à chaque requête HTTP. L'objet rendu par
la dépendance n'est donc **pas** une instance ORM ``User`` : il n'est rattaché à
aucune session, ne porte aucune relation et ne peut pas être persisté.

Ce type le rend explicite plutôt que de laisser un ``SimpleNamespace`` se faire
passer pour un ``User`` — une classe déclarée échoue à l'attribution d'un
attribut inconnu (``slots``) au lieu de la laisser passer silencieusement.
"""

import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class AuthUser:
    """Utilisateur authentifié, reconstruit depuis le contexte (caché ou frais)."""

    id: uuid.UUID
    email: str | None = None
    nom: str | None = None
    prenom: str | None = None
    role: str = ""
    role_id: int | None = None
    service_id: int | None = None
    organisation_id: int | None = None
    active: bool = False
    must_change_password: bool = False
    is_first_login: bool = False
    is_email_verified: bool = False
    permission_codes: frozenset[str] = field(default_factory=frozenset)
    service_ids: tuple[int, ...] = ()

    @classmethod
    def from_context(cls, ctx: dict) -> "AuthUser":
        return cls(
            id=uuid.UUID(str(ctx["user_id"])),
            email=ctx.get("email"),
            nom=ctx.get("nom"),
            prenom=ctx.get("prenom"),
            role=ctx.get("role") or "",
            role_id=ctx.get("role_id"),
            service_id=ctx.get("service_id"),
            organisation_id=ctx.get("organisation_id"),
            active=bool(ctx.get("active")),
            must_change_password=bool(ctx.get("must_change_password")),
            is_first_login=bool(ctx.get("is_first_login")),
            is_email_verified=bool(ctx.get("is_email_verified")),
            permission_codes=frozenset(ctx.get("permissions") or ()),
            service_ids=tuple(ctx.get("service_ids") or ()),
        )


def cached_permission_codes(user: object) -> frozenset[str] | None:
    """Permissions résolues en amont, ou ``None`` si l'appelant n'est pas un AuthUser.

    ``None`` signifie « inconnu, interroger la base » et se distingue de
    ``frozenset()`` qui signifie « aucune permission ».
    """
    if isinstance(user, AuthUser):
        return user.permission_codes
    return None


def cached_service_ids(user: object) -> tuple[int, ...] | None:
    """Services résolus en amont, ou ``None`` si l'appelant n'est pas un AuthUser."""
    if isinstance(user, AuthUser):
        return user.service_ids
    return None
