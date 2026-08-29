"""Les transferts du moteur dédié, lus depuis l'écran des sorties de fonds.

Un versement à la banque saisi sur `POST /sorties-fonds` s'écrira, une fois le
drapeau de bascule ouvert, dans `transferts_internes` et non plus dans
`sorties_fonds`. L'écran qui l'a saisi doit continuer à l'afficher, et son pied
de colonne « transferts internes » à le compter — sinon l'opération disparaît
sous les yeux du caissier à la seconde où elle est enregistrée.

Ce module projette ces transferts dans la forme de lecture de l'écran
(`SortieFondsOut`). Trois règles le gouvernent.

**Il ne lit que les transferts adressables par ce chemin**, c'est-à-dire ceux
qui portent un `document_uuid`. Un transfert saisi directement sur
`/transferts-internes` n'a jamais figuré sur cet écran et n'a pas à y
apparaître ; il a le sien.

**La projection est inconditionnelle** : elle ne consulte pas le drapeau.
Refermer le drapeau n'efface aucune ligne déjà écrite ; une lecture qui en
dépendrait les ferait disparaître de l'écran tout en les laissant dans les
soldes de trésorerie. C'est aussi ce qui rend le changement testable pendant
que la table dédiée est encore vide : rien ne change tant que rien n'y est
écrit.

**Aucun filtre sur `TransfertInterne.statut`.** La correction est additive :
l'original (`CONTREPASSE`) et la ligne inverse qui le compense (`EXECUTE`)
coexistent et s'annulent arithmétiquement. Masquer l'original tout en gardant
l'inverse afficherait — et sommerait — de l'argent venu de nulle part. Le
statut est de l'affichage, jamais un filtre d'agrégation (cf. le modèle
`TransfertInterne`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.transfert_interne import (
    STATUT_CONTREPASSE,
    STATUT_EXECUTE,
    TransfertInterne,
)
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsOut

TYPE_VERSEMENT_BANQUE = "versement_banque"
TYPE_APPROVISIONNEMENT_CAISSE = "approvisionnement_caisse"

#: Sens du transfert → `type_sortie` historique équivalent. Un virement de
#: banque à banque n'a pas d'équivalent : il n'a jamais pu être saisi sur cet
#: écran, et n'y est donc pas projeté.
SENS_VERS_TYPE: dict[tuple[str, str], str] = {
    ("CAISSE", "BANQUE"): TYPE_VERSEMENT_BANQUE,
    ("BANQUE", "CAISSE"): TYPE_APPROVISIONNEMENT_CAISSE,
}
TYPE_VERS_SENS: dict[str, tuple[str, str]] = {
    type_sortie: sens for sens, type_sortie in SENS_VERS_TYPE.items()
}

#: Statut du moteur dédié → statut affiché sur l'écran des sorties de fonds.
#:
#: `CONTREPASSE` n'est **pas** `ANNULEE`, et le mot compte : une annulation
#: historique retire l'opération des totaux, une contre-passation la laisse et
#: lui adjoint son inverse. Les confondre ferait croire à l'écran qu'il peut
#: masquer la ligne.
STATUT_AFFICHE: dict[str, str] = {
    STATUT_EXECUTE: "VALIDE",
    STATUT_CONTREPASSE: "CONTREPASSE",
}

#: Un transfert interne ne circule ni en espèces ni par chèque : rien ne sort de
#: l'organisation. La valeur reprend celle que `POST /sorties-fonds` force déjà
#: sur le chemin historique pour ces deux types, de sorte qu'un filtre par mode
#: de paiement rende les mêmes lignes des deux côtés.
MODE_PAIEMENT = "cash"

#: Horodatage retenu quand une ligne n'a pas de date : il la place en fin de tri
#: décroissant, comme le `NULLS LAST` demandé au SQL côté historique.
DATE_MINIMALE = datetime.min.replace(tzinfo=timezone.utc)

CompteSource = aliased(CompteBancaire)
BanqueSource = aliased(Banque)
CompteDestination = aliased(CompteBancaire)
BanqueDestination = aliased(Banque)
#: `execute_par` n'est pas une clé étrangère déclarée : la jointure est explicite.
Executant = aliased(User)


@dataclass(frozen=True)
class FiltresSorties:
    """Les filtres de `GET /sorties-fonds`, tels qu'un transfert peut les subir."""

    date_debut: datetime | None = None
    date_fin: datetime | None = None
    type_sortie: str | None = None
    mode_paiement: str | None = None
    canal: str | None = None
    compte_bancaire_id: int | None = None
    statut: str | None = None
    reference: str | None = None
    #: Le filtre porte sur une réquisition (identifiant ou numéro).
    filtre_requisition: bool = False
    #: L'utilisateur n'a pas accès au menu et ne voit que ses services.
    restreint_aux_services: bool = False


