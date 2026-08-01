"""Conversion vers la devise de tenue.

Le défaut corrigé : `debit_tenue` recevait le montant brut quelle que soit la
devise. Le Grand Livre, la Balance et les états financiers agrégeant tous ces
colonnes, une organisation mêlant USD et CDF additionnait des francs
congolais à des dollars.

Points vérifiés :
- les deux conventions de taux (application « par USD », module comptable
  « source → cible ») sont correctement réconciliées ;
- le taux de TRÉSORERIE n'est jamais repris automatiquement : le taux
  comptable est un choix distinct, saisi par le comptable ;
- sans taux, échec bloquant — jamais de conversion silencieuse au taux 1 ;
- l'équilibre de l'écriture survit aux arrondis de conversion ;
- une écriture déjà déséquilibrée n'est pas « réparée » par la conversion.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.modules.comptabilite.models import (
    ComptaEcriture,
    ComptaExercice,
    ComptaLigneEcriture,
    ComptaTauxChange,
)
from app.modules.comptabilite.services.change_service import (
    TauxIntrouvable,
    convertir_lignes,
    resoudre_taux,
    taux_tresorerie_vers_comptable,
)
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Change Test", slug=f"chg-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _activer(db, org) -> ComptaExercice:
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    await db.flush()
    return (
        await db.execute(select(ComptaExercice).where(ComptaExercice.organisation_id == org.id))
    ).scalar_one()


# ── Résolution du taux ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meme_devise_donne_un_taux_neutre(db_session):
    db = db_session
    org = await _org(db)
    taux = await resoudre_taux(
        db, organisation_id=org.id, devise_source="USD", devise_cible="USD",
        date_operation=date(2026, 5, 1),
    )
    assert taux == Decimal("1")


@pytest.mark.asyncio
async def test_le_taux_de_tresorerie_n_est_jamais_repris_automatiquement(db_session):
    """Le taux appliqué par la trésorerie n'est pas le taux comptable : même
    parfaitement renseigné côté trésorerie, il ne doit pas servir à convertir
    une écriture. Sinon il serait impossible de distinguer ensuite une
    conversion voulue d'une conversion subie."""
    db = db_session
    org = await _org(db)
    db.add(
        PrintSettings(
            organisation_id=org.id, exchange_rate=Decimal("0"),
            exchange_rate_cdf=Decimal("2800"), exchange_rate_eur=Decimal("0"),
            exchange_rate_xof=Decimal("0"),
        )
    )
    await db.flush()

    with pytest.raises(TauxIntrouvable):
        await resoudre_taux(
            db, organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            date_operation=date(2026, 5, 1),
        )


@pytest.mark.asyncio
async def test_taux_de_tresorerie_traduit_en_convention_comptable(db_session):
    """Il reste PROPOSÉ comme point de départ dans l'écran de paramétrage,
    traduit de « unités pour 1 USD » vers « source → cible »."""
    db = db_session
    org = await _org(db)
    db.add(
        PrintSettings(
            organisation_id=org.id, exchange_rate=Decimal("0"),
            exchange_rate_cdf=Decimal("2800"), exchange_rate_eur=Decimal("0.92"),
            exchange_rate_xof=Decimal("0"),
        )
    )
    await db.flush()

    assert await taux_tresorerie_vers_comptable(db, org.id, "CDF", "USD") == Decimal("0.00035714")
    # Entre deux devises non pivot, le taux se déduit du rapport des deux.
    assert await taux_tresorerie_vers_comptable(db, org.id, "CDF", "EUR") == Decimal("0.00032857")


