"""Créances des membres constatées à l'émission des notes de débit.

Points sensibles couverts :
- le mode est éteint par défaut et, éteint, ne change rien au règlement ;
- un compte par membre, numéroté sous la racine, ou repris d'un plan importé ;
- la créance passe au journal Adhérents et le règlement solde le compte du
  membre — jamais deux fois le produit ;
- une note actualisée remplace son écriture sans la modifier (brouillon
  annulé, écriture validée contre-passée), une note annulée n'en laisse pas ;
- la reprise ne touche pas une note déjà réglée en partie ;
- créance et règlement se lettrent par le numéro de la note.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaJournal,
    ComptaMappingPosteBudgetaire,
)
from app.modules.comptabilite.services.creances_service import (
    compte_creance_de_la_note,
    constater_notes_existantes,
    numero_suivant,
    regler_creances,
    synchroniser_creance_note,
)
from app.modules.comptabilite.services.ecriture_service import valider_ecriture
from app.modules.comptabilite.services.lettrage_service import lettrage_automatique
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite
from app.services.encaissement_payments import record_encaissement_payment


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


class _Dossier:
    def __init__(self, db, org, user, cotisations, penalites):
        self.db, self.org, self.user = db, org, user
        self.cotisations, self.penalites = cotisations, penalites

    async def compte(self, numero: str) -> ComptaCompte:
        return (
            await self.db.execute(
                select(ComptaCompte).where(
                    ComptaCompte.organisation_id == self.org.id, ComptaCompte.numero == numero
                )
            )
        ).scalar_one()

    async def membre(self, nom: str) -> ExpertComptable:
        expert = ExpertComptable(numero_ordre=f"EC/{_suffix()}", nom_denomination=nom, type_ec="EC")
        self.db.add(expert)
        await self.db.flush()
        return expert

    async def note(self, expert, *, cotisation="600", penalite="0", paye="0") -> Encaissement:
        lignes = [(self.cotisations, "Cotisation 2026", Decimal(cotisation))]
        if Decimal(penalite) > 0:
            lignes.append((self.penalites, "Pénalité AG", Decimal(penalite)))
        total = sum((m for _, _, m in lignes), Decimal("0"))
        note = Encaissement(
            numero_recu=f"ND-{_suffix()}", organisation_id=self.org.id, type_client="expert_comptable",
            expert_comptable_id=expert.id, libelle="Cotisation 2026", exercice=2026,
            montant=total, montant_total=total, montant_paye=Decimal(paye), montant_percu=Decimal(paye),
            budget_poste_id=self.cotisations.id, statut_paiement="non_paye" if Decimal(paye) == 0 else "partiel",
            mode_paiement="cash", canal="CAISSE", impact_budgetaire=True,
            date_encaissement=datetime(2026, 2, 1, 9, tzinfo=timezone.utc),
        )
        self.db.add(note)
        await self.db.flush()
        for ordre, (poste, libelle, montant) in enumerate(lignes):
            self.db.add(EncaissementArticle(
                organisation_id=self.org.id, encaissement_id=note.id, libelle=libelle, quantite=1,
                prix_unitaire=montant, montant=montant, budget_poste_id=poste.id, sort_order=ordre,
            ))
        await self.db.flush()
        return note

    async def synchroniser(self, note) -> ComptaEcriture | None:
        return await synchroniser_creance_note(
            self.db, organisation_id=self.org.id, encaissement_id=note.id, user_id=self.user.id
        )

    async def ecritures(self, type_origine: str) -> list[ComptaEcriture]:
        return list(
            (
                await self.db.execute(
                    select(ComptaEcriture)
                    .options(selectinload(ComptaEcriture.lignes))
                    .where(
                        ComptaEcriture.organisation_id == self.org.id,
                        ComptaEcriture.type_origine == type_origine,
                    )
                    .order_by(ComptaEcriture.created_at)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )

    async def solde(self, compte: ComptaCompte) -> Decimal:
        """Solde débiteur du compte, hors écritures annulées."""
        total = Decimal("0")
        for type_origine in ("note_debit", "payment_history", "CONTREPASSATION"):
            for ecriture in await self.ecritures(type_origine):
                if ecriture.statut == "ANNULEE" and type_origine != "CONTREPASSATION":
                    # Une écriture validée puis contre-passée reste au Grand
                    # Livre avec son inverse ; un brouillon annulé n'y est jamais entré.
                    if ecriture.numero is None:
                        continue
                for ligne in ecriture.lignes:
                    if ligne.compte_id == compte.id:
                        total += Decimal(ligne.debit) - Decimal(ligne.credit)
        return total


async def _dossier(db, *, creances: bool = True, racine: str = "411") -> _Dossier:
    org = Organisation(nom="Créances Test", slug=f"cre-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"c{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=Decimal("0"), est_ouverte=True))
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    postes = []
    for code in ("COT", "PEN"):
        poste = BudgetPoste(
            organisation_id=org.id, exercice_id=exercice.id, code=f"{code}-{_suffix()}",
            libelle=f"Poste {code}", type="RECETTE", active=True,
            montant_prevu=Decimal("100000"), montant_engage=0, montant_paye=0, is_deleted=False,
        )
        db.add(poste)
        postes.append(poste)
    await db.flush()
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    await generer_mappings_par_defaut(db, organisation_id=org.id)
    db.add(OrganisationSettings(organisation_id=org.id, accounting_integration_mode="automatic"))
    await db.flush()
    dossier = _Dossier(db, org, user, *postes)
    # Deux comptes de produit distincts, pour suivre chaque ligne de la note.
    for poste, numero in ((postes[0], "70"), (postes[1], "758")):
        mapping = (
            await db.execute(
                select(ComptaMappingPosteBudgetaire).where(
                    ComptaMappingPosteBudgetaire.organisation_id == org.id,
                    ComptaMappingPosteBudgetaire.budget_poste_id == poste.id,
                )
            )
        ).scalar_one()
        mapping.compte_id = (await dossier.compte(numero)).id
    await db.flush()
    if creances:
        await regler_creances(
            db, organisation_id=org.id, actif=True, compte_racine_id=(await dossier.compte(racine)).id
        )
    return dossier


def test_numerotation_des_comptes_de_membres():
    # Les zéros de fin de la racine sont la place du numéro d'ordre.
    assert numero_suivant("4111010000", set()) == "4111010001"
    assert numero_suivant("4111010000", {"4111010001", "4111010002"}) == "4111010003"
    # Une racine courte reçoit quatre chiffres.
    assert numero_suivant("411", {"4110001"}) == "4110002"


@pytest.mark.asyncio
async def test_mode_eteint_le_reglement_reste_tresorerie_contre_produit(db_session):
    d = await _dossier(db_session, creances=False)
    note = await d.note(await d.membre("KABONGO Jean"))

    assert await d.synchroniser(note) is None
    assert await d.ecritures("note_debit") == []

    await record_encaissement_payment(
        d.db, organisation_id=d.org.id, encaissement_id=note.id, montant=Decimal("600"),
        mode_paiement="cash", reference=None, notes=None, user_id=d.user.id,
    )
    (reglement,) = await d.ecritures("payment_history")
    produit = await d.compte("70")
    assert [(l.compte_id, l.credit) for l in reglement.lignes if l.credit > 0] == [(produit.id, Decimal("600"))]


@pytest.mark.asyncio
async def test_creance_au_journal_creances_puis_reglement_au_compte_du_tiers(db_session):
    d = await _dossier(db_session)
    expert = await d.membre("KABONGO Jean")
    note = await d.note(expert, cotisation="600", penalite="100")

    creance = await d.synchroniser(note)
    journal = await d.db.get(ComptaJournal, creance.journal_id)
    assert (journal.code, creance.statut, creance.reference_piece) == ("ADR", "BROUILLON", note.numero_recu)
    assert creance.date_ecriture == date(2026, 2, 1)

    membre = (
        await d.db.execute(select(ComptaCompte).where(ComptaCompte.tiers_expert_id == expert.id))
    ).scalar_one()
    assert (membre.numero, membre.libelle, membre.lettrable) == ("4110001", "KABONGO Jean", True)
    assert membre.parent_id == (await d.compte("411")).id

    (ecriture,) = await d.ecritures("note_debit")
    lignes = {l.compte_id: (l.debit, l.credit) for l in ecriture.lignes}
    assert lignes == {
        membre.id: (Decimal("700"), Decimal("0")),
        (await d.compte("70")).id: (Decimal("0"), Decimal("600")),
        (await d.compte("758")).id: (Decimal("0"), Decimal("100")),
    }
    # Rejouer ne crée rien : la note n'a pas changé.
    assert (await d.synchroniser(note)).id == creance.id
    assert len(await d.ecritures("note_debit")) == 1

    # Acompte : la trésorerie au débit, le compte du membre au crédit.
    await record_encaissement_payment(
        d.db, organisation_id=d.org.id, encaissement_id=note.id, montant=Decimal("300"),
        mode_paiement="cash", reference=None, notes=None, user_id=d.user.id,
    )
    (reglement,) = await d.ecritures("payment_history")
    assert reglement.reference_piece == note.numero_recu
    assert [(l.compte_id, l.credit) for l in reglement.lignes if l.credit > 0] == [(membre.id, Decimal("300"))]
    assert await d.solde(membre) == Decimal("400")

    # Un second membre prend le numéro suivant.
    autre = await d.note(await d.membre("MBUYI Marie"))
    await d.synchroniser(autre)
    assert await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=autre.id) != membre.id
    numeros = sorted(
        (await d.db.execute(
            select(ComptaCompte.numero).where(
                ComptaCompte.organisation_id == d.org.id, ComptaCompte.tiers_expert_id.is_not(None)
            )
        )).scalars()
    )
    assert numeros == ["4110001", "4110002"]


@pytest.mark.asyncio
async def test_compte_du_tiers_repris_d_un_plan_importe(db_session):
    """Le plan repris du logiciel comptable porte déjà un compte au nom du
    membre : il est rattaché, pas doublé."""
    d = await _dossier(db_session, creances=False)
    racine_411 = await d.compte("411")
    racine = ComptaCompte(
        organisation_id=d.org.id, referentiel_id=racine_411.referentiel_id, numero="4111010000",
        libelle="Cotisations de membre-EC PP", nature="ACTIF", sens_normal="DEBIT", classe="4",
    )
    existant = ComptaCompte(
        organisation_id=d.org.id, referentiel_id=racine_411.referentiel_id, numero="4111010007",
        libelle="AMANI BAKULIKIRA Dolcane", nature="ACTIF", sens_normal="DEBIT", classe="4",
    )
    d.db.add_all([racine, existant])
    await d.db.flush()
    await regler_creances(d.db, organisation_id=d.org.id, actif=True, compte_racine_id=racine.id)

    connu = await d.note(await d.membre("Amani Bakulikira, Dolcane"))
    await d.synchroniser(connu)
    assert await compte_creance_de_la_note(
        d.db, organisation_id=d.org.id, encaissement_id=connu.id
    ) == existant.id

    nouveau = await d.note(await d.membre("ZOLA Pierre"))
    await d.synchroniser(nouveau)
    compte_id = await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=nouveau.id)
    assert (await d.db.get(ComptaCompte, compte_id)).numero == "4111010001"


@pytest.mark.asyncio
async def test_note_actualisee_remplace_son_ecriture_sans_la_modifier(db_session):
    d = await _dossier(db_session)
    expert = await d.membre("KABONGO Jean")
    note = await d.note(expert, cotisation="600")
    premiere = await d.synchroniser(note)

    async def actualiser(montant: str):
        article = (
            await d.db.execute(select(EncaissementArticle).where(EncaissementArticle.encaissement_id == note.id))
        ).scalar_one()
        article.montant = article.prix_unitaire = Decimal(montant)
        note.montant = note.montant_total = Decimal(montant)
        await d.db.flush()
        return await d.synchroniser(note)

    # Brouillon : simplement annulé, il n'a jamais atteint le Grand Livre.
    deuxieme = await actualiser("650")
    await d.db.refresh(premiere)
    assert premiere.statut == "ANNULEE" and deuxieme.id != premiere.id
    assert await d.ecritures("CONTREPASSATION") == []

    # Validée : contre-passée, puis remplacée.
    await valider_ecriture(d.db, ecriture_id=deuxieme.id, organisation_id=d.org.id, user_id=d.user.id)
    troisieme = await actualiser("500")
    await d.db.refresh(deuxieme)
    assert deuxieme.statut == "ANNULEE"
    (inverse,) = await d.ecritures("CONTREPASSATION")
    assert inverse.contrepasse_ecriture_id == deuxieme.id

    membre_id = await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=note.id)
    assert await d.solde(await d.db.get(ComptaCompte, membre_id)) == Decimal("500")
    assert [e.objet_origine_id for e in await d.ecritures("note_debit")] == [
        str(note.id), f"{note.id}:2", f"{note.id}:3",
    ]
    assert troisieme.statut == "BROUILLON"


@pytest.mark.asyncio
async def test_note_annulee_ne_laisse_pas_de_creance(db_session):
    d = await _dossier(db_session)
    note = await d.note(await d.membre("KABONGO Jean"))
    creance = await d.synchroniser(note)
    membre_id = await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=note.id)

    note.statut_operation = "ANNULEE"
    await d.db.flush()
    assert await d.synchroniser(note) is None
    await d.db.refresh(creance)
    assert creance.statut == "ANNULEE"
    assert await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=note.id) is None
    assert await d.solde(await d.db.get(ComptaCompte, membre_id)) == Decimal("0")


@pytest.mark.asyncio
async def test_poste_sans_compte_bloque_la_creance(db_session):
    d = await _dossier(db_session)
    mapping = (
        await d.db.execute(
            select(ComptaMappingPosteBudgetaire).where(
                ComptaMappingPosteBudgetaire.budget_poste_id == d.cotisations.id
            )
        )
    ).scalar_one()
    await d.db.delete(mapping)
    await d.db.flush()
    note = await d.note(await d.membre("KABONGO Jean"))
    with pytest.raises(HTTPException) as exc:
        await d.synchroniser(note)
    assert "sans compte comptable" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_reprise_laisse_les_notes_deja_reglees_en_partie(db_session):
    d = await _dossier(db_session, creances=False)
    vierge = await d.note(await d.membre("KABONGO Jean"), cotisation="600")
    await d.note(await d.membre("MBUYI Marie"), cotisation="600", paye="200")

    with pytest.raises(HTTPException):
        await constater_notes_existantes(d.db, organisation_id=d.org.id, simulation=True)

    await regler_creances(
        d.db, organisation_id=d.org.id, actif=True, compte_racine_id=(await d.compte("411")).id
    )
    simulation = await constater_notes_existantes(d.db, organisation_id=d.org.id, simulation=True)
    assert (simulation.constatees, simulation.montant, simulation.deja_reglees_en_partie) == (1, Decimal("600"), 1)
    assert await d.ecritures("note_debit") == []

    reel = await constater_notes_existantes(
        d.db, organisation_id=d.org.id, simulation=False, user_id=d.user.id
    )
    assert (reel.constatees, reel.deja_reglees_en_partie, reel.echecs) == (1, 1, [])
    (ecriture,) = await d.ecritures("note_debit")
    assert ecriture.objet_origine_id == str(vierge.id)
    # Rejouer ne constate rien de plus.
    assert (await constater_notes_existantes(d.db, organisation_id=d.org.id, simulation=False)).constatees == 0


@pytest.mark.asyncio
async def test_creance_et_reglement_se_lettrent_par_le_numero_de_la_note(db_session):
    d = await _dossier(db_session)
    note = await d.note(await d.membre("KABONGO Jean"), cotisation="600")
    creance = await d.synchroniser(note)
    await record_encaissement_payment(
        d.db, organisation_id=d.org.id, encaissement_id=note.id, montant=Decimal("600"),
        mode_paiement="cash", reference=None, notes=None, user_id=d.user.id,
    )
    (reglement,) = await d.ecritures("payment_history")
    for ecriture in (creance, reglement):
        await valider_ecriture(d.db, ecriture_id=ecriture.id, organisation_id=d.org.id, user_id=d.user.id)

    membre_id = await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=note.id)
    rapport = await lettrage_automatique(
        d.db, organisation_id=d.org.id, compte_id=membre_id, simulation=False, user_id=d.user.id
    )
    assert [(g.motif, len(g.lignes), g.montant) for g in rapport.groupes] == [("REFERENCE", 2, Decimal("600"))]


@pytest.mark.asyncio
async def test_reglage_refuse_une_racine_hors_des_comptes_de_tiers(db_session):
    d = await _dossier(db_session, creances=False)
    with pytest.raises(HTTPException):
        await regler_creances(d.db, organisation_id=d.org.id, actif=True, compte_racine_id=None)
    with pytest.raises(HTTPException):
        await regler_creances(
            d.db, organisation_id=d.org.id, actif=True, compte_racine_id=(await d.compte("571")).id
        )


@pytest.mark.asyncio
async def test_vocabulaire_de_l_organisation_reglable(db_session):
    """Un ordre parle de membres, une association d'adhérents : le nom donné
    aux tiers et celui du journal se règlent, et le journal déjà créé suit.
    Par défaut, ce sont les termes de l'Ordre."""
    d = await _dossier(db_session)
    racine = await d.compte("411")
    journal = (
        await d.db.execute(
            select(ComptaJournal).where(ComptaJournal.organisation_id == d.org.id, ComptaJournal.code == "ADR")
        )
    ).scalar_one()
    assert journal.libelle == "Adhérents"

    societe = await regler_creances(
        d.db, organisation_id=d.org.id, actif=True, compte_racine_id=racine.id,
        libelle_tiers="  client ", libelle_journal="Ventes",
    )
    assert (societe.libelle_tiers, societe.libelle_journal_creances) == ("client", "Ventes")
    await d.db.refresh(journal)
    assert journal.libelle == "Ventes"

    # Sans indication, le vocabulaire choisi reste en place.
    societe = await regler_creances(d.db, organisation_id=d.org.id, actif=True, compte_racine_id=racine.id)
    assert societe.libelle_tiers == "client"


