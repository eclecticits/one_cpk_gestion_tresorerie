"""Statut « Actif » déclaré à la main : rendre un membre inactif, ou le réactiver.

Seul le fichier des personnes physiques porte une colonne « Actif ». Une société
n'avait donc jamais de statut, et un EC mal renseigné ne pouvait pas être
corrigé. La déclaration comble les deux : elle prime sur le fichier, tient au
membre (conseil + n° d'ordre) comme la sortie, et vaut à partir de l'exercice
de sa date d'effet.

Elle ne change pas la conclusion : un membre inactif reste jugé, il est
seulement écarté des comptes « Actifs » (tableau de bord, filtres, rapport).
Une société sans déclaration est tenue pour active.

Une seule déclaration est en vigueur par membre. En faire une nouvelle annule
la précédente ; annuler revient au fichier (ou, pour une société, à « active »).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from .audit import record_tableau_audit
from .models import TableauStatutActif
from .sorties import _enregistrer_piece, cle_numero, est_morale

#: Motifs proposés, selon le statut déclaré et la personne ; le champ reste libre.
MOTIFS_SUGGERES: dict[str, dict[str, list[str]]] = {
    "inactif": {
        "PM": [
            "Mise en sommeil déclarée",
            "Aucune activité constatée",
            "Pas d'adresse identifiable",
            "Société injoignable : téléphone et e-mail sans réponse",
        ],
        "PP": [
            "Cessation temporaire d'activité déclarée",
            "Aucune activité constatée",
            "Erreur du fichier des membres",
        ],
    },
    "actif": {
        "PM": ["Reprise d'activité déclarée", "Adresse du siège confirmée"],
        "PP": ["Reprise d'activité déclarée", "Erreur du fichier des membres"],
    },
}


def _texte(valeur: str | None, longueur: int) -> str | None:
    texte = " ".join((valeur or "").split())
    return texte[:longueur] or None


def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def libelle_statut(declaration: TableauStatutActif) -> str:
    """« Inactif depuis le 01/11/2026 : Pas d'adresse identifiable »."""
    morale = declaration.personne == "PM"
    etat = ("Active" if morale else "Actif") if declaration.actif else ("Inactive" if morale else "Inactif")
    return f"{etat} depuis le {declaration.date_effet.strftime('%d/%m/%Y')} : {declaration.motif}"


def statut_payload(declaration: TableauStatutActif | None) -> dict[str, Any] | None:
    if declaration is None:
        return None
    return {
        "id": declaration.id,
        "actif": declaration.actif,
        "actif_fichier": declaration.actif_fichier,
        "date_effet": declaration.date_effet,
        "motif": declaration.motif,
        "libelle": libelle_statut(declaration),
        "reference": declaration.reference,
        "observation": declaration.observation,
        "piece_path": declaration.piece_path,
        "piece_nom": declaration.piece_nom,
        "created_at": declaration.created_at,
        "annule_le": declaration.annule_le,
        "motif_annulation": declaration.motif_annulation,
    }


async def situation_du_membre(
    db: AsyncSession, organisation_id: int, exercice: str | None, numero_ordre: str,
) -> dict[str, Any]:
    """Le membre tel que la Base le voit : nom, catégorie, statut retenu et statut du fichier."""
    # Import différé : le service importe ce module.
    from .repository import _actifs_membres, cle_numero_sql
    from .service import get_base_tableau

    cle = cle_numero(numero_ordre)
    if not cle:
        raise _refus("Un membre sans n° d'ordre n'a pas de statut : corrigez d'abord son numéro.")
    base = await get_base_tableau(db, [organisation_id], exercice=exercice, recherche=cle, situation="tous")
    for ligne in [*base["dossiers"], *base["membres_a_completer"]]:
        lire = ligne.get if isinstance(ligne, dict) else lambda k, l=ligne: getattr(l, k, None)
        if cle_numero(lire("numero_ordre")) != cle:
            continue
        if lire("sortie"):
            raise _refus("Ce membre est sorti du Tableau : son statut « Actif » ne compte plus.")
        categorie = lire("categorie")
        actif_fichier = None
        if not est_morale(categorie):
            fichier = _actifs_membres([organisation_id], base["exercice"])
            actif_fichier = (await db.execute(
                select(fichier.c.actif).where(
                    fichier.c.organisation_id == organisation_id, cle_numero_sql(fichier.c.numero_ordre) == cle,
                ).limit(1)
            )).scalar_one_or_none()
        return {
            "exercice": base["exercice"],
            "numero_ordre": cle,
            "nom": " ".join(x for x in (lire("nom"), lire("prenom")) if x),
            "categorie": categorie,
            "personne": "PM" if est_morale(categorie) else "PP",
            "actif": lire("actif"),
            "actif_fichier": actif_fichier,
            "statut_actif": lire("statut_actif"),
        }
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Membre {cle} introuvable dans la Base de l'exercice.")


