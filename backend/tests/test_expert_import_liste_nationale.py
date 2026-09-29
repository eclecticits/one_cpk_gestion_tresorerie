import uuid

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.experts import (
    _category_fields_from_statut,
    _import_experts_payload,
    _province_from_ville,
    _row_to_import_row,
    _situation_to_active,
)
from app.models.expert_comptable import ExpertComptable
from app.schemas.expert import ExpertImportRequest, ExpertImportRow


@pytest.mark.parametrize(
    "ville,province",
    [
        ("Kinshasa", "Kinshasa"),
        ("  LUBUMBASHI ", "Haut-Katanga"),
        ("Mbuji Mayi", "Kasaï-Oriental"),
        ("Mbuji-Mayi", "Kasaï-Oriental"),
        ("Kolwezi", "Lualaba"),
        ("", None),
        ("Paris", None),
    ],
)
def test_province_from_ville(ville, province):
    assert _province_from_ville(ville) == province


@pytest.mark.parametrize(
    "statut,expected",
    [
        ("en cabinet", ("EC", "En Cabinet")),
        ("indépendant", ("EC", "Indépendant")),
        ("Salarie", ("EC", "Salarié")),
        ("SEC", ("SEC", "Cabinet")),
        ("retraité", None),
    ],
)
def test_category_fields_from_statut(statut, expected):
    fields = _category_fields_from_statut(statut)
    if expected is None:
        assert fields is None
    else:
        assert (fields["type_ec"], fields["statut_professionnel"]) == expected


@pytest.mark.parametrize(
    "situation,active",
    [
        ("Inactif / non publié au Tableau", False),
        ("INACTIF", False),
        ("Actif", True),
        ("actif / publié au Tableau", True),
        ("", None),
        (None, None),
        ("Suspendu", None),
    ],
)
def test_situation_to_active(situation, active):
    assert _situation_to_active(situation) is active


def test_row_to_import_row_lit_la_liste_nationale():
    row = _row_to_import_row(
        "liste_nationale",
        {
            "N° d'ordre": "EC/18.00003",
            "Nom de l'expert-comptable": "ADRUPIAKO TADRI Emmanuel",
            "Sexe": "M",
            "Ville": "Kinshasa",
            "Statut": "en cabinet",
            "Situation": "Inactif / non publié au Tableau",
            "N° de téléphone": "0812345678",
            "E-mail": "eadrupiako@example.cd",
        },
    )
    assert row.numero_ordre == "EC/18.00003"
    assert row.statut_professionnel == "En Cabinet"
    assert row.categorie_personne == "Personne Physique"
    assert row.ville == "Kinshasa"
    assert row.active is False
    assert row.telephone == "0812345678"
    assert row.email == "eadrupiako@example.cd"


def test_situation_facultative_dans_les_autres_onglets():
    row = _row_to_import_row("salarie", {"N° d'ordre": "LT/1", "Noms": "X", "Situation": "Inactif"})
    assert row.active is False
    row = _row_to_import_row("salarie", {"N° d'ordre": "LT/1", "Noms": "X"})
    assert row.active is None


def _numero() -> str:
    return f"EC/T.{uuid.uuid4().hex[:8]}"