def peut_contenir_un_transfert(filtres: FiltresSorties) -> bool:
    """Ce jeu de filtres peut-il désigner un transfert du moteur dédié ?

    Répondre non permet de ne pas interroger la table du tout — et surtout de
    ne pas rendre une ligne qu'un filtre excluait : un transfert n'a ni
    réquisition, ni service, ni annulation.
    """
    if filtres.filtre_requisition or filtres.restreint_aux_services:
        return False
    if filtres.type_sortie and filtres.type_sortie.lower() not in TYPE_VERS_SENS:
        return False
    if filtres.mode_paiement and filtres.mode_paiement.lower() != MODE_PAIEMENT:
        return False
    statut = (filtres.statut or "").strip().upper()
    # `ANNULEE` est un statut du chemin historique seul : le moteur dédié ne
    # retire jamais une opération, il la compense.
    if statut and statut not in ("ALL", "VALIDE", STATUT_CONTREPASSE):
        return False
    return True


def _jambe_bancaire():
    """Le compte bancaire de l'opération, quel que soit le sens.

    Exactement une des deux jambes est bancaire pour les sens projetés ici : la
    caisse n'a pas de compte, son identifiant est NULL. C'est le compte que le
    chemin historique stocke dans `compte_bancaire_id`, dans les deux sens.
    """
    return func.coalesce(TransfertInterne.destination_id, TransfertInterne.source_id)


def _conditions(tenant_id: int, filtres: FiltresSorties) -> list:
    conditions = [
        TransfertInterne.organisation_id == tenant_id,
        # Seuls les transferts saisis par le chemin `sorties-fonds` en portent
        # un : c'est ce qui les rend adressables depuis cet écran.
        TransfertInterne.document_uuid.isnot(None),
    ]

    sens_admis = (
        [TYPE_VERS_SENS[filtres.type_sortie.lower()]]
        if filtres.type_sortie
        else list(SENS_VERS_TYPE)
    )
    if filtres.canal:
        # Le canal est la poche qui **envoie** : un versement sort de la caisse,
        # un approvisionnement sort de la banque. Même convention que le champ
        # `canal` du chemin historique.
        canal = filtres.canal.upper()
        sens_admis = [sens for sens in sens_admis if sens[0] == canal]
    conditions.append(
        or_(
            *(
                and_(
                    TransfertInterne.source_type == source,
                    TransfertInterne.destination_type == destination,
                )
                for source, destination in sens_admis
            )
        )
        if sens_admis
        # Aucun sens admis : une condition toujours fausse plutôt qu'une
        # requête omise, pour que l'appelant garde un chemin unique.
        else false()
    )

    if filtres.date_debut is not None:
        conditions.append(TransfertInterne.date_transfert >= filtres.date_debut)
    if filtres.date_fin is not None:
        conditions.append(TransfertInterne.date_transfert <= filtres.date_fin)
    if filtres.compte_bancaire_id:
        conditions.append(_jambe_bancaire() == filtres.compte_bancaire_id)
    if filtres.reference:
        conditions.append(TransfertInterne.reference.ilike(f"%{filtres.reference}%"))

    statut = (filtres.statut or "").strip().upper()
    if statut == STATUT_CONTREPASSE:
        conditions.append(TransfertInterne.statut == STATUT_CONTREPASSE)
    # `VALIDE` et l'absence de filtre ne restreignent rien : voir l'invariant en
    # tête de module. Un original contre-passé reste affiché et compté, sa
    # correction étant portée par une ligne distincte.
    return conditions


def _requete_jointe():
    """Le transfert et ses deux jambes, sans filtre — les jointures seules."""
    return (
        select(
            TransfertInterne,
            CompteSource,
            BanqueSource,
            CompteDestination,
            BanqueDestination,
            Executant,
        )
        .outerjoin(CompteSource, TransfertInterne.source_id == CompteSource.id)
        .outerjoin(BanqueSource, CompteSource.banque_id == BanqueSource.id)
        .outerjoin(CompteDestination, TransfertInterne.destination_id == CompteDestination.id)
        .outerjoin(BanqueDestination, CompteDestination.banque_id == BanqueDestination.id)
        .outerjoin(Executant, TransfertInterne.execute_par == Executant.id)
    )


def _requete(tenant_id: int, filtres: FiltresSorties):
    return _requete_jointe().where(*_conditions(tenant_id, filtres))


def _libelle_compte(banque, compte) -> str:
    return " - ".join(
        part
        for part in (getattr(banque, "nom", None), getattr(compte, "intitule", None))
        if part
    )


def _poche(type_poche: str, banque, compte) -> str:
    return "Caisse centrale" if type_poche == "CAISSE" else (_libelle_compte(banque, compte) or "Banque")


