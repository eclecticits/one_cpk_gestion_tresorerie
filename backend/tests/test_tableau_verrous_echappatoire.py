"""Les verrous d'immuabilité du Tableau, et la porte qu'on peut leur ouvrir.

Un snapshot scellé et une actualisation complétée sont immuables : une
commission a délibéré sur ces valeurs, elles ne doivent pas bouger dans le dos
de qui les a lues. Mais un scellement par erreur — mauvais périmètre, capture
lancée deux fois — laissait la donnée définitivement intouchable, sans autre
recours qu'un administrateur désactivant le déclencheur en production.

Ces tests installent les gardes à partir du SQL de la migration, et non d'une
copie : le schéma de test naît de `create_all()`, qui ne crée aucun déclencheur.
Sans cela, la suite reste aveugle à ce qui se joue en base.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

# Le schéma de test naît de `create_all()` : sans cet import, les tables du
# Tableau ne sont pas déclarées et n'existent pas quand ce fichier tourne seul.
from app.modules.tableau import models as tableau_models  # noqa: F401
from test_budget_engagements import _org, _user


def _migration(nom: str):
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _poser_les_gardes(db, *, avec_echappatoire: bool):
    """Installe fonctions et déclencheurs tels que les migrations les définissent."""
    mig = _migration("20260916_verrous_tableau_echappatoire")
    await db.execute(text(mig._garde_snapshot(avec_echappatoire=avec_echappatoire)))
    await db.execute(text(mig._garde_actualisation(avec_echappatoire=avec_echappatoire)))
    for sql in (
        "DROP TRIGGER IF EXISTS trg_tableau_reference_snapshot_immutable ON tableau_reference_snapshots",
        "CREATE TRIGGER trg_tableau_reference_snapshot_immutable BEFORE UPDATE OR DELETE"
        " ON tableau_reference_snapshots FOR EACH ROW EXECUTE FUNCTION tableau_guard_reference_snapshot()",
        "DROP TRIGGER IF EXISTS trg_tableau_actualisation_immutable ON tableau_actualisations",
        "CREATE TRIGGER trg_tableau_actualisation_immutable BEFORE UPDATE OR DELETE"
        " ON tableau_actualisations FOR EACH ROW EXECUTE FUNCTION tableau_guard_actualisation()",
    ):
        await db.execute(text(sql))
    await db.flush()


async def _snapshot_scelle(db) -> int:
    """Un snapshot déjà scellé, écrit avant que les gardes ne soient posées."""
    org = await _org(db)
    auteur = await _user(db, org)
    res = await db.execute(text(
        """
        INSERT INTO tableau_reference_snapshots
            (created_by, captured_at, sealed_at, source_name, scope_type,
             registry_checksum, member_count)
        VALUES (:auteur, now(), now(), 'experts_comptables', 'NATIONAL', :somme, 0)
        RETURNING id
        """
    ), {"auteur": auteur.id, "somme": "a" * 64})
    return res.scalar_one()


@pytest.mark.asyncio
async def test_un_snapshot_scelle_reste_intouchable(db_session):
    """La règle d'abord : sans annonce, rien ne bouge."""
    sid = await _snapshot_scelle(db_session)
    await _poser_les_gardes(db_session, avec_echappatoire=True)

    with pytest.raises(DBAPIError) as err:
        await db_session.execute(
            text("UPDATE tableau_reference_snapshots SET member_count = 99 WHERE id = :i"),
            {"i": sid},
        )
        await db_session.flush()
    assert "immutable" in str(err.value)


@pytest.mark.asyncio
async def test_l_administrateur_peut_desceller_un_snapshot(db_session):
    """Un scellement par erreur cesse d'être définitif.

    `onec.admin_reset` est le drapeau déjà utilisé par l'outil de remise à zéro
    et par le verrou des lignes de réquisition : on n'en invente pas un second.
    """
    sid = await _snapshot_scelle(db_session)
    await _poser_les_gardes(db_session, avec_echappatoire=True)

    await db_session.execute(text("SET LOCAL onec.admin_reset = 'on'"))
    await db_session.execute(
        text("UPDATE tableau_reference_snapshots SET sealed_at = NULL WHERE id = :i"),
        {"i": sid},
    )
    await db_session.flush()

    reste = (await db_session.execute(
        text("SELECT sealed_at FROM tableau_reference_snapshots WHERE id = :i"), {"i": sid}
    )).scalar_one()
    assert reste is None


@pytest.mark.asyncio
async def test_sans_l_echappatoire_le_verrou_ne_cede_pas(db_session):
    """Contrôle de la garde elle-même : c'est bien le drapeau qui ouvre, rien d'autre.

    Si ce test cessait d'échouer, le précédent ne prouverait plus rien.
    """
    sid = await _snapshot_scelle(db_session)
    await _poser_les_gardes(db_session, avec_echappatoire=False)

    await db_session.execute(text("SET LOCAL onec.admin_reset = 'on'"))
    with pytest.raises(DBAPIError) as err:
        await db_session.execute(
            text("UPDATE tableau_reference_snapshots SET sealed_at = NULL WHERE id = :i"),
            {"i": sid},
        )
        await db_session.flush()
    assert "immutable" in str(err.value)
