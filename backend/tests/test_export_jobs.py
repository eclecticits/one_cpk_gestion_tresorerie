"""Garde-fous de la génération d'exports en tâche de fond (phase 1).

Aucun de ces tests n'a besoin d'une base : ils portent sur les décisions —
cloisonnement, chemins, empreintes, cohérence modèle/migration — et pas sur le
comportement SQL, qui demande le harnais complet.

Le premier d'entre eux est le plus important : `session_tenant` doit REFUSER de
s'ouvrir sans organisation. Hors HTTP, l'absence de contexte ne lève rien
d'elle-même — elle produit des requêtes non filtrées, donc un classeur
contenant les données de toutes les organisations.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.api.v1.endpoints import secure_uploads
from app.api.v1.endpoints.export_jobs import PERMISSION_PAR_TYPE, VERIFICATEUR_PAR_TYPE
from app.core.auth_user import AuthUser
from app.core.config import settings
from app.models.export_job import STATUT_EN_FILE, STATUT_TERMINE, ExportJob
from app.services.export_jobs import (
    TYPES_SUPPORTES,
    chemin_relatif_artefact,
    empreinte_params,
    horodatage_peremption,
    racine_uploads,
    serialiser_job,
    types_asynchrones,
)
from app.workers.exports import MESSAGE_ECHEC_GENERIQUE, _traduire_echec
from app.workers.tenant_session import ContexteTenantManquant, session_tenant


# ── Cloisonnement ────────────────────────────────────────────────────────────


async def test_une_session_hors_http_sans_organisation_est_refusee():
    """LE test du §7 : un job sans contexte tenant doit échouer, pas produire.

    Le refus doit tomber AVANT toute connexion : rien ne doit pouvoir être lu
    sans organisation, pas même une fois.
    """
    with pytest.raises(ContexteTenantManquant):
        async with session_tenant(None):
            pytest.fail("La session ne devait pas s'ouvrir sans organisation.")


# ── Emplacement des artefacts ────────────────────────────────────────────────


def test_la_racine_des_uploads_est_celle_de_secure_uploads():
    """Deux résolutions du même répertoire : elles doivent coïncider.

    `export_jobs.racine_uploads()` duplique volontairement la résolution de
    `secure_uploads.UPLOAD_ROOT` (un service ne doit pas importer un module
    d'endpoints). Ce test est le prix de cette duplication : si l'une bouge sans
    l'autre, le worker écrit à un endroit que le téléchargement ne sait pas lire.
    """
    assert str(racine_uploads()) == secure_uploads.UPLOAD_ROOT


def test_le_chemin_de_l_artefact_est_reconnu_par_le_controle_d_appartenance():
    """L'artefact doit tomber sous le contrôle de tenant déjà existant.

    `secure_uploads._extract_tenant_uuid` lit le second segment du chemin et le
    compare à l'organisation du jeton. Si le chemin des exports ne suivait pas
    cette forme, il faudrait écrire un second contrôle d'appartenance — donc
    avoir deux endroits où se tromper.
    """
    org = uuid.uuid4()
    relatif = chemin_relatif_artefact(org, uuid.uuid4())

    assert secure_uploads._extract_tenant_uuid(relatif) == str(org)
    assert secure_uploads._path_requires_tenant_match(relatif) is True
    assert relatif.endswith(".xlsx")


# ── Déduplication ────────────────────────────────────────────────────────────


def test_l_empreinte_ignore_l_ordre_des_filtres():
    """Sinon deux clics identiques produiraient deux empreintes, donc deux jobs."""
    a = empreinte_params(7, "budget", {"annee": 2026, "type": "TOUT"})
    b = empreinte_params(7, "budget", {"type": "TOUT", "annee": 2026})
    assert a == b


def test_l_empreinte_separe_les_organisations_et_les_types():
    """Deux organisations ne doivent jamais partager un artefact."""
    base = {"annee": 2026}
    assert empreinte_params(7, "budget", base) != empreinte_params(8, "budget", base)
    assert empreinte_params(7, "budget", base) != empreinte_params(7, "requisitions", base)


# ── Drapeau de bascule ───────────────────────────────────────────────────────


def test_le_drapeau_est_ferme_par_defaut(monkeypatch):
    """Rien ne bascule tant qu'on ne l'a pas demandé explicitement."""
    monkeypatch.setattr(settings, "export_async_types", "")
    assert types_asynchrones() == set()


def test_un_type_inconnu_ne_bascule_pas(monkeypatch):
    """Une faute de frappe ne doit pas router vers un worker qui ne sait pas produire."""
    monkeypatch.setattr(settings, "export_async_types", "budget, requisitions, budgt")
    # Depuis la phase 2, les cinq types sont produits par le worker ; seul
    # `budgt` n'existe pas et doit être écarté.
    assert types_asynchrones() == {"budget", "requisitions"}


# ── Représentation rendue au client ──────────────────────────────────────────


def _job(**surcharge) -> ExportJob:
    valeurs = {
        "id": uuid.uuid4(),
        "organisation_id": 7,
        "requested_by": None,
        "type": "budget",
        "params": {"annee": 2026},
        "params_hash": "x" * 64,
        "status": STATUT_EN_FILE,
        "progress": 0,
        "row_count": None,
        "file_path": None,
        "file_name": None,
        "file_size": None,
        "error_code": None,
        "error_message": None,
        "attempts": 0,
        "lease_until": None,
        "worker_id": None,
        "created_at": datetime.now(timezone.utc),
        "started_at": None,
        "finished_at": None,
        "expires_at": None,
    }
    valeurs.update(surcharge)
    return ExportJob(**valeurs)


def test_le_lien_de_telechargement_n_apparait_que_quand_il_y_a_un_fichier():
    """Un client qui voit le lien peut le suivre : pas de statut à réinterpréter."""
    en_file = serialiser_job(_job())
    assert "download_path" not in en_file
    assert en_file["status_path"].endswith(en_file["id"])

    termine = serialiser_job(
        _job(status=STATUT_TERMINE, file_path="tenants/x/exports/y.xlsx", file_name="budget.xlsx")
    )
    assert termine["download_path"] == f"/exports/jobs/{termine['id']}/download"


def test_un_job_termine_sans_fichier_ne_propose_pas_de_lien():
    """Cas de l'artefact purgé : le job reste DONE en base tant que la purge
    n'est pas passée, mais un lien vers un fichier absent serait un piège."""
    assert "download_path" not in serialiser_job(_job(status=STATUT_TERMINE, file_path=None))


def test_la_peremption_suit_le_reglage(monkeypatch):
    monkeypatch.setattr(settings, "export_job_retention_days", 7)
    depuis = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert horodatage_peremption(depuis) == depuis + timedelta(days=7)


# ── Message d'échec rendu à l'utilisateur ────────────────────────────────────


def test_un_refus_4xx_garde_le_message_qui_permet_d_agir():
    """Le chemin synchrone rend ces messages tels quels : l'asynchrone aussi.

    Les 4xx de la construction sont écrites POUR l'utilisateur — le refus de
    plafond porte les deux nombres et l'action qui débloque. Les remplacer par
    « réessayez » laisse comme seule option de recliquer à l'identique, ce qui
    est exactement le motif observé dans les tirs de charge.
    """
    exc = HTTPException(
        status_code=413,
        detail="Export trop volumineux : 120000 lignes pour un plafond de 60000. Restreignez la période.",
    )
    code, message = _traduire_echec(exc)
    assert code == "HTTP_413"
    assert "60000" in message and "Restreignez" in message


def test_une_erreur_technique_ne_fuit_pas_dans_l_interface():
    """`repr(exc)` porterait des noms de tables et des fragments de SQL."""
    code, message = _traduire_echec(
        RuntimeError('relation "export_jobs" does not exist LINE 1: SELECT ...')
    )
    assert code == "RuntimeError"
    assert message == MESSAGE_ECHEC_GENERIQUE
    assert "export_jobs" not in message


def test_une_5xx_reste_generique():
    """Une erreur serveur ne dit rien d'actionnable à celui qui la lit."""
    code, message = _traduire_echec(HTTPException(status_code=500, detail="Internal error"))
    assert message == MESSAGE_ECHEC_GENERIQUE
    assert code == "HTTPException"


def test_le_code_d_erreur_tient_dans_la_colonne():
    """`error_code` est un VARCHAR(60) : un nom de classe plus long tronque."""
    nom = "X" * 200
    exc = type(nom, (RuntimeError,), {})()
    code, _ = _traduire_echec(exc)
    assert len(code) <= 60


# ── Cohérences qui ne se voient qu'en croisant deux fichiers ────────────────


def test_chaque_type_supporte_a_une_regle_d_acces():
    """Un type produit par le worker mais absent des deux tables devient
    inconsultable (refus par défaut). Le défaut est le bon, mais mieux vaut le
    savoir ici qu'en production, sur un artefact déjà généré."""
    for type_export in TYPES_SUPPORTES:
        assert type_export in PERMISSION_PAR_TYPE or type_export in VERIFICATEUR_PAR_TYPE, (
            f"{type_export} est produit par le worker mais n'a ni permission ni "
            "vérificateur déclaré : ses jobs seraient invisibles."
        )


def test_chaque_type_supporte_sait_etre_construit():
    """Déclarer un type supporté sans l'ajouter au dispatch du worker donnerait
    un job accepté en 202 puis échoué avec « type non pris en charge » — le pire
    des deux mondes, puisque l'utilisateur a attendu pour rien."""
    import inspect

    from app.workers import exports as taches

    source = inspect.getsource(taches.construire)
    for type_export in TYPES_SUPPORTES:
        assert f'"{type_export}"' in source, (
            f"{type_export} est déclaré supporté mais absent du dispatch de "
            "app/workers/exports.py:construire."
        )


def test_les_verificateurs_ne_recouvrent_pas_les_permissions():
    """Un type présent dans les deux tables aurait deux contrôles d'accès, dont
    un seul s'appliquerait — et lequel dépendrait de l'ordre du code."""
    assert not (set(PERMISSION_PAR_TYPE) & set(VERIFICATEUR_PAR_TYPE))


def _charger_migration():
    chemin = Path(__file__).resolve().parents[1] / "alembic/versions/20260828_export_jobs.py"
    spec = importlib.util.spec_from_file_location("migration_export_jobs", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _OpEspion:
    """Remplace `op` dans la migration pour capturer ce qu'elle déclare."""

    def __init__(self) -> None:
        self.colonnes: list[sa.Column] = []
        self.index: list[str] = []

    def create_table(self, nom, *elements, **kwargs):
        self.colonnes = [e for e in elements if isinstance(e, sa.Column)]

    def create_index(self, nom, table, colonnes, **kwargs):
        self.index.append(nom)


def test_la_migration_et_le_modele_decrivent_la_meme_table(monkeypatch):
    """Une colonne ajoutée au modèle et oubliée dans la migration ne se voit
    qu'au premier déploiement, sous la forme d'un `UndefinedColumn` en
    production. Ici elle se voit tout de suite."""
    migration = _charger_migration()
    espion = _OpEspion()
    monkeypatch.setattr(migration, "op", espion)
    migration.upgrade()

    colonnes_migration = {c.name for c in espion.colonnes}
    colonnes_modele = {c.name for c in ExportJob.__table__.columns}
    assert colonnes_migration == colonnes_modele

    nullables_migration = {c.name for c in espion.colonnes if c.nullable}
    nullables_modele = {c.name for c in ExportJob.__table__.columns if c.nullable}
    assert nullables_migration == nullables_modele

    assert set(espion.index) == {i.name for i in ExportJob.__table__.indexes}

    # Les `server_default` aussi : un défaut déclaré d'un seul côté ne casse
    # rien à l'exécution (l'ORM fournit toujours la valeur), mais il fait
    # proposer à `alembic revision --autogenerate` un `alter_column` à chaque
    # passage — et ce bruit finit par masquer une vraie divergence.
    def _defauts(colonnes) -> dict[str, str | None]:
        return {
            c.name: (str(c.server_default.arg) if c.server_default is not None else None)
            for c in colonnes
        }

    assert _defauts(espion.colonnes) == _defauts(ExportJob.__table__.columns)


# ── En-tête de téléchargement ────────────────────────────────────────────────
#
# Les deux tests ci-dessous auraient attrapé un 500 rendu APRÈS que le classeur
# a été construit et payé : Starlette encode les en-têtes en latin-1 et laisse
# passer un CRLF, et le nom de fichier des exports est bâti à partir de
# paramètres de requête bruts (`f"requisitions_{date_debut}_{date_fin}.xlsx"`)
# que `_parse_datetime` ne refuse pas quand ils sont invalides.


def test_l_entete_de_piece_jointe_survit_a_un_nom_hostile():
    """Le nom vient de paramètres de requête : il doit être encodable en latin-1."""
    from app.api.v1.endpoints.exports import entete_piece_jointe

    for hostile in ('a"b.xlsx', "a\r\nX-Injecte: 1", "requisitions_€_fin.xlsx", "a b\\c"):
        entete = entete_piece_jointe(hostile)
        entete.encode("latin-1")  # ce que fait Starlette : ne doit pas lever
        assert "\r" not in entete and "\n" not in entete
        assert entete.count('"') == 2  # les guillemets du nom, et eux seuls


def test_l_entete_de_piece_jointe_preserve_les_noms_legitimes():
    """La liste blanche ne doit pas défigurer ce que produisent les exports."""
    from app.api.v1.endpoints.exports import entete_piece_jointe

    for legitime in (
        "budget_2026_TOUT.xlsx",
        "requisitions_2026-01-01_2026-12-31.xlsx",
        "experts_comptables.xlsx",
    ):
        assert entete_piece_jointe(legitime) == f'attachment; filename="{legitime}"'


def test_un_nom_de_fichier_vide_reste_telechargeable():
    """Un nom entièrement filtré ne doit pas produire `filename=""`."""
    from app.api.v1.endpoints.exports import entete_piece_jointe

    assert entete_piece_jointe("€€€") == 'attachment; filename="export.xlsx"'


# ── Liste des jobs : le LIMIT doit porter sur ce qui est visible ─────────────


class _SessionFiltrante:
    """Session minimale qui honore le filtre de type et le LIMIT du SELECT.

    Elle refuse toute permission (aucune ligne de rôle) : l'utilisateur de ce
    test n'a donc droit qu'aux types sans permission — `budget`.
    """

    def __init__(self, jobs):
        self.jobs = jobs
        self.requetes_de_permission = 0

    async def execute(self, stmt, *args, **kwargs):
        compile_ = stmt.compile()
        if "FROM export_jobs" not in str(compile_):
            self.requetes_de_permission += 1
            return _Resultat([])
        connus = set(PERMISSION_PAR_TYPE)
        types = set()
        for valeur in compile_.params.values():
            if isinstance(valeur, str) and valeur in connus:
                types.add(valeur)
            elif isinstance(valeur, (list, tuple)):
                types.update(v for v in valeur if v in connus)
        retenus = sorted(
            (j for j in self.jobs if j.type in types),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return _Resultat(retenus[: (stmt._limit or 20)])


class _Resultat:
    def __init__(self, donnees):
        self.donnees = donnees

    def scalars(self):
        return self

    def all(self):
        return self.donnees

    def scalar_one_or_none(self):
        return self.donnees[0] if self.donnees else None


async def test_la_liste_ne_perd_pas_les_jobs_visibles_derriere_une_page_de_jobs_caches():
    """Le filtre de permission doit être DANS le SQL, pas après le `LIMIT`.

    Appliqué après coup, il vidait la page : une organisation dont les vingt
    derniers exports sont des encaissements faisait voir une liste vide à un
    utilisateur sans `menu_encaissements`, alors que ses propres exports budget
    existaient. Il en concluait que ses exports avaient été perdus.

    Le compte de requêtes est l'autre moitié du correctif : il est borné par le
    nombre de types, pas par la taille de la page.
    """
    from app.api.v1.endpoints.export_jobs import lister_jobs

    base = datetime.now(timezone.utc)
    jobs = [
        _job(type="encaissements", created_at=base - timedelta(minutes=i)) for i in range(30)
    ] + [_job(type="budget", created_at=base - timedelta(days=1, minutes=i)) for i in range(3)]

    utilisateur = AuthUser(
        id=uuid.uuid4(), role="agent", role_id=3, organisation_id=7, active=True
    )
    session = _SessionFiltrante(jobs)

    reponse = await lister_jobs(limite=20, user=utilisateur, db=session)

    assert [item["type"] for item in reponse["items"]] == ["budget"] * 3
    assert reponse["total"] == 3
    # Une résolution par type cartographié au plus, quelle que soit la page.
    assert session.requetes_de_permission <= len(PERMISSION_PAR_TYPE)


# ── Corrections de revue (29/08) ─────────────────────────────────────────────


class _ResultatOptionnel:
    def __init__(self, valeur):
        self._valeur = valeur

    def scalar_one_or_none(self):
        return self._valeur


class _SessionStatut:
    """Session minimale rendant le statut d'abonnement de l'organisation."""

    def __init__(self, statut):
        self.statut = statut

    async def execute(self, _requete):
        return _ResultatOptionnel(self.statut)


@pytest.mark.parametrize("statut", ["ACTIVE", "TRIAL", "  active  "])
async def test_un_abonnement_valide_laisse_mettre_en_file(monkeypatch, statut):
    from app.api.v1.endpoints import exports

    monkeypatch.setattr(exports, "get_cached_saas_status", _sans_console_saas)
    await exports._refuser_si_abonnement_suspendu(_SessionStatut(statut), 7)


@pytest.mark.parametrize("statut", ["EXPIRED", "SUSPENDED", None, ""])
async def test_un_abonnement_suspendu_ne_peut_plus_mettre_en_file(monkeypatch, statut):
    """Le garde-fou de deps.py ne couvre que les verbes d'écriture ; or un GET
    d'export ÉCRIT désormais une ligne. Sans ce contrôle, une organisation en
    lecture seule continuait de consommer le worker."""
    from app.api.v1.endpoints import exports

    monkeypatch.setattr(exports, "get_cached_saas_status", _sans_console_saas)
    with pytest.raises(HTTPException) as echec:
        await exports._refuser_si_abonnement_suspendu(_SessionStatut(statut), 7)
    assert echec.value.status_code == 402


async def test_la_console_saas_fait_autorite_sur_l_organisation(monkeypatch):
    """Même ordre de résolution que deps.py : deux ordres différents finiraient
    par déclarer un tenant suspendu d'un côté et actif de l'autre."""
    from app.api.v1.endpoints import exports

    async def _console_dit_expire(_org_id):
        return "EXPIRED"

    monkeypatch.setattr(exports, "get_cached_saas_status", _console_dit_expire)
    # L'organisation se dit ACTIVE, la console dit EXPIRED : la console gagne.
    with pytest.raises(HTTPException) as echec:
        await exports._refuser_si_abonnement_suspendu(_SessionStatut("ACTIVE"), 7)
    assert echec.value.status_code == 402


async def _sans_console_saas(_org_id):
    return None


def test_seule_la_table_absente_est_toleree():
    """Attraper ProgrammingError en bloc masquerait une colonne absente ou une
    faute de syntaxe — des erreurs qui doivent rester bruyantes."""
    from app.workers.exports import _table_absente

    class _Orig:
        def __init__(self, sqlstate):
            self.sqlstate = sqlstate

    class _Erreur(Exception):
        def __init__(self, orig):
            self.orig = orig

    assert _table_absente(_Erreur(_Orig("42P01"))) is True
    assert _table_absente(_Erreur(_Orig("42703"))) is False  # colonne absente
    assert _table_absente(Exception("sans orig")) is False


async def test_le_balayage_survit_a_la_table_absente(monkeypatch):
    """Le worker ne dépend pas du backend : son cron se déclenche à la minute,
    y compris avant qu'alembic ait tourné sur une pile neuve."""
    from sqlalchemy.exc import ProgrammingError

    from app.workers import exports as taches

    class _Orig:
        sqlstate = "42P01"

    async def _table_pas_encore_creee(*_args, **_kwargs):
        raise ProgrammingError("SELECT ...", {}, _Orig())

    monkeypatch.setattr(taches, "_balayer_baux_expires", _table_pas_encore_creee)
    monkeypatch.setattr(taches, "_purger_artefacts_perimes", _table_pas_encore_creee)

    assert await taches.balayer_baux_expires(None) == 0
    assert await taches.purger_artefacts_perimes() == 0


async def test_une_autre_erreur_sql_reste_bruyante(monkeypatch):
    from sqlalchemy.exc import ProgrammingError

    from app.workers import exports as taches

    class _Orig:
        sqlstate = "42703"  # colonne inexistante : signe d'un modèle désynchronisé

    async def _colonne_absente(*_args, **_kwargs):
        raise ProgrammingError("SELECT ...", {}, _Orig())

    monkeypatch.setattr(taches, "_balayer_baux_expires", _colonne_absente)
    with pytest.raises(ProgrammingError):
        await taches.balayer_baux_expires(None)


def test_la_fenetre_de_deduplication_couvre_l_attente_du_client():
    """Le client abandonne au bout de 10 minutes (DELAI_TOTAL_MS de
    download.ts). Une fenêtre plus courte ferait régénérer l'export au moment
    précis où la déduplication a le plus de valeur : juste après un abandon."""
    assert settings.export_dedup_window_minutes > 10
