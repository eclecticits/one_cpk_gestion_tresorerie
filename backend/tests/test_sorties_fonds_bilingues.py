"""L'écran des sorties de fonds voit-il les deux moteurs ?

Une fois le drapeau de bascule ouvert, un versement à la banque saisi sur
`POST /sorties-fonds` s'écrit dans `transferts_internes` et non plus dans
`sorties_fonds`. Trois choses doivent alors continuer de fonctionner **sur le
même identifiant**, celui que la création a annoncé :

- la ligne s'affiche dans `GET /sorties-fonds` et compte dans le pied de
  colonne « transferts internes » ;
- `POST /sorties-fonds/{id}/pdf` attache le bon et ses annexes ;
- `PATCH /sorties-fonds/{id}/statut` annule — c'est-à-dire, de ce côté-là,
  contre-passe.

Sans ces trois-là, ouvrir le drapeau ferait disparaître une opération de
l'écran qui vient de l'enregistrer. Ces tests sont la condition d'ouverture.

Ils écrivent directement dans le moteur dédié avec un `document_uuid`, comme le
fera la délégation d'écriture : la phase testée ici est l'équivalence de
lecture, pas la bascule elle-même.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import select

from app.api.v1.endpoints.sorties_fonds import (
    list_sorties_fonds,
    update_sortie_statut,
    upload_sortie_pdf,
)
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsStatusUpdate
from app.schemas.transfert import TransfertInterneCreate
from app.services.transferts_internes_service import create_transfer

MOMENT = datetime(2026, 8, 25, 11, 0, tzinfo=timezone.utc)


class _FakeRequest:
    headers: dict = {}
    client = None


async def _contexte(db):
    org = Organisation(nom="Bilingue", slug=f"bl-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"b{uuid.uuid4().hex[:6]}@ex.com", role="admin",
                prenom="Ada", nom="Lovelace", organisation_id=org.id)
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db.add_all([user, banque])
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("1000"), solde_actuel=Decimal("1000"),
        is_active=True, account_type="BANK",
    )
    db.add_all([
        compte,
        CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("1000"),
                       solde_cdf=Decimal("0"), est_ouverte=True),
    ])
    await db.flush()
    await db.commit()
    return org, user, compte


async def _transfert(db, org, user, compte, *, montant="100", sens="versement",
                     date=None, document=True):
    """Un transfert du moteur dédié, tel que la délégation d'écriture le créera."""
    if sens == "versement":
        source_type, source_id = "CAISSE", None
        destination_type, destination_id = "BANQUE", compte.id
    else:
        source_type, source_id = "BANQUE", compte.id
        destination_type, destination_id = "CAISSE", None
    payload = TransfertInterneCreate(
        source_type=source_type, source_id=source_id,
        destination_type=destination_type, destination_id=destination_id,
        montant=Decimal(montant), devise="USD", date_transfert=date or MOMENT,
    )
    return await create_transfer(
        db, payload=payload, tenant_id=org.id, user=user,
        document_uuid=uuid.uuid4() if document else None,
    )


def _sortie_legacy(org, user, *, montant="50", date=None, type_sortie="autre",
                   compte_id=None, canal="CAISSE"):
    return SortieFonds(
        organisation_id=org.id, type_sortie=type_sortie, montant_paye=Decimal(montant),
        mode_paiement="cash", devise="USD", canal=canal, compte_bancaire_id=compte_id,
        motif="Dépense", beneficiaire="Fournisseur", statut="VALIDE",
        date_paiement=date or MOMENT, created_by=user.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )


async def _lister(db, org, user, **kwargs):
    parametres = dict(
        include=None, date_debut=None, date_fin=None, type_sortie=None,
        mode_paiement=None, canal=None, compte_bancaire_id=None, statut=None,
        requisition_id=None, requisition_numero=None, reference=None, order=None,
        limit=100, offset=0, include_summary=True, user=user, tenant_id=org.id, db=db,
    )
    parametres.update(kwargs)
    return await list_sorties_fonds(**parametres)