@pytest.mark.asyncio
async def test_taux_du_referentiel_et_son_inverse(db_session):
    """Saisir un seul sens suffit : l'autre s'en déduit."""
    db = db_session
    org = await _org(db)
    db.add(
        ComptaTauxChange(
            organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00040000"), date_taux=date(2026, 1, 1),
        )
    )
    await db.flush()

    direct = await resoudre_taux(
        db, organisation_id=org.id, devise_source="CDF", devise_cible="USD",
        date_operation=date(2026, 5, 1),
    )
    assert direct == Decimal("0.00040000")

    inverse = await resoudre_taux(
        db, organisation_id=org.id, devise_source="USD", devise_cible="CDF",
        date_operation=date(2026, 5, 1),
    )
    assert inverse == Decimal("2500.00000000")


@pytest.mark.asyncio
async def test_inverser_un_taux_arrondi_ne_redonne_pas_l_original(db_session):
    """Comportement attendu, à ne pas confondre avec un défaut : 0,00035714
    est déjà l'arrondi de 1/2800, l'inverser rend 2800,0224. C'est pourquoi il
    vaut mieux saisir le sens réellement utilisé par l'organisation."""
    db = db_session
    org = await _org(db)
    db.add(
        ComptaTauxChange(
            organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00035714"), date_taux=date(2026, 1, 1),
        )
    )
    await db.flush()

    inverse = await resoudre_taux(
        db, organisation_id=org.id, devise_source="USD", devise_cible="CDF",
        date_operation=date(2026, 5, 1),
    )
    assert inverse == Decimal("2800.02240018")


@pytest.mark.asyncio
async def test_taux_le_plus_recent_a_la_date_de_l_operation(db_session):
    """Une écriture d'avril ne doit pas être convertie au taux de septembre."""
    db = db_session
    org = await _org(db)
    db.add_all([
        ComptaTauxChange(
            organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00040000"), date_taux=date(2026, 1, 1),
        ),
        ComptaTauxChange(
            organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00030000"), date_taux=date(2026, 9, 1),
        ),
    ])
    await db.flush()

    en_avril = await resoudre_taux(
        db, organisation_id=org.id, devise_source="CDF", devise_cible="USD",
        date_operation=date(2026, 4, 15),
    )
    assert en_avril == Decimal("0.00040000")

    en_octobre = await resoudre_taux(
        db, organisation_id=org.id, devise_source="CDF", devise_cible="USD",
        date_operation=date(2026, 10, 15),
    )
    assert en_octobre == Decimal("0.00030000")


@pytest.mark.asyncio
async def test_sans_taux_echec_bloquant(db_session):
    """Jamais de conversion silencieuse au taux 1 : c'est le défaut corrigé."""
    db = db_session
    org = await _org(db)
    with pytest.raises(TauxIntrouvable) as exc:
        await resoudre_taux(
            db, organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            date_operation=date(2026, 5, 1),
        )
    assert "CDF" in str(exc.value)


@pytest.mark.asyncio
async def test_taux_d_une_autre_organisation_est_ignore(db_session):
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    db.add(
        ComptaTauxChange(
            organisation_id=org_b.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00035714"), date_taux=date(2026, 1, 1),
        )
    )
    await db.flush()

    with pytest.raises(TauxIntrouvable):
        await resoudre_taux(
            db, organisation_id=org_a.id, devise_source="CDF", devise_cible="USD",
            date_operation=date(2026, 5, 1),
        )


# ── Conversion des lignes ───────────────────────────────────────────────────


def test_conversion_preserve_l_equilibre_malgre_les_arrondis():
    """Converti ligne à ligne puis arrondi au centime, un total peut dériver
    d'un centime. L'écriture doit rester équilibrée en devise de tenue."""
    taux = Decimal("0.00035714")
    lignes = [
        (Decimal("33333"), Decimal("0")),
        (Decimal("33333"), Decimal("0")),
        (Decimal("33334"), Decimal("0")),
        (Decimal("0"), Decimal("100000")),
    ]
    convertis = convertir_lignes(lignes, taux)

    total_debit = sum((d for d, _ in convertis), Decimal("0"))
    total_credit = sum((c for _, c in convertis), Decimal("0"))
    assert total_debit == total_credit, f"déséquilibre après conversion : {convertis}"
    # Converties isolément, les trois lignes de débit ne totalisent que 35,70 ;
    # le centime manquant est AJOUTÉ à la plus grosse d'entre elles, ce qui
    # aligne l'écriture sur la conversion exacte du total (100 000 × taux).
    assert total_debit == Decimal("35.71")
    assert all(debit >= 0 and credit >= 0 for debit, credit in convertis)