@pytest.mark.asyncio
async def test_client_non_membre_a_son_propre_compte(db_session):
    """Tous les clients d'une organisation ne sont pas ses membres : une note
    à un client du référentiel constate aussi sa créance, sous la racine des
    clients si elle est réglée."""
    from app.models.client import Client

    d = await _dossier(db_session)
    racine_membres = await d.compte("411")
    racine_clients = ComptaCompte(
        organisation_id=d.org.id, referentiel_id=racine_membres.referentiel_id, numero="4112000000",
        libelle="Autres clients", nature="ACTIF", sens_normal="DEBIT", classe="4",
    )
    client = Client(organisation_id=d.org.id, nom="Banque Centrale du Congo")
    d.db.add_all([racine_clients, client])
    await d.db.flush()
    await regler_creances(
        d.db, organisation_id=d.org.id, actif=True, compte_racine_id=racine_membres.id,
        compte_racine_clients_id=racine_clients.id,
    )

    note = await d.note(await d.membre("KABONGO Jean"))
    note.type_client, note.client_nom = "personne_morale", client.nom
    note.expert_comptable_id, note.client_id = None, client.id
    await d.db.flush()
    await d.synchroniser(note)
    compte = await d.db.get(
        ComptaCompte,
        await compte_creance_de_la_note(d.db, organisation_id=d.org.id, encaissement_id=note.id),
    )
    assert (compte.numero, compte.libelle, compte.tiers_client_id) == (
        "4112000001", "Banque Centrale du Congo", client.id,
    )

    # Une note sans tiers identifié (un simple nom) reste comptabilisée à l'encaissement.
    anonyme = await d.note(await d.membre("X"))
    anonyme.type_client, anonyme.client_nom, anonyme.expert_comptable_id = "personne_morale", "Passant", None
    await d.db.flush()
    assert await d.synchroniser(anonyme) is None