# ---------------------------------------------------------------------------
# La ligne et le total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_transfert_delegue_s_affiche_et_compte_comme_transfert_interne(db_session):
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, montant="100")
    db_session.add(_sortie_legacy(org, user, montant="50"))
    await db_session.commit()

    reponse = await _lister(db_session, org, user)

    ligne = next(item for item in reponse.items if item.id == transfert.document_uuid)
    assert ligne.type_sortie == "versement_banque"
    assert ligne.montant_paye == Decimal("100")
    assert ligne.statut == "VALIDE"
    assert ligne.canal == "CAISSE"  # l'argent sort de la caisse
    assert ligne.compte_bancaire_id == compte.id
    assert ligne.reference == transfert.reference
    # Le bénéficiaire d'un mouvement interne est la poche qui reçoit.
    assert ligne.beneficiaire == "Rawbank - Compte courant"

    assert reponse.total == 2
    assert reponse.total_montant_paye == Decimal("150")
    # Un transfert n'est pas une dépense, quel que soit le moteur qui l'écrit.
    assert reponse.total_transferts_internes == Decimal("100")
    assert reponse.total_depenses_reelles == Decimal("50")


@pytest.mark.asyncio
async def test_un_transfert_saisi_hors_de_cet_ecran_n_y_apparait_pas(db_session):
    """Sans `document_uuid`, le transfert n'a jamais figuré ici et n'y entre pas.

    `/transferts-internes` a son propre écran. Faire remonter ses lignes sur
    celui des sorties de fonds y ferait apparaître des opérations que personne
    n'y a saisies — et gonflerait un total que sa propre liste ne justifiait
    pas jusque-là.
    """
    org, user, compte = await _contexte(db_session)
    await _transfert(db_session, org, user, compte, montant="100", document=False)
    await db_session.commit()

    reponse = await _lister(db_session, org, user)

    assert reponse.items == []
    assert reponse.total == 0
    assert reponse.total_transferts_internes == Decimal("0")


@pytest.mark.asyncio
async def test_la_contrepassation_s_affiche_a_cote_de_l_original(db_session):
    """L'original reste, sa correction s'ajoute — et les deux sont lisibles.

    C'est l'écart assumé avec le chemin historique, qui retire l'opération de
    la liste. Ici rien n'est retiré : masquer l'original tout en gardant son
    inverse afficherait de l'argent venu de nulle part.
    """
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, montant="100")

    rendu = await update_sortie_statut(
        sortie_id=str(transfert.document_uuid),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de compte"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
    )
    assert rendu.id == transfert.document_uuid
    assert rendu.statut == "CONTREPASSE"
    assert rendu.motif_annulation == "Erreur de compte"
    assert rendu.annulee_le is not None

    reponse = await _lister(db_session, org, user)

    assert len(reponse.items) == 2
    original = next(item for item in reponse.items if item.id == transfert.document_uuid)
    inverse = next(item for item in reponse.items if item.id != transfert.document_uuid)
    assert original.statut == "CONTREPASSE"
    # La correction est une opération à part entière, de sens inverse.
    assert inverse.statut == "VALIDE"
    assert inverse.type_sortie == "approvisionnement_caisse"
    assert inverse.motif == "Contre-passation d'un transfert interne"
    assert inverse.montant_paye == Decimal("100")

    # Le pied de colonne est un VOLUME de mouvements internes, pas un net : le
    # chemin historique y additionne déjà les deux sens (versement ET
    # approvisionnement). Deux mouvements de 100 valent donc 200, et la
    # trésorerie, elle, est bien revenue à son point de départ.
    assert reponse.total_transferts_internes == Decimal("200")
    caisse = await db_session.scalar(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id)
    )
    await db_session.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("1000")


@pytest.mark.asyncio
async def test_la_contrepassation_d_un_transfert_hors_ecran_reste_hors_ecran(db_session):
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, document=False)
    from app.services.transferts_internes_service import contrepasser_transfer

    inverse = await contrepasser_transfer(
        db_session, transfer_id=transfert.id, tenant_id=org.id, user=user,
        motif="Erreur de saisie",
    )
    assert inverse.document_uuid is None

    reponse = await _lister(db_session, org, user)
    assert reponse.items == []