def _motif(transfert: TransfertInterne) -> str:
    if transfert.transfert_origine_id is not None:
        return "Contre-passation d'un transfert interne"
    if transfert.source_type == "CAISSE":
        return "Versement à la banque"
    return "Approvisionnement de la caisse"


def _utilisateur(personne: User | None) -> dict | None:
    if personne is None or personne.id is None:
        return None
    return {
        "id": str(personne.id),
        "prenom": personne.prenom,
        "nom": personne.nom,
        "email": personne.email,
    }


def projeter(ligne) -> SortieFondsOut:
    """Un transfert du moteur dédié, dans la forme que l'écran sait lire."""
    transfert, compte_source, banque_source, compte_dest, banque_dest, executant = ligne
    return SortieFondsOut(
        # L'écran adresse une opération par UUID ; la clé primaire d'un
        # transfert est un entier. C'est l'UUID annoncé à la création qui fait
        # identité, et c'est lui que `POST /sorties-fonds/{id}/pdf` retrouve.
        id=transfert.document_uuid,
        type_sortie=SENS_VERS_TYPE[(transfert.source_type, transfert.destination_type)],
        montant_paye=Decimal(transfert.montant or 0),
        date_paiement=transfert.date_transfert,
        mode_paiement=MODE_PAIEMENT,
        reference=transfert.reference,
        reference_numero=transfert.reference,
        devise=(transfert.devise or "USD").upper(),
        canal=transfert.source_type,
        compte_bancaire_id=transfert.destination_id or transfert.source_id,
        idempotency_key=transfert.idempotency_key,
        pdf_path=transfert.pdf_path,
        origine="transfert_interne",
        statut=STATUT_AFFICHE.get(transfert.statut, transfert.statut),
        # La table dédiée ne porte pas ce champ, et la file de comptabilisation
        # manuelle ne couvre que `sorties_fonds` : cet écran ne lit pas la
        # valeur, mais elle n'est pas une affirmation sur l'écriture générée.
        statut_comptabilisation="NON_COMPTABILISEE",
        motif_annulation=transfert.motif_contrepassation,
        annulee_le=transfert.contrepasse_le,
        annulee_par_id=str(transfert.contrepasse_par) if transfert.contrepasse_par else None,
        motif=_motif(transfert),
        # Le bénéficiaire d'un mouvement interne est la poche qui reçoit : c'est
        # la seule réponse vraie à « où est allé l'argent ».
        beneficiaire=_poche(transfert.destination_type, banque_dest, compte_dest),
        annexes=transfert.annexes,
        created_by=str(transfert.execute_par) if transfert.execute_par else None,
        created_by_user=_utilisateur(executant),
        created_at=transfert.created_at,
    )


async def lister(
    db: AsyncSession,
    *,
    tenant_id: int,
    filtres: FiltresSorties,
    limit: int,
) -> list[SortieFondsOut]:
    """Les `limit` transferts les plus récents que ces filtres désignent.

    Le `limit` transmis doit couvrir `offset + limit` de l'appelant : borner
    chaque source à sa propre page rendrait les N premières lignes de chacune,
    c'est-à-dire pas les N plus récentes de l'ensemble.
    """
    if not peut_contenir_un_transfert(filtres):
        return []
    query = (
        _requete(tenant_id, filtres)
        .order_by(TransfertInterne.date_transfert.desc(), TransfertInterne.id.desc())
        .limit(limit)
    )
    return [projeter(ligne) for ligne in (await db.execute(query)).all()]


async def compter_et_sommer(
    db: AsyncSession, *, tenant_id: int, filtres: FiltresSorties
) -> tuple[int, Decimal]:
    """Nombre et montant cumulé des transferts que ces filtres désignent.

    Les deux voyagent ensemble parce qu'ils doivent décrire exactement les
    mêmes lignes que `lister` : un total qu'aucune liste ne justifie est le
    défaut que toute cette bascule cherche à éviter.
    """
    if not peut_contenir_un_transfert(filtres):
        return 0, Decimal("0")
    query = select(
        func.count(TransfertInterne.id),
        func.coalesce(func.sum(TransfertInterne.montant), 0),
    ).where(*_conditions(tenant_id, filtres))
    nombre, montant = (await db.execute(query)).one()
    return int(nombre or 0), Decimal(montant or 0)


async def par_document_uuid(
    db: AsyncSession, *, tenant_id: int, document_uuid: UUID
) -> TransfertInterne | None:
    """Le transfert que cet UUID désigne, ou None.

    Sert aux routes qui adressent une opération par son identifiant documentaire
    (`/{id}/pdf`, `/{id}/statut`) et qui doivent répondre pour les deux moteurs.
    """
    return await db.scalar(
        select(TransfertInterne).where(
            TransfertInterne.document_uuid == document_uuid,
            TransfertInterne.organisation_id == tenant_id,
        )
    )


