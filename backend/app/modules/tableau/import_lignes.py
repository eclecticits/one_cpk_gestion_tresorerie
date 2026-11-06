"""Relecture d'un import : ses lignes telles que le fichier Excel les portait.

Les colonnes sont celles du fichier, dans son ordre (`colonnes_source`, gardé à
l'import puisque `raw_data` en JSONB ne le conserve pas). Rien n'est recalculé :
c'est ce qui a été importé, avec les signalements posés à la normalisation.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from .excel_import import _strip_accents
from .models import TableauSourceRow
from .repository import _sans_accents_sql, get_import


def _texte(valeur: Any) -> str | None:
    if valeur is None:
        return None
    texte = str(valeur)
    # Les dates passées par openpyxl arrivent en ISO avec une heure nulle.
    if len(texte) == 19 and texte.endswith("T00:00:00"):
        annee, mois, jour = texte[:10].split("-")
        return f"{jour}/{mois}/{annee}"
    return texte


def _sans_accents(texte: str) -> str:
    return _strip_accents(texte).lower()


async def lignes_import(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    *,
    feuille: str | None = None,
    recherche: str | None = None,
    signalees: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    colonnes_par_feuille: dict[str, list[str]] = (imp.metadata_json or {}).get("colonnes_source") or {}

    base = [TableauSourceRow.import_id == imp.id, TableauSourceRow.organisation_id == organisation_id]
    comptes = (await db.execute(
        select(TableauSourceRow.feuille, func.count())
        .where(*base)
        .group_by(TableauSourceRow.feuille)
    )).all()
    lignes_par_feuille = {nom: total for nom, total in comptes}
    # L'ordre des feuilles est celui du classeur ; une feuille sans colonnes connues vient après.
    feuilles = [nom for nom in colonnes_par_feuille if nom in lignes_par_feuille]
    feuilles += sorted(nom for nom in lignes_par_feuille if nom not in colonnes_par_feuille)
    if not feuilles:
        return {
            "import_id": imp.id, "source_type": imp.source_type, "feuilles": [], "feuille": None,
            "colonnes": [], "total": 0, "total_signalees": 0, "limit": limit, "offset": offset, "lignes": [],
        }
    courante = feuille if feuille in feuilles else feuilles[0]

    filtres = [*base, TableauSourceRow.feuille == courante]
    # Une ligne sans erreur porte un `null` JSON (pas un NULL SQL) : on ne mesure que les tableaux.
    erreurs = TableauSourceRow.normalization_errors
    signalee = case(
        (func.jsonb_typeof(erreurs) == "array", func.jsonb_array_length(erreurs)),
        else_=0,
    ) > 0
    total_signalees = (await db.execute(select(func.count()).where(*filtres, signalee))).scalar_one()
    if signalees:
        filtres.append(signalee)
    if (recherche or "").split():
        # Les valeurs seulement : chercher « Assureur » ne doit pas ramener toutes les lignes.
        valeurs = (
            select(func.string_agg(literal_column("value"), " "))
            .select_from(func.jsonb_each_text(TableauSourceRow.raw_data))
            .scalar_subquery()
        )
        for mot in recherche.split():
            filtres.append(_sans_accents_sql(valeurs).like(f"%{_sans_accents(mot)}%"))
    total = (await db.execute(select(func.count()).where(*filtres))).scalar_one()
    rows = (await db.execute(
        select(TableauSourceRow)
        .where(*filtres)
        .order_by(TableauSourceRow.line_number.asc(), TableauSourceRow.id.asc())
        .limit(limit)
        .offset(offset)
    )).scalars().all()

    colonnes = list(colonnes_par_feuille.get(courante) or [])
    # Une clé présente dans les lignes mais absente de l'en-tête mémorisé reste visible.
    for row in rows:
        for cle in row.raw_data or {}:
            if cle not in colonnes:
                colonnes.append(cle)
    return {
        "import_id": imp.id,
        "source_type": imp.source_type,
        "feuilles": [{"nom": nom, "lignes": lignes_par_feuille.get(nom, 0)} for nom in feuilles],
        "feuille": courante,
        "colonnes": colonnes,
        "total": total,
        "total_signalees": total_signalees,
        "limit": limit,
        "offset": offset,
        "lignes": [
            {
                "id": row.id,
                "ligne": row.line_number,
                "valeurs": [_texte((row.raw_data or {}).get(colonne)) for colonne in colonnes],
                "signalements": list(dict.fromkeys(
                    str(erreur.get("message")) for erreur in (row.normalization_errors or [])
                    if isinstance(erreur, dict) and erreur.get("message")
                )),
            }
            for row in rows
        ],
    }