# ---------------------------------------------------------------------------
# Les filtres de l'écran
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_les_filtres_designent_les_memes_lignes_dans_les_deux_sources(db_session):
    org, user, compte = await _contexte(db_session)
    versement = await _transfert(db_session, org, user, compte, montant="100", sens="versement")
    appro = await _transfert(db_session, org, user, compte, montant="40", sens="appro")
    await db_session.commit()

    par_type = await _lister(db_session, org, user, type_sortie="versement_banque")
    assert [item.id for item in par_type.items] == [versement.document_uuid]
    assert par_type.total_transferts_internes == Decimal("100")

    # Le canal est la poche qui envoie : un approvisionnement sort de la banque.
    par_canal = await _lister(db_session, org, user, canal="BANQUE")
    assert [item.id for item in par_canal.items] == [appro.document_uuid]

    par_compte = await _lister(db_session, org, user, compte_bancaire_id=compte.id)
    assert {item.id for item in par_compte.items} == {versement.document_uuid, appro.document_uuid}

    par_autre_compte = await _lister(db_session, org, user, compte_bancaire_id=compte.id + 10_000)
    assert par_autre_compte.items == []

    par_reference = await _lister(db_session, org, user, reference=versement.reference)
    assert [item.id for item in par_reference.items] == [versement.document_uuid]


@pytest.mark.asyncio
async def test_les_filtres_qu_un_transfert_ne_peut_pas_satisfaire_l_excluent(db_session):
    """Une réquisition, un virement, une annulation : rien de tout cela n'existe ici.

    Les rendre malgré le filtre afficherait une ligne que l'utilisateur a
    explicitement écartée.
    """
    org, user, compte = await _contexte(db_session)
    await _transfert(db_session, org, user, compte)
    await db_session.commit()

    assert (await _lister(db_session, org, user, type_sortie="autre")).items == []
    assert (await _lister(db_session, org, user, mode_paiement="virement")).items == []
    assert (await _lister(db_session, org, user, statut="ANNULEE")).items == []
    assert (await _lister(db_session, org, user, requisition_numero="REQ-1")).items == []


@pytest.mark.asyncio
async def test_les_bornes_de_date_suivent_la_date_du_transfert(db_session):
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, date=MOMENT)
    await db_session.commit()

    dedans = await _lister(db_session, org, user, date_debut="2026-08-25", date_fin="2026-08-25")
    assert [item.id for item in dedans.items] == [transfert.document_uuid]

    dehors = await _lister(db_session, org, user, date_debut="2026-08-26", date_fin="2026-08-27")
    assert dehors.items == []


# ---------------------------------------------------------------------------
# La pagination, qui doit voir les deux sources ensemble
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_page_rend_les_plus_recentes_des_deux_sources_melangees(db_session):
    """Borner chaque source séparément rendrait les N premières de chacune.

    C'est-à-dire pas les N plus récentes de l'ensemble : une page de deux
    lignes montrerait la sortie la plus récente et le transfert le plus
    récent, en cachant une sortie plus récente que ce transfert.
    """
    org, user, compte = await _contexte(db_session)
    await _transfert(db_session, org, user, compte, montant="10",
                     date=MOMENT + timedelta(days=3))
    await _transfert(db_session, org, user, compte, montant="20",
                     date=MOMENT + timedelta(days=1))
    db_session.add_all([
        _sortie_legacy(org, user, montant="30", date=MOMENT + timedelta(days=4)),
        _sortie_legacy(org, user, montant="40", date=MOMENT + timedelta(days=2)),
    ])
    await db_session.commit()

    page = await _lister(db_session, org, user, limit=2, include_summary=False)
    assert [item.montant_paye for item in page] == [Decimal("30"), Decimal("10")]

    suivante = await _lister(db_session, org, user, limit=2, offset=2, include_summary=False)
    assert [item.montant_paye for item in suivante] == [Decimal("40"), Decimal("20")]

    croissant = await _lister(db_session, org, user, limit=2, order="date_paiement.asc",
                              include_summary=False)
    assert [item.montant_paye for item in croissant] == [Decimal("20"), Decimal("40")]

    # Le total, lui, décrit toutes les lignes et pas seulement la page.
    complet = await _lister(db_session, org, user, limit=2)
    assert complet.total == 4
    assert complet.total_montant_paye == Decimal("100")


# ---------------------------------------------------------------------------
# Le bon et ses annexes
# ---------------------------------------------------------------------------


def _fichier(nom: str, contenu: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=nom,
        file=io.BytesIO(contenu),
        headers={"content-type": content_type},
    )