def _ligne(numero: str, nom: str, active: bool | None, **extra) -> ExpertImportRow:
    return ExpertImportRow(
        numero_ordre=numero, nom_denomination=nom, active=active,
        type_ec="EC", categorie_personne="Personne Physique", statut_professionnel="Salarié", **extra,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_la_situation_fixe_l_etat_des_nouveaux_et_signale_les_ecarts(db_session, test_admin_user):
    deja_actif = ExpertComptable(numero_ordre=_numero(), nom_denomination="Actif ici", active=True)
    deja_inactif = ExpertComptable(numero_ordre=_numero(), nom_denomination="Inactif ici", active=False)
    db_session.add_all([deja_actif, deja_inactif])
    await db_session.commit()

    nouveau_inactif, nouveau_actif, sans_situation = _numero(), _numero(), _numero()
    payload = ExpertImportRequest(
        category="liste_nationale",
        filename="liste.xlsx",
        rows=[
            _ligne(nouveau_inactif, "Nouveau inactif", False, ville="Lubumbashi"),
            _ligne(nouveau_actif, "Nouveau actif", True, ville="Atlantide"),
            _ligne(sans_situation, "Sans situation", None),
            _ligne(deja_actif.numero_ordre, "Actif renommé", False),
            _ligne(deja_inactif.numero_ordre, "Inactif renommé", True),
        ],
    )

    response = await _import_experts_payload(payload, test_admin_user, db_session)

    assert response.success is True
    assert (response.created, response.updated, response.skipped) == (3, 2, 0)
    messages = [e["message"] for e in response.errors]
    assert any("non désactivé" in m for m in messages)
    assert any("non réactivé" in m for m in messages)
    assert any("créé inactif" in m for m in messages)
    assert any("Atlantide" in m for m in messages)

    numeros = [nouveau_inactif, nouveau_actif, sans_situation, deja_actif.numero_ordre, deja_inactif.numero_ordre]
    rows = (
        await db_session.execute(select(ExpertComptable).where(ExpertComptable.numero_ordre.in_(numeros)))
    ).scalars().all()
    by_numero = {e.numero_ordre: e for e in rows}
    for expert in rows:
        await db_session.refresh(expert)

    assert by_numero[nouveau_inactif].active is False
    assert by_numero[nouveau_inactif].province_attache == "Haut-Katanga"
    assert by_numero[nouveau_actif].active is True
    assert by_numero[nouveau_actif].province_attache is None
    assert by_numero[sans_situation].active is False
    # Les fiches existantes sont mises à jour, mais leur état ne bouge pas.
    assert by_numero[deja_actif.numero_ordre].active is True
    assert by_numero[deja_actif.numero_ordre].nom_denomination == "Actif renommé"
    assert by_numero[deja_inactif.numero_ordre].active is False
    assert by_numero[deja_inactif.numero_ordre].nom_denomination == "Inactif renommé"


@pytest.mark.asyncio(loop_scope="session")
async def test_liste_nationale_accepte_les_cellules_vides(db_session, test_admin_user):
    sec = ExpertComptable(
        numero_ordre=_numero(), nom_denomination="Cabinet X", type_ec="SEC",
        statut_professionnel="Cabinet", active=False,
    )
    db_session.add(sec)
    await db_session.commit()

    vide = _numero()
    lignes = [
        _row_to_import_row("liste_nationale", {"N° d'ordre": vide, "Nom de l'expert-comptable": "Tout vide"}),
        _row_to_import_row("liste_nationale", {"N° d'ordre": sec.numero_ordre, "Nom de l'expert-comptable": "Cabinet X"}),
    ]
    payload = ExpertImportRequest(category="liste_nationale", filename="liste.xlsx", rows=lignes)

    response = await _import_experts_payload(payload, test_admin_user, db_session)

    assert response.success is True
    assert (response.created, response.updated, response.skipped) == (1, 1, 0)
    cree = (await db_session.execute(select(ExpertComptable).where(ExpertComptable.numero_ordre == vide))).scalar_one()
    assert cree.active is False
    assert cree.type_ec == "EC"
    assert cree.statut_professionnel is None
    # Une ligne sans statut ne fait pas basculer une SEC en EC.
    await db_session.refresh(sec)
    assert sec.type_ec == "SEC"


@pytest.mark.asyncio(loop_scope="session")
async def test_onglet_categorie_sans_situation_cree_actif(db_session, test_admin_user):
    numero = _numero()
    payload = ExpertImportRequest(
        category="salarie", filename="salaries.xlsx", rows=[_ligne(numero, "Salarié", None)],
    )

    response = await _import_experts_payload(payload, test_admin_user, db_session)

    assert response.success is True
    assert response.errors == []
    cree = (await db_session.execute(select(ExpertComptable).where(ExpertComptable.numero_ordre == numero))).scalar_one()
    assert cree.active is True
