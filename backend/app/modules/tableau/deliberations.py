"""Délibérations de la commission : mettre un membre en règle, ou l'en retirer.

La délibération fixe la conclusion d'un membre pour un exercice à la place du
calcul automatique. Elle tient au membre (conseil + n° d'ordre), comme la
sortie : elle vaut pour les EC et les sociétés, avec ou sans dossier, et un
réimport ne la fait pas disparaître.

Le calcul automatique n'est jamais perdu : il reste lisible à côté de la
décision, et si les données changent ensuite au point de conduire à une autre
conclusion, l'écart est signalé — la décision tient, la commission la revoit.

Une seule délibération est en vigueur par membre et par exercice. En prendre
une nouvelle révoque la précédente ; une révocation exige un motif et garde
la délibération dans l'historique.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from . import verdict as verdict_engine
from .audit import record_tableau_audit
from .models import TableauDeliberation
from .sorties import _enregistrer_piece, cle_numero, est_morale

CONCLUSIONS = (verdict_engine.INSCRIT, verdict_engine.NON_INSCRIT, verdict_engine.A_DELIBERER)
CRITERES = ("cotisation", "formation", "assurance", "chiffre_affaires")

#: Motifs proposés dans la fenêtre ; le champ reste libre.
MOTIFS_SUGGERES: dict[str, list[str]] = {
    "mise_en_regle": [
        "Cotisation régularisée après la date de situation",
        "Formation justifiée par des pièces probantes",
        "Attestation d'assurance reçue",
        "Déclaration du chiffre d'affaires reçue",
        "Cas de force majeure",
        "Erreur dans les données importées",
    ],
    "retrait": [
        "Paiement annulé ou rejeté",
        "Pièce justificative non probante",
        "Fausse déclaration",
        "Sanction disciplinaire",
        "Erreur dans les données importées",
    ],
}

#: Motifs propres aux sociétés, proposés en tête de liste pour un retrait.
MOTIFS_RETRAIT_SOCIETE = [
    "Pas d'adresse identifiable",
    "Siège social introuvable à l'adresse déclarée",
    "Société injoignable : téléphone et e-mail sans réponse",
]


def motifs_suggeres(categorie: str | None) -> dict[str, list[str]]:
    """Les motifs proposés pour ce membre : une société a les siens en plus."""
    if not est_morale(categorie):
        return MOTIFS_SUGGERES
    return {**MOTIFS_SUGGERES, "retrait": [*MOTIFS_RETRAIT_SOCIETE, *MOTIFS_SUGGERES["retrait"]]}


def _texte(valeur: str | None, longueur: int) -> str | None:
    texte = " ".join((valeur or "").split())
    return texte[:longueur] or None


def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def libelle_deliberation(deliberation: TableauDeliberation) -> str:
    """« En règle par délibération de la commission (séance du 12/11) : motif »."""
    conclusion = verdict_engine.libelle_conclusion(deliberation.conclusion) or deliberation.conclusion
    texte = f"{conclusion} par délibération de la commission"
    if deliberation.reference_seance:
        texte += f" ({deliberation.reference_seance})"
    return f"{texte} : {deliberation.motif}"


def deliberation_payload(
    deliberation: TableauDeliberation | None, verdict_automatique: str | None = None,
) -> dict[str, Any] | None:
    if deliberation is None:
        return None
    return {
        "id": deliberation.id,
        "conclusion": deliberation.conclusion,
        "conclusion_automatique": deliberation.conclusion_automatique,
        # Ce que dit le calcul aujourd'hui, avec les données actuelles.
        "verdict_automatique": verdict_automatique,
        "diverge": bool(verdict_automatique) and verdict_automatique != deliberation.conclusion
        and verdict_automatique != deliberation.conclusion_automatique,
        "criteres": list(deliberation.criteres or []),
        "motif": deliberation.motif,
        "libelle": libelle_deliberation(deliberation),
        "reference_seance": deliberation.reference_seance,
        "observation": deliberation.observation,
        "piece_path": deliberation.piece_path,
        "piece_nom": deliberation.piece_nom,
        "created_at": deliberation.created_at,
    }


def appliquer(verdict: dict[str, Any], deliberation: TableauDeliberation | None) -> dict[str, Any]:
    """Le verdict tel que la commission l'a fixé, le calcul automatique gardé à côté."""
    automatique = verdict.get("conclusion")
    if deliberation is None:
        return {**verdict, "deliberation": None}
    return {
        **verdict,
        "conclusion": deliberation.conclusion,
        "motif": libelle_deliberation(deliberation),
        "deliberation": deliberation_payload(deliberation, automatique),
    }