@pytest.mark.asyncio
async def test_le_bon_et_ses_annexes_s_attachent_a_un_transfert_delegue(db_session, tmp_path, monkeypatch):
    """Le justificatif de dépôt bancaire ne doit pas disparaître avec la bascule."""
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.UPLOAD_ROOT", str(tmp_path))
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte)

    resultat = await upload_sortie_pdf(
        sortie_id=str(transfert.document_uuid),
        background_tasks=BackgroundTasks(),
        file=_fichier("bon.pdf", b"%PDF-1.4 bon", "application/pdf"),
        notify=False,
        attachments=[_fichier("bordereau.pdf", b"%PDF-1.4 depot", "application/pdf")],
        db=db_session, user=user, tenant_id=org.id, tenant_uuid=str(uuid.uuid4()),
    )
    assert resultat["ok"] is True

    relu = await db_session.scalar(
        select(TransfertInterne).where(TransfertInterne.id == transfert.id)
    )
    await db_session.refresh(relu)
    assert relu.pdf_path and relu.pdf_path.endswith("-bon.pdf")
    # Le nom du fichier vient de la référence de l'opération : c'est ce qui
    # permet de retrouver le bon à partir du document imprimé.
    assert relu.reference.replace("-", "") in relu.pdf_path.replace("-", "")
    assert relu.annexes and len(relu.annexes) == 1

    # La ligne d'écran rend le chemin du bon : le bouton d'impression le trouve.
    reponse = await _lister(db_session, org, user)
    assert reponse.items[0].pdf_path == relu.pdf_path


@pytest.mark.asyncio
async def test_un_uuid_inconnu_reste_un_404(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.UPLOAD_ROOT", str(tmp_path))
    org, user, _ = await _contexte(db_session)
    with pytest.raises(HTTPException) as erreur:
        await upload_sortie_pdf(
            sortie_id=str(uuid.uuid4()), background_tasks=BackgroundTasks(),
            file=_fichier("bon.pdf", b"%PDF-1.4", "application/pdf"), notify=False,
            attachments=None, db=db_session, user=user, tenant_id=org.id,
            tenant_uuid=str(uuid.uuid4()),
        )
    assert erreur.value.status_code == 404


# ---------------------------------------------------------------------------
# Ce que l'annulation d'un transfert exige, et ce qu'elle refuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contrepasser_exige_un_motif_ecrit(db_session):
    """Deux lignes restent dans les livres : sans motif, plus rien ne les explique."""
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte)

    with pytest.raises(HTTPException) as erreur:
        await update_sortie_statut(
            sortie_id=str(transfert.document_uuid),
            payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation=None),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
        )
    assert erreur.value.status_code == 400
    assert "Motif" in erreur.value.detail


@pytest.mark.asyncio
async def test_un_transfert_ne_se_revalide_pas(db_session):
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte)

    with pytest.raises(HTTPException) as erreur:
        await update_sortie_statut(
            sortie_id=str(transfert.document_uuid),
            payload=SortieFondsStatusUpdate(statut="VALIDE"),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
        )
    assert erreur.value.status_code == 400


@pytest.mark.asyncio
async def test_la_fenetre_de_trente_minutes_ne_s_applique_pas_a_une_contrepassation(db_session):
    """Elle protège une période passée d'être réécrite ; ici rien n'est réécrit.

    Le chemin historique refuse une annulation au-delà de 30 minutes parce
    qu'elle retire l'opération de sa période — qui peut être clôturée. Une
    contre-passation n'écrit que dans le présent : appliquer la fenêtre
    laisserait une erreur ancienne sans correction possible.
    """
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, date=MOMENT)
    ancien = datetime.now(timezone.utc) - timedelta(days=2)
    transfert.created_at = ancien
    await db_session.commit()

    rendu = await update_sortie_statut(
        sortie_id=str(transfert.document_uuid),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur ancienne"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
    )
    assert rendu.statut == "CONTREPASSE"


@pytest.mark.asyncio
async def test_un_transfert_deja_contrepasse_ne_se_contrepasse_pas_deux_fois(db_session):
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte)
    await update_sortie_statut(
        sortie_id=str(transfert.document_uuid),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de compte"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
    )

    with pytest.raises(HTTPException) as erreur:
        await update_sortie_statut(
            sortie_id=str(transfert.document_uuid),
            payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Encore"),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
        )
    assert erreur.value.status_code == 409