def test_conversion_n_invente_rien_sur_une_ecriture_deja_desequilibree():
    """Une saisie fausse doit rester fausse : c'est à la validation de la
    refuser, pas à la conversion de la maquiller."""
    taux = Decimal("2")
    lignes = [(Decimal("100"), Decimal("0")), (Decimal("0"), Decimal("90"))]
    convertis = convertir_lignes(lignes, taux)
    assert convertis == [(Decimal("200.00"), Decimal("0.00")), (Decimal("0.00"), Decimal("180.00"))]


def test_taux_neutre_laisse_les_montants_intacts():
    lignes = [(Decimal("125.50"), Decimal("0")), (Decimal("0"), Decimal("125.50"))]
    assert convertir_lignes(lignes, Decimal("1")) == [
        (Decimal("125.50"), Decimal("0.00")),
        (Decimal("0.00"), Decimal("125.50")),
    ]


# ── Bout en bout ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ecriture_manuelle_en_cdf_est_convertie(db_session):
    """La saisie manuelle souffrait du même défaut que la génération."""
    db = db_session
    org = await _org(db)
    exercice = await _activer(db, org)
    db.add(
        ComptaTauxChange(
            organisation_id=org.id, devise_source="CDF", devise_cible="USD",
            taux=Decimal("0.00035714"), date_taux=date(2026, 1, 1),
        )
    )
    await db.commit()

    from app.models.user import User
    from app.modules.comptabilite.models import ComptaCompte, ComptaJournal
    from app.modules.comptabilite.routers.ecritures import create_ecriture
    from app.modules.comptabilite.schemas.ecritures import EcritureCreateIn, LigneEcritureIn

    user = User(id=uuid.uuid4(), email=f"u{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()

    journal = (
        await db.execute(
            select(ComptaJournal).where(
                ComptaJournal.organisation_id == org.id, ComptaJournal.code == "CA"
            )
        )
    ).scalar_one()
    caisse = (
        await db.execute(
            select(ComptaCompte).where(
                ComptaCompte.organisation_id == org.id, ComptaCompte.numero == "571"
            )
        )
    ).scalar_one()
    produit = (
        await db.execute(
            select(ComptaCompte).where(
                ComptaCompte.organisation_id == org.id, ComptaCompte.numero == "70"
            )
        )
    ).scalar_one()

    out = await create_ecriture(
        payload=EcritureCreateIn(
            journal_id=journal.id, exercice_id=exercice.id, date_ecriture=date(2026, 5, 1),
            libelle="Cotisation en CDF", devise="CDF",
            lignes=[
                LigneEcritureIn(compte_id=caisse.id, debit=Decimal("280000"), credit=Decimal("0")),
                LigneEcritureIn(compte_id=produit.id, debit=Decimal("0"), credit=Decimal("280000")),
            ],
        ),
        tenant_id=org.id, user=user, db=db,
    )

    ecriture = await db.get(ComptaEcriture, out.id)
    assert ecriture.taux_change == Decimal("0.00035714")
    lignes = (
        await db.execute(
            select(ComptaLigneEcriture).where(ComptaLigneEcriture.ecriture_id == ecriture.id)
        )
    ).scalars().all()
    assert sum((l.debit for l in lignes), Decimal("0")) == Decimal("280000")  # devise d'origine
    assert sum((l.debit_tenue for l in lignes), Decimal("0")) == Decimal("100.00")  # 280 000 / 2800
