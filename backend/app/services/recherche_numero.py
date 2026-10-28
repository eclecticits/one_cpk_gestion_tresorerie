"""Recherche d'une sortie de fonds ou d'un retour par son numéro.

Une sortie et ses retours se cherchent ensemble : taper le numéro de l'une
fait apparaître les autres. Le caissier qui tient un reçu de retour veut voir
la sortie qu'il corrige, et l'inverse — et l'export doit dire la même chose
que l'écran.

Le numéro attribué (`reference_numero`, ex. PAY-ADM-2026-00239) et la
référence externe saisie (`reference`, ex. un n° de chèque) sont tous deux
cherchés, sans tenir compte de la casse ni des espaces autour.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds


def motif(numero: str | None) -> str | None:
    """Le motif `ILIKE` d'une saisie, ou `None` si elle est vide."""
    texte = (numero or "").strip() if isinstance(numero, str) else ""
    if not texte:
        return None
    if len(texte) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Saisissez au moins 3 caractères pour rechercher un numéro.",
        )
    echappe = texte.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{echappe}%"


def _sortie_porte(p: str) -> ColumnElement[bool]:
    return or_(
        SortieFonds.reference_numero.ilike(p, escape="\\"),
        SortieFonds.reference.ilike(p, escape="\\"),
    )


def _retour_porte(p: str) -> ColumnElement[bool]:
    return or_(
        RetourCaisse.reference_numero.ilike(p, escape="\\"),
        RetourCaisse.reference.ilike(p, escape="\\"),
    )


def condition_sortie(p: str) -> ColumnElement[bool]:
    """La sortie porte ce numéro, ou l'un de ses retours le porte."""
    return or_(
        _sortie_porte(p),
        SortieFonds.id.in_(select(RetourCaisse.sortie_fonds_id).where(_retour_porte(p))),
    )


def condition_retour(p: str) -> ColumnElement[bool]:
    """Le retour porte ce numéro, ou la sortie qu'il corrige le porte."""
    return or_(
        _retour_porte(p),
        RetourCaisse.sortie_fonds_id.in_(select(SortieFonds.id).where(_sortie_porte(p))),
    )