# ---------------------------------------------------------------------------
# Le classeur exporte l'écran qu'il dit exporter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_classeur_des_sorties_contient_les_transferts_delegues(db_session):
    """Un classeur amputé des lignes de son écran est un faux sur un imprimé.

    Le total du pied de colonne se calcule sur les lignes présentes : une ligne
    manquante ne fait pas qu'une absence, elle fausse la somme.
    """
    from app.api.v1.endpoints.exports import construire_classeur_sorties_fonds

    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, montant="100")
    db_session.add(_sortie_legacy(org, user, montant="50"))
    await db_session.commit()

    classeur, _nom = await construire_classeur_sorties_fonds(db_session, org.id)
    feuille = classeur["Sorties"]
    valeurs = [
        [cellule.value for cellule in ligne]
        for ligne in feuille.iter_rows()
    ]
    plates = [str(cellule) for ligne in valeurs for cellule in ligne if cellule is not None]

    assert transfert.reference in plates
    assert "Rawbank - Compte courant" in plates  # le bénéficiaire, poche qui reçoit
    # Le transfert est signalé comme tel, jamais fondu dans les espèces.
    assert plates.count("Transfert interne") >= 1
    assert 100.0 in [
        cellule for ligne in valeurs for cellule in ligne if isinstance(cellule, float)
    ]


# ---------------------------------------------------------------------------
# Volume et net : ce que le pied de colonne dit vraiment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_volume_compte_les_mouvements_le_net_dit_ce_qui_a_bouge(db_session):
    """Un versement contre-passé : volume doublé, net nul.

    Le volume ne peut pas mentir sur le nombre de mouvements — il y en a bien
    eu deux, et n'en compter qu'un masquerait une opération réelle. Mais seul
    le net répond à « combien d'argent a changé de poche », et sans lui l'écran
    affiche le double sans rien qui dise que la trésorerie est revenue.

    Filtrer les contre-passés pour obtenir le net serait l'erreur : cela
    afficherait la ligne inverse sans son original, donc de l'argent créé de
    rien. C'est la lecture qu'on complète, jamais l'agrégat qu'on ampute.
    """
    org, user, compte = await _contexte(db_session)
    transfert = await _transfert(db_session, org, user, compte, montant="250")

    avant = await _lister(db_session, org, user)
    assert avant.total_transferts_internes == Decimal("250")
    assert avant.total_transferts_internes_net == Decimal("250")  # caisse → banque

    await update_sortie_statut(
        sortie_id=str(transfert.document_uuid),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de compte"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
    )

    apres = await _lister(db_session, org, user)
    assert len(apres.items) == 2
    assert apres.total_transferts_internes == Decimal("500")  # deux mouvements
    assert apres.total_transferts_internes_net == Decimal("0")  # rien n'a bougé


@pytest.mark.asyncio
async def test_le_net_est_signe_et_compte_les_deux_moteurs(db_session):
    """Négatif quand l'argent est remonté vers la caisse, et les deux sources comptent."""
    org, user, compte = await _contexte(db_session)
    # Chemin historique : un versement de 100 (caisse → banque).
    db_session.add(_sortie_legacy(
        org, user, montant="100", type_sortie="versement_banque",
        compte_id=compte.id, canal="CAISSE",
    ))
    # Chemin historique : un approvisionnement de 40 (banque → caisse).
    db_session.add(_sortie_legacy(
        org, user, montant="40", type_sortie="approvisionnement_caisse",
        compte_id=compte.id, canal="BANQUE",
    ))
    # Moteur dédié : un approvisionnement de 300 (banque → caisse).
    await _transfert(db_session, org, user, compte, montant="300", sens="appro")
    await db_session.commit()

    vue = await _lister(db_session, org, user)
    assert vue.total_transferts_internes == Decimal("440")  # 100 + 40 + 300
    # 100 monté, 340 redescendu : net de 240 revenus vers la caisse.
    assert vue.total_transferts_internes_net == Decimal("-240")


@pytest.mark.asyncio
async def test_le_net_suit_les_filtres_comme_le_volume(db_session):
    org, user, compte = await _contexte(db_session)
    await _transfert(db_session, org, user, compte, montant="250", sens="versement")
    await _transfert(db_session, org, user, compte, montant="90", sens="appro")
    await db_session.commit()

    tout = await _lister(db_session, org, user)
    assert (tout.total_transferts_internes, tout.total_transferts_internes_net) == (
        Decimal("340"), Decimal("160"),
    )

    versements = await _lister(db_session, org, user, type_sortie="versement_banque")
    assert (versements.total_transferts_internes, versements.total_transferts_internes_net) == (
        Decimal("250"), Decimal("250"),
    )

    appros = await _lister(db_session, org, user, type_sortie="approvisionnement_caisse")
    assert (appros.total_transferts_internes, appros.total_transferts_internes_net) == (
        Decimal("90"), Decimal("-90"),
    )