async def projeter_par_document_uuid(
    db: AsyncSession, *, tenant_id: int, document_uuid: UUID
) -> SortieFondsOut | None:
    """Le transfert que cet UUID désigne, dans la forme de lecture de l'écran.

    Aucune condition de sens ni de statut : la route qui vient d'agir sur une
    opération doit pouvoir la rendre telle qu'elle est désormais, y compris
    contre-passée.
    """
    ligne = (
        await db.execute(
            _requete_jointe().where(
                TransfertInterne.document_uuid == document_uuid,
                TransfertInterne.organisation_id == tenant_id,
            )
        )
    ).first()
    return projeter(ligne) if ligne is not None else None


def cle_de_tri(order: str | None):
    """Clé Python reproduisant `_parse_order`, pour fusionner les deux sources.

    Retourne `(clé, décroissant)`. Une date absente vaut `DATE_MINIMALE`, ce que
    le SQL reproduit en plaçant explicitement les NULL du côté des plus petites
    valeurs : sans cet accord, une ligne sans date de paiement changerait de
    position selon qu'un transfert existe ou non.
    """
    champ, _, sens = (order or "date_paiement.desc").partition(".")
    decroissant = sens.lower() != "asc"
    if champ not in ("date_paiement", "created_at", "montant_paye"):
        champ, decroissant = "date_paiement", True

    def cle(item: SortieFondsOut):
        valeur = getattr(item, champ, None)
        if isinstance(valeur, datetime):
            return valeur if valeur.tzinfo is not None else valeur.replace(tzinfo=timezone.utc)
        if valeur is None:
            return DATE_MINIMALE if champ != "montant_paye" else Decimal("-Infinity")
        return valeur

    return cle, decroissant


async def libelle_poche_destination(db: AsyncSession, *, transfert: TransfertInterne) -> str:
    """Nom de la poche qui reçoit : « Caisse centrale » ou « Banque - Compte ».

    Le bénéficiaire d'un mouvement interne. Requête faite à la demande — seule
    la notification du bon en a besoin, et seulement pour un transfert.
    """
    if transfert.destination_type == "CAISSE":
        return "Caisse centrale"
    ligne = (
        await db.execute(
            select(CompteBancaire, Banque)
            .outerjoin(Banque, CompteBancaire.banque_id == Banque.id)
            .where(CompteBancaire.id == transfert.destination_id)
        )
    ).first()
    if ligne is None:
        return "Banque"
    compte, banque = ligne
    return _libelle_compte(banque, compte) or "Banque"


async def lignes_export(
    db: AsyncSession, *, tenant_id: int, filtres: FiltresSorties
) -> list[dict]:
    """Les transferts délégués, dans la forme dont le classeur a besoin.

    Le classeur des sorties de fonds nomme sa source par l'objet compte
    bancaire (« Banque source », « Compte bancaire ») que la projection d'écran
    ne porte pas : elle n'expose qu'un identifiant. Cette variante rend donc les
    entités jointes plutôt qu'un `SortieFondsOut`.

    Elle existe pour une raison simple : un classeur qui ne contient pas les
    lignes de l'écran qu'il exporte est un faux sur un document imprimé.
    """
    if not peut_contenir_un_transfert(filtres):
        return []
    query = _requete(tenant_id, filtres).order_by(TransfertInterne.created_at.desc())
    lignes = []
    for transfert, compte_source, banque_source, compte_dest, banque_dest, executant in (
        await db.execute(query)
    ).all():
        # La jambe bancaire : celle qui a un numéro de compte à afficher. Les
        # libellés sont rendus déjà résolus — les relations d'un objet aliasé ne
        # sont pas chargées, et les lire depuis le classeur déclencherait un
        # accès paresseux hors contexte async, qui fait échouer l'export entier.
        if transfert.source_type == "BANQUE":
            compte_bancaire, banque = compte_source, banque_source
        else:
            compte_bancaire, banque = compte_dest, banque_dest
        lignes.append(
            {
                "created_at": transfert.created_at,
                "date": transfert.date_transfert,
                "type_sortie": SENS_VERS_TYPE[
                    (transfert.source_type, transfert.destination_type)
                ],
                # Le canal est la poche qui envoie.
                "canal": transfert.source_type,
                "banque_nom": getattr(banque, "nom", None),
                "compte_numero": getattr(compte_bancaire, "numero_compte", None),
                "auteur": executant,
                "beneficiaire": _poche(transfert.destination_type, banque_dest, compte_dest),
                "motif": _motif(transfert),
                "montant": Decimal(transfert.montant or 0),
                "reference": transfert.reference or "",
                "statut": STATUT_AFFICHE.get(transfert.statut, transfert.statut),
            }
        )
    return lignes