async def deliberations_en_vigueur(
    db: AsyncSession, organisation_ids: list[int], exercice: str | None,
) -> dict[tuple[int, str], TableauDeliberation]:
    """Délibérations non révoquées de l'exercice, par (conseil, n° d'ordre normalisé)."""
    if not exercice or not organisation_ids:
        return {}
    rows = (await db.execute(
        select(TableauDeliberation).where(
            TableauDeliberation.organisation_id.in_(organisation_ids),
            TableauDeliberation.exercice == exercice,
            TableauDeliberation.revoquee_le.is_(None),
        )
    )).scalars().all()
    return {(d.organisation_id, d.numero_ordre): d for d in rows}


def pour_membre(
    deliberations: dict[tuple[int, str], TableauDeliberation], organisation_id: int | None, numero: str | None,
) -> TableauDeliberation | None:
    cle = cle_numero(numero)
    if organisation_id is None or not cle:
        return None
    return deliberations.get((organisation_id, cle))


async def _en_vigueur(db: AsyncSession, organisation_id: int, exercice: str, cle: str) -> TableauDeliberation | None:
    return (await db.execute(
        select(TableauDeliberation).where(
            TableauDeliberation.organisation_id == organisation_id,
            TableauDeliberation.exercice == exercice,
            TableauDeliberation.numero_ordre == cle,
            TableauDeliberation.revoquee_le.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()


async def _invalider(db: AsyncSession, organisation_id: int, exercice: str) -> None:
    # Import différé : le service importe ce module.
    from .service import _invalider_analyses

    await _invalider_analyses(db, organisation_id, exercice)


async def situation_du_membre(
    db: AsyncSession, organisation_id: int, exercice: str | None, numero_ordre: str,
) -> dict[str, Any]:
    """Le membre tel que la Base le juge : nom, catégorie, et ce que dit le calcul seul."""
    # Import différé : le service importe ce module.
    from .service import get_base_tableau

    cle = cle_numero(numero_ordre)
    if not cle:
        raise _refus("Un membre sans n° d'ordre ne peut pas être délibéré : corrigez d'abord son numéro.")
    base = await get_base_tableau(db, [organisation_id], exercice=exercice, recherche=cle, situation="tous")
    for ligne in [*base["dossiers"], *base["membres_a_completer"]]:
        lire = ligne.get if isinstance(ligne, dict) else lambda k, l=ligne: getattr(l, k, None)
        if cle_numero(lire("numero_ordre")) != cle:
            continue
        if lire("sortie"):
            raise _refus("Ce membre est sorti du Tableau : il n'y a plus rien à délibérer.")
        deliberation = lire("deliberation")
        nom = " ".join(x for x in (lire("nom"), lire("prenom")) if x)
        return {
            "exercice": base["exercice"],
            "numero_ordre": cle,
            "nom": nom,
            "categorie": lire("categorie"),
            "conclusion": lire("conclusion"),
            "conclusion_automatique": deliberation["verdict_automatique"] if deliberation else lire("conclusion"),
            "deliberation": deliberation,
        }
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Membre {cle} introuvable dans la Base de l'exercice.")


def _valider(conclusion: str, motif: str, criteres: list[str]) -> str:
    """Contrôles communs à la délibération d'un membre et au lot. Renvoie le motif nettoyé."""
    if conclusion not in CONCLUSIONS:
        raise _refus("Décision inconnue : en règle, non en règle ou à délibérer.")
    texte_motif = _texte(motif, 2000)
    if not texte_motif:
        raise _refus("Le motif de la délibération est obligatoire.")
    inconnus = [c for c in criteres if c not in CRITERES]
    if inconnus:
        raise _refus(f"Critère inconnu : {', '.join(inconnus)}.")
    return texte_motif


def _ecart(membre: dict[str, Any], conclusion: str) -> str | None:
    """Pourquoi ce membre de la sélection n'est pas délibéré, ou None s'il peut l'être."""
    if not cle_numero(membre.get("numero_ordre")):
        return "Sans n° d'ordre"
    if membre.get("sortie"):
        return "Sorti du Tableau"
    deliberation = membre.get("deliberation")
    automatique = deliberation["verdict_automatique"] if deliberation else membre.get("conclusion")
    if deliberation and deliberation.get("conclusion") == conclusion:
        return "Déjà délibéré dans ce sens"
    if automatique == conclusion:
        return f"Le calcul conclut déjà « {verdict_engine.libelle_conclusion(conclusion) or conclusion} »"
    return None


async def _enregistrer(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    *,
    exercice: str,
    cle: str,
    nom: str,
    categorie: str | None,
    conclusion: str,
    conclusion_automatique: str | None,
    criteres: list[str],
    motif: str,
    reference_seance: str | None,
    observation: str | None,
    lot: int | None = None,
) -> TableauDeliberation:
    """Remplace la délibération en vigueur du membre, sans valider la transaction."""
    precedente = await _en_vigueur(db, organisation_id, exercice, cle)
    maintenant = datetime.now(timezone.utc)
    if precedente is not None:
        precedente.revoquee_le = maintenant
        precedente.revoquee_par = user.id
        precedente.motif_revocation = "Remplacée par une nouvelle délibération"
        # L'index unique ne vaut que pour les délibérations en vigueur : la révocation doit partir avant.
        await db.flush()

    deliberation = TableauDeliberation(
        organisation_id=organisation_id,
        exercice=exercice,
        numero_ordre=cle,
        nom=_texte(nom, 300) or cle,
        personne="PM" if est_morale(categorie) else "PP",
        conclusion=conclusion,
        conclusion_automatique=conclusion_automatique,
        criteres=[c for c in CRITERES if c in criteres],
        motif=motif,
        reference_seance=_texte(reference_seance, 200),
        observation=(observation or "").strip()[:2000] or None,
        created_by=user.id,
        created_at=maintenant,
    )
    db.add(deliberation)
    await db.flush()
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.deliberation.create",
        target_type="membre",
        target_id=cle,
        metadata_json={
            "exercice": exercice,
            "conclusion": conclusion,
            "conclusion_automatique": conclusion_automatique,
            "criteres": deliberation.criteres,
            "motif": motif,
            "remplace": precedente.id if precedente else None,
            "lot": lot,
        },
    )
    return deliberation


async def deliberer(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    tenant_uuid: str,
    *,
    exercice: str,
    numero_ordre: str,
    nom: str,
    categorie: str | None,
    conclusion: str,
    conclusion_automatique: str | None,
    criteres: list[str],
    motif: str,
    reference_seance: str | None = None,
    observation: str | None = None,
    piece: UploadFile | None = None,
) -> TableauDeliberation:
    """Enregistre la délibération du membre ; celle qui était en vigueur est révoquée."""
    cle = cle_numero(numero_ordre)
    if not cle:
        raise _refus("Un membre sans n° d'ordre ne peut pas être délibéré : corrigez d'abord son numéro.")
    texte_motif = _valider(conclusion, motif, criteres)
    if conclusion_automatique and conclusion == conclusion_automatique:
        libelle = verdict_engine.libelle_conclusion(conclusion) or conclusion
        raise _refus(f"Le calcul conclut déjà « {libelle} » : il n'y a rien à délibérer.")

    deliberation = await _enregistrer(
        db, user, organisation_id,
        exercice=exercice, cle=cle, nom=nom, categorie=categorie, conclusion=conclusion,
        conclusion_automatique=conclusion_automatique, criteres=criteres, motif=texte_motif,
        reference_seance=reference_seance, observation=observation,
    )
    if piece is not None and piece.filename:
        deliberation.piece_path, deliberation.piece_nom = await _enregistrer_piece(
            piece, tenant_uuid, cle, racine="tableau-deliberations",
        )
    await _invalider(db, organisation_id, exercice)
    await db.commit()
    await db.refresh(deliberation)
    return deliberation


#: Garde-fou d'un lot : au-delà, la sélection est sans doute une erreur de filtre.
LOT_MAX = 1000


async def deliberer_lot(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    *,
    exercice: str | None,
    numeros: list[str] | None,
    filtres: dict[str, Any] | None,
    conclusion: str,
    criteres: list[str],
    motif: str,
    reference_seance: str | None = None,
    observation: str | None = None,
) -> dict[str, Any]:
    """Délibère toute une sélection d'un coup : même décision, même motif, même séance.

    Chaque membre reçoit sa propre délibération, révocable seule. Ceux qui ne
    peuvent pas l'être (sortis, sans numéro, déjà dans ce sens) sont écartés et
    nommés. Tout le lot est enregistré, ou rien.
    """
    # Import différé : les relevés importent le service, qui importe ce module.
    from .releves import membres_selection

    texte_motif = _valider(conclusion, motif, criteres)
    membres, exercice = await membres_selection(db, organisation_id, exercice=exercice, numeros=numeros, filtres=filtres)
    if len(membres) > LOT_MAX:
        raise _refus(f"La sélection compte {len(membres)} membres : {LOT_MAX} au plus par délibération groupée.")
    lot = int(datetime.now(timezone.utc).timestamp() * 1000)
    deliberes: list[dict[str, Any]] = []
    ecartes: list[dict[str, Any]] = []
    for membre in membres:
        nom = " ".join(x for x in (membre.get("nom"), membre.get("prenom")) if x)
        raison = _ecart(membre, conclusion)
        if raison:
            ecartes.append({"numero_ordre": membre.get("numero_ordre"), "nom": nom, "raison": raison})
            continue
        deliberation = membre.get("deliberation")
        automatique = deliberation["verdict_automatique"] if deliberation else membre.get("conclusion")
        await _enregistrer(
            db, user, organisation_id,
            exercice=exercice, cle=cle_numero(membre["numero_ordre"]), nom=nom, categorie=membre.get("categorie"),
            conclusion=conclusion, conclusion_automatique=automatique, criteres=criteres, motif=texte_motif,
            reference_seance=reference_seance, observation=observation, lot=lot,
        )
        deliberes.append({"numero_ordre": membre.get("numero_ordre"), "nom": nom})
    if deliberes:
        await _invalider(db, organisation_id, exercice)
    await db.commit()
    return {"exercice": exercice, "deliberes": deliberes, "ecartes": ecartes}


async def revoquer(db: AsyncSession, user: User, organisation_id: int, deliberation_id: int, motif: str) -> None:
    """Retire la délibération : le calcul automatique reprend la main."""
    texte_motif = _texte(motif, 2000)
    if not texte_motif:
        raise _refus("Le motif de la révocation est obligatoire.")
    deliberation = (await db.execute(
        select(TableauDeliberation).where(
            TableauDeliberation.id == deliberation_id,
            TableauDeliberation.organisation_id == organisation_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if deliberation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Délibération introuvable.")
    if deliberation.revoquee_le is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette délibération est déjà révoquée.")
    deliberation.revoquee_le = datetime.now(timezone.utc)
    deliberation.revoquee_par = user.id
    deliberation.motif_revocation = texte_motif
    await db.flush()
    await _invalider(db, organisation_id, deliberation.exercice)
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.deliberation.revoke",
        target_type="membre",
        target_id=deliberation.numero_ordre,
        metadata_json={"exercice": deliberation.exercice, "conclusion": deliberation.conclusion, "motif": texte_motif},
    )
    await db.commit()


async def historique(db: AsyncSession, organisation_id: int, exercice: str, numero_ordre: str) -> list[dict[str, Any]]:
    """Toutes les délibérations du membre pour l'exercice, la plus récente d'abord."""
    cle = cle_numero(numero_ordre)
    if not cle:
        return []
    rows = (await db.execute(
        select(TableauDeliberation).where(
            TableauDeliberation.organisation_id == organisation_id,
            TableauDeliberation.exercice == exercice,
            TableauDeliberation.numero_ordre == cle,
        ).order_by(TableauDeliberation.created_at.desc(), TableauDeliberation.id.desc())
    )).scalars().all()
    return [
        {
            **(deliberation_payload(d) or {}),
            "revoquee_le": d.revoquee_le,
            "motif_revocation": d.motif_revocation,
        }
        for d in rows
    ]
