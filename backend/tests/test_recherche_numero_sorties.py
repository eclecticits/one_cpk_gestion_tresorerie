"""Une sortie de fonds ou un retour se retrouve par son numéro.

Le numéro attribué (PAY-…, n° de retour) est celui qui figure sur la pièce :
c'est lui qu'on tape quand on la tient en main. Une sortie et ses retours se
cherchent ensemble, et l'export dit la même chose que l'écran.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.exports import construire_classeur_sorties_fonds
from app.api.v1.endpoints.reports import retours as rapport_retours
from app.api.v1.endpoints.sorties_fonds import list_sorties_fonds
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

MOMENT = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)


async def _contexte(db):
    org = Organisation(nom="Recherche", slug=f"rn-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"rn-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()

    def sortie(numero, reference=None):
        return SortieFonds(
            organisation_id=org.id, type_sortie="autre", montant_paye=Decimal("100"), mode_paiement="cash",
            devise="USD", canal="CAISSE", motif="Avance", beneficiaire="Agent", statut="VALIDE",
            date_paiement=MOMENT, created_by=user.id, reference_numero=numero, reference=reference,
        )

    cherchee = sortie("PAY-ADM-2026-00239")
    autre = sortie("PAY-ADM-2026-00240", reference="CHQ-7781")
    db.add_all([cherchee, autre])
    await db.flush()
    retour = RetourCaisse(
        organisation_id=org.id, sortie_fonds_id=cherchee.id, montant=Decimal("30"), devise="USD",
        canal="CAISSE", mode="cash", statut="VALIDE", date_retour=MOMENT, reference_numero="RET-2026-00012",
        created_by=user.id,
    )
    db.add(retour)
    await db.commit()
    return org, user, cherchee, autre, retour


async def _liste(db, org, user, numero):
    reponse = await list_sorties_fonds(
        include=None, date_debut=None, date_fin=None, type_sortie=None, mode_paiement=None, canal=None,
        compte_bancaire_id=None, statut=None, requisition_id=None, requisition_numero=None, reference=None,
        numero=numero, nature_mouvement=None, order=None, limit=100, offset=0, include_summary=True,
        user=user, tenant_id=org.id, db=db,
    )
    return reponse


@pytest.mark.asyncio
async def test_une_sortie_et_ses_retours_se_cherchent_par_numero(db_session):
    org, user, cherchee, autre, retour = await _contexte(db_session)

    # Casse et espaces ignorés ; un bout du numéro suffit.
    par_sortie = await _liste(db_session, org, user, "  pay-adm-2026-00239 ")
    assert [str(s.id) for s in par_sortie.items] == [str(cherchee.id)]
    assert par_sortie.total == 1
    assert par_sortie.total_retours_caisse == Decimal("30")

    # Le numéro du retour ramène la sortie qu'il corrige.
    par_retour = await _liste(db_session, org, user, "RET-2026-00012")
    assert [str(s.id) for s in par_retour.items] == [str(cherchee.id)]

    # La référence externe se cherche aussi ; l'autre sortie n'a pas de retour.
    par_reference = await _liste(db_session, org, user, "chq-7781")
    assert [str(s.id) for s in par_reference.items] == [str(autre.id)]
    assert par_reference.total_retours_caisse == Decimal("0")

    # Une recherche trop courte est refusée plutôt que de balayer toute
    # l'organisation ; « % » ne devient donc jamais un joker.
    with pytest.raises(HTTPException) as exc:
        await _liste(db_session, org, user, "%")
    assert exc.value.status_code == 400

    retours = await rapport_retours(
        date_debut=None, date_fin=None, canal=None, devise=None, numero="00239",
        user=user, db=db_session, tenant_id=org.id,
    )
    assert [r.reference_numero for r in retours] == ["RET-2026-00012"]
    assert await rapport_retours(
        date_debut=None, date_fin=None, canal=None, devise=None, numero="00240",
        user=user, db=db_session, tenant_id=org.id,
    ) == []


@pytest.mark.asyncio
async def test_l_export_porte_le_numero_et_suit_la_recherche(db_session):
    org, _user, _cherchee, _autre, _retour = await _contexte(db_session)

    classeur, _nom = await construire_classeur_sorties_fonds(db_session, org.id, numero="PAY-ADM-2026-00239")
    lignes = [[c.value for c in ligne] for ligne in classeur["Sorties"].iter_rows()]
    entete = next(l for l in lignes if "N° opération" in l)
    col = entete.index("N° opération")
    numeros = {l[col] for l in lignes[lignes.index(entete) + 1:] if l[col]}
    assert {"PAY-ADM-2026-00239", "RET-2026-00012"} <= numeros
    assert "PAY-ADM-2026-00240" not in numeros
    # Le total suit la colonne du montant malgré la colonne ajoutée : 100 − 30.
    col_montant = entete.index("Montant payé (USD)")
    total = next(l for l in lignes if any(isinstance(v, str) and v.strip().upper() == "TOTAL" for v in l))
    assert Decimal(str(total[col_montant])) == Decimal("70")
