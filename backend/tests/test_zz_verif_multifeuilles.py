"""Import d'un classeur Tableau à plusieurs feuilles.

Le lecteur Excel renumérote les lignes à chaque onglet : la ligne 5 de la
première feuille et la ligne 5 de la seconde portent le même numéro pour le même
import. Tant que l'unicité ne regardait que `(import_id, line_number)`, tout
classeur multi-feuilles échouait sur la contrainte.

Le test ne se contente pas de vérifier que l'import aboutit. Un statut
`completed` ne dit rien d'une feuille silencieusement ignorée : c'est en
comptant les lignes, feuille par feuille, qu'on voit si le classeur a vraiment
été lu en entier.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.modules.tableau.models import TableauSourceRow
from app.modules.tableau.service import import_excel
from test_tableau_module import _make_workbook_bytes


@pytest.mark.asyncio
async def test_import_classeur_multifeuilles(db_session, test_admin_user):
    outcome = await import_excel(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "tableau_reel.xlsx",
        _make_workbook_bytes(),
        "2071",
        date_situation=date(2071, 6, 30),
    )
    assert outcome.imp.status == "completed"

    lignes = list((await db_session.execute(
        select(TableauSourceRow).where(TableauSourceRow.import_id == outcome.imp.id)
    )).scalars().all())

    # Les deux feuilles du classeur d'essai : deux lignes dans la première, une
    # dans la seconde. Une feuille ignorée se verrait ici, pas dans le statut.
    par_feuille: dict[str, list[int]] = {}
    for ligne in lignes:
        par_feuille.setdefault(ligne.feuille, []).append(ligne.line_number)
    assert set(par_feuille) == {"EC EN CABINET 25", "EC Indépendant 25"}
    assert len(lignes) == 3

    # Le cœur de la régression : les deux feuilles portent chacune une ligne 5,
    # et elles doivent coexister. C'est exactement ce que l'ancienne contrainte
    # rendait impossible.
    assert 5 in par_feuille["EC EN CABINET 25"]
    assert 5 in par_feuille["EC Indépendant 25"]

    # Et les numéros d'ordre des trois feuilles sont bien tous arrivés.
    numeros = {
        (ligne.business_key_candidate or "").strip()
        for ligne in lignes
        if ligne.business_key_candidate
    }
    assert numeros == {"EC/16.00001", "EC/18.00003", "EC/17.00002"}