async def _en_vigueur(db: AsyncSession, organisation_id: int, cle: str) -> TableauStatutActif | None:
    return (await db.execute(
        select(TableauStatutActif).where(
            TableauStatutActif.organisation_id == organisation_id,
            TableauStatutActif.numero_ordre == cle,
            TableauStatutActif.annule_le.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()


async def declarer(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    tenant_uuid: str,
    *,
    membre: dict[str, Any],
    actif: bool,
    date_effet: date,
    motif: str,
    reference: str | None = None,
    observation: str | None = None,
    piece: UploadFile | None = None,
) -> TableauStatutActif:
    """Déclare le membre actif ou inactif ; la déclaration en vigueur est annulée."""
    cle = membre["numero_ordre"]
    if membre.get("actif") is actif:
        etat = "actif" if actif else "inactif"
        raise _refus(f"Ce membre est déjà {etat} : il n'y a rien à déclarer.")
    if date_effet > date.today():
        raise _refus("La date d'effet ne peut pas être dans le futur.")
    texte_motif = _texte(motif, 2000)
    if not texte_motif:
        raise _refus("Le motif est obligatoire.")

    precedente = await _en_vigueur(db, organisation_id, cle)
    maintenant = datetime.now(timezone.utc)
    if precedente is not None:
        precedente.annule_le = maintenant
        precedente.annule_par = user.id
        precedente.motif_annulation = "Remplacée par une nouvelle déclaration"
        # L'index unique ne vaut que pour la déclaration en vigueur : l'annulation doit partir avant.
        await db.flush()

    declaration = TableauStatutActif(
        organisation_id=organisation_id,
        numero_ordre=cle,
        nom=_texte(membre.get("nom"), 300) or cle,
        personne=membre["personne"],
        actif=actif,
        actif_fichier=membre.get("actif_fichier"),
        date_effet=date_effet,
        motif=texte_motif,
        reference=_texte(reference, 200),
        observation=(observation or "").strip()[:2000] or None,
        created_by=user.id,
        created_at=maintenant,
    )
    if piece is not None and piece.filename:
        declaration.piece_path, declaration.piece_nom = await _enregistrer_piece(
            piece, tenant_uuid, cle, racine="tableau-statuts-actifs",
        )
    db.add(declaration)
    await db.flush()
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.statut_actif.declare",
        target_type="membre",
        target_id=cle,
        metadata_json={
            "actif": actif,
            "actif_fichier": membre.get("actif_fichier"),
            "date_effet": date_effet,
            "motif": texte_motif,
            "remplace": precedente.id if precedente else None,
        },
    )
    await db.commit()
    await db.refresh(declaration)
    return declaration


async def annuler(db: AsyncSession, user: User, organisation_id: int, declaration_id: int, motif: str) -> None:
    """Annule la déclaration : le statut du fichier revient (une société redevient active)."""
    texte_motif = _texte(motif, 2000)
    if not texte_motif:
        raise _refus("Le motif de l'annulation est obligatoire.")
    declaration = (await db.execute(
        select(TableauStatutActif).where(
            TableauStatutActif.id == declaration_id,
            TableauStatutActif.organisation_id == organisation_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if declaration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Déclaration introuvable.")
    if declaration.annule_le is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette déclaration est déjà annulée.")
    declaration.annule_le = datetime.now(timezone.utc)
    declaration.annule_par = user.id
    declaration.motif_annulation = texte_motif
    await db.flush()
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.statut_actif.annule",
        target_type="membre",
        target_id=declaration.numero_ordre,
        metadata_json={"actif": declaration.actif, "motif": texte_motif},
    )
    await db.commit()


async def historique(db: AsyncSession, organisation_id: int, numero_ordre: str) -> list[dict[str, Any]]:
    """Toutes les déclarations du membre, la plus récente d'abord."""
    cle = cle_numero(numero_ordre)
    if not cle:
        return []
    rows = (await db.execute(
        select(TableauStatutActif).where(
            TableauStatutActif.organisation_id == organisation_id,
            TableauStatutActif.numero_ordre == cle,
        ).order_by(TableauStatutActif.created_at.desc(), TableauStatutActif.id.desc())
    )).scalars().all()
    return [p for p in (statut_payload(d) for d in rows) if p]
