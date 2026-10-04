"""Notes de débit des experts-comptables et des SEC : liste et import Excel.

Une note de débit est un encaissement non payé rattaché à un expert. Cet écran
ne crée pas une seconde comptabilité des créances : il lit les encaissements
sous la même portée que la liste des encaissements (`_portee_encaissements`),
et l'import crée des notes que le règlement, les relances et la liste des
débiteurs prennent en charge tels quels.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.api.v1.endpoints.encaissements import _portee_encaissements
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.note_debit_import import NoteDebitImport
from app.models.user import User
from app.services.audit_service import log_action
from app.services.creances import est_exigible, montant_du
from app.services.notes_debit_import import analyse_en_reponse, analyser, importer
from app.services.report_cache import invalidate_report_summary_cache
from app.utils.upload_validation import read_upload_limited

router = APIRouter()

PERMISSION_IMPORT = "treso.experts_comptables.import_notes_debit"
TAILLE_MAX = 5 * 1024 * 1024
EXTENSIONS = (".xlsx", ".xlsm")


async def _lire_fichier(fichier: UploadFile) -> bytes:
    nom = (fichier.filename or "").lower()
    if not nom.endswith(EXTENSIONS):
        raise HTTPException(status_code=400, detail="Déposez un classeur Excel (.xlsx).")
    return await read_upload_limited(
        fichier, TAILLE_MAX, error_detail="Fichier trop volumineux (5 Mo au plus)."
    )


@router.post("/import/analyse", dependencies=[Depends(has_permission(PERMISSION_IMPORT))])
async def analyser_import(
    fichier: UploadFile = File(...),
    service_id: int | None = Form(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ce que l'import ferait du fichier, sans rien écrire."""
    contenu = await _lire_fichier(fichier)
    analyse = await analyser(db, tenant_id=tenant_id, user=user, contenu=contenu, service_id=service_id)
    return {"fichier": fichier.filename, **analyse_en_reponse(analyse)}


@router.post("/import", dependencies=[Depends(has_permission(PERMISSION_IMPORT))])
async def importer_notes(
    fichier: UploadFile = File(...),
    options: str = Form(default="{}"),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Crée les notes du fichier — toutes ou aucune.

    `options` (JSON) : `service_id`, `postes` (clé de colonne → id de poste),
    `importer_doublons` (créer aussi les lignes déjà émises cette année).
    """
    try:
        reglages = json.loads(options or "{}")
        postes = {str(k): int(v) for k, v in (reglages.get("postes") or {}).items() if v not in (None, "")}
        service_id = reglages.get("service_id")
        service_id = int(service_id) if service_id not in (None, "") else None
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="options invalides")
    contenu = await _lire_fichier(fichier)
    resultat = await importer(
        db,
        tenant_id=tenant_id,
        user=user,
        fichier=fichier.filename or "",
        contenu=contenu,
        service_id=service_id,
        postes=postes,
        importer_doublons=bool(reglages.get("importer_doublons")),
    )
    await invalidate_report_summary_cache(tenant_id)
    return resultat


@router.get("/imports")
async def lister_imports(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    imports = (
        await db.execute(
            select(NoteDebitImport, User)
            .outerjoin(User, User.id == NoteDebitImport.created_by)
            .where(NoteDebitImport.organisation_id == tenant_id)
            .order_by(NoteDebitImport.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(imp.id),
            "fichier": imp.fichier,
            "nb_notes": imp.nb_notes,
            "nb_lignes_ecartees": imp.nb_lignes_ecartees,
            "montant_total": str(imp.montant_total),
            "montant_arrieres": str(imp.montant_arrieres),
            "colonnes": imp.colonnes or [],
            "created_at": imp.created_at.isoformat() if imp.created_at else None,
            "auteur": (
                " ".join(p for p in (getattr(auteur, "prenom", None), getattr(auteur, "nom", None)) if p)
                or getattr(auteur, "email", None)
            )
            if auteur is not None
            else None,
        }
        for imp, auteur in imports
    ]


@router.get("")
async def lister_notes(
    q: str | None = Query(default=None, description="N° d'ordre, nom ou n° de note"),
    statut: str = Query(default="impayees", pattern="^(impayees|soldees|toutes)$"),
    type_client: str | None = Query(default=None, pattern="^(expert_comptable|sec)$"),
    import_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Les notes de débit des experts et des SEC, avec les totaux de la sélection.

    Les totaux portent sur toute la sélection filtrée, jamais sur la seule page.
    """
    portee = await _portee_encaissements(db, user, tenant_id)
    vide = {"items": [], "total": 0, "totaux": {"montant_total": "0", "montant_paye": "0", "reste_du": "0"}}
    if portee is None:
        return vide
    conditions = [
        *portee,
        Encaissement.est_proforma.is_(False),
        Encaissement.expert_comptable_id.is_not(None),
        Encaissement.type_client.in_(("expert_comptable", "sec")),
    ]
    if statut == "impayees":
        conditions.append(est_exigible())
        conditions.append(montant_du() > 0)
    elif statut == "soldees":
        conditions.append(Encaissement.statut_paiement.in_(("complet", "avance")))
    if type_client:
        conditions.append(Encaissement.type_client == type_client)
    if import_id:
        conditions.append(Encaissement.note_debit_import_id == import_id)
    if q and q.strip():
        motif = f"%{q.strip()}%"
        conditions.append(
            or_(
                ExpertComptable.numero_ordre.ilike(motif),
                ExpertComptable.nom_denomination.ilike(motif),
                Encaissement.numero_recu.ilike(motif),
                Encaissement.libelle.ilike(motif),
            )
        )

    base = select(Encaissement, ExpertComptable).join(
        ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id
    ).where(*conditions)
    agregat = (
        await db.execute(
            select(
                func.count(Encaissement.id),
                func.coalesce(func.sum(Encaissement.montant_total), 0),
                func.coalesce(func.sum(Encaissement.montant_paye), 0),
            )
            .select_from(Encaissement)
            .join(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
            .where(*conditions)
        )
    ).one()
    lignes = (
        await db.execute(
            base.order_by(Encaissement.date_encaissement.desc(), Encaissement.numero_recu.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    maintenant = datetime.now(timezone.utc)
    items = []
    for note, expert in lignes:
        reste = (note.montant_total or 0) - (note.montant_paye or 0)
        items.append(
            {
                "id": str(note.id),
                "numero_recu": note.numero_recu,
                "date_encaissement": note.date_encaissement.isoformat() if note.date_encaissement else None,
                "jours": (maintenant - note.date_encaissement).days if note.date_encaissement else 0,
                "libelle": note.libelle,
                "type_client": note.type_client,
                "expert": {
                    "id": str(expert.id),
                    "numero_ordre": expert.numero_ordre,
                    "nom": expert.nom_denomination,
                    "type_ec": expert.type_ec,
                    "statut_professionnel": expert.statut_professionnel,
                },
                "montant_total": str(note.montant_total),
                "montant_paye": str(note.montant_paye),
                "reste_du": str(max(reste, 0)),
                "statut_paiement": note.statut_paiement,
                "statut_operation": note.statut_operation,
                "relance_count": note.relance_count or 0,
                "importee": note.note_debit_import_id is not None,
            }
        )
    nb, total, paye = agregat
    return {
        "items": items,
        "total": int(nb or 0),
        "totaux": {
            "montant_total": str(total),
            "montant_paye": str(paye),
            "reste_du": str(max(total - paye, 0)),
        },
    }


# ---------------------------------------------------------------------------
# Fiche, documents imprimables, mise en demeure
# ---------------------------------------------------------------------------

#: Délai laissé par une mise en demeure, sauf choix contraire à l'émission.
DELAI_MISE_EN_DEMEURE_JOURS = 15
ACTION_MISE_EN_DEMEURE = "NOTE_DEBIT_MISE_EN_DEMEURE"

#: Ce que l'historique d'une note sait raconter, dans les mots de l'écran.
LIBELLES_HISTORIQUE = {
    ACTION_MISE_EN_DEMEURE: "Mise en demeure émise",
    "ENCAISSEMENT_RELANCE_SOLDE": "Relance envoyée par e-mail",
    "ENCAISSEMENT_TARIF_FORCE": "Montant différent du tarif réglé (retenu tel que saisi)",
    "ENCAISSEMENT_REIMPUTE": "Poste budgétaire corrigé",
    "ENCAISSEMENT_HORS_BUDGET_AFFECTE": "Affectée au budget",
    "ENCAISSEMENT_PIECE_JOINTE_AJOUTEE": "Pièce justificative ajoutée",
    "ENCAISSEMENT_CANCELLED": "Note annulée",
    "ENCAISSEMENT_SOFT_DELETED": "Note supprimée",
    "ENCAISSEMENT_RESTORED": "Note restaurée",
}
#: Types d'entrée du journal, pour que l'écran les distingue sans lire les libellés.
TYPES_HISTORIQUE = {
    ACTION_MISE_EN_DEMEURE: "mise_en_demeure",
    "ENCAISSEMENT_RELANCE_SOLDE": "relance",
    "ENCAISSEMENT_CANCELLED": "annulation",
}


def _nom_utilisateur(utilisateur: User | None) -> str | None:
    if utilisateur is None:
        return None
    nom = " ".join(p for p in (getattr(utilisateur, "prenom", None), getattr(utilisateur, "nom", None)) if p)
    return nom or getattr(utilisateur, "email", None)


async def _comptes_de_paiement(db: AsyncSession, tenant_id: int) -> list[dict[str, Any]]:
    """Les comptes bancaires où le membre peut verser : ceux qu'imprime la note."""
    from app.models.banque import Banque
    from app.models.compte_bancaire import CompteBancaire

    lignes = (
        await db.execute(
            select(CompteBancaire, Banque.nom)
            .outerjoin(Banque, Banque.id == CompteBancaire.banque_id)
            .where(
                CompteBancaire.organisation_id == tenant_id,
                CompteBancaire.is_active.is_(True),
                CompteBancaire.account_type == "BANK",
            )
            .order_by(CompteBancaire.is_principal.desc(), CompteBancaire.id)
        )
    ).all()
    return [
        {
            "banque": banque,
            "intitule": compte.intitule,
            "numero_compte": compte.numero_compte,
            "devise": compte.devise,
            "code_swift_bic": compte.code_swift_bic,
        }
        for compte, banque in lignes
    ]


async def _articles_par_note(db: AsyncSession, note_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    from app.models.budget import BudgetPoste
    from app.models.encaissement import EncaissementArticle

    if not note_ids:
        return {}
    lignes = (
        await db.execute(
            select(EncaissementArticle, BudgetPoste.code)
            .outerjoin(BudgetPoste, BudgetPoste.id == EncaissementArticle.budget_poste_id)
            .where(EncaissementArticle.encaissement_id.in_(note_ids))
            .order_by(EncaissementArticle.encaissement_id, EncaissementArticle.sort_order)
        )
    ).all()
    resultat: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for article, code in lignes:
        resultat.setdefault(article.encaissement_id, []).append(
            {
                "libelle": article.libelle,
                "quantite": str(article.quantite),
                "prix_unitaire": str(article.prix_unitaire),
                "montant": str(article.montant),
                "poste_code": code,
            }
        )
    return resultat


def _document_note(note: Encaissement, expert: ExpertComptable, articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Ce qu'une note imprime : une ligne par article, faute d'article l'en-tête."""
    reste = (note.montant_total or 0) - (note.montant_paye or 0)
    return {
        "id": str(note.id),
        "numero_recu": note.numero_recu,
        "date_encaissement": note.date_encaissement.isoformat() if note.date_encaissement else None,
        "libelle": note.libelle,
        "type_client": note.type_client,
        "statut_paiement": note.statut_paiement,
        "statut_operation": note.statut_operation,
        "montant_total": str(note.montant_total),
        "montant_paye": str(note.montant_paye),
        "reste_du": str(max(reste, 0)),
        "articles": articles
        or [
            {
                "libelle": note.libelle,
                "quantite": "1.00",
                "prix_unitaire": str(note.montant_total),
                "montant": str(note.montant_total),
                "poste_code": note.budget_poste_code,
            }
        ],
        "expert": _expert_document(expert),
    }


def _expert_document(expert: ExpertComptable) -> dict[str, Any]:
    return {
        "id": str(expert.id),
        "numero_ordre": expert.numero_ordre,
        "nom": expert.nom_denomination,
        "type_ec": expert.type_ec,
        "statut_professionnel": expert.statut_professionnel,
        "email": expert.email,
        "telephone": expert.telephone,
        "province": expert.province_attache,
    }


async def _notes_visibles(db: AsyncSession, user: User, tenant_id: int, *conditions: Any) -> list[tuple[Encaissement, ExpertComptable]]:
    portee = await _portee_encaissements(db, user, tenant_id)
    if portee is None:
        return []
    return list(
        (
            await db.execute(
                select(Encaissement, ExpertComptable)
                .join(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
                .where(
                    *portee,
                    Encaissement.est_proforma.is_(False),
                    Encaissement.type_client.in_(("expert_comptable", "sec")),
                    *conditions,
                )
                .order_by(Encaissement.date_encaissement, Encaissement.numero_recu)
            )
        ).all()
    )


@router.get("/documents")
async def documents_a_imprimer(
    ids: str | None = Query(default=None, description="Identifiants séparés par des virgules"),
    import_id: uuid.UUID | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Les notes à imprimer en lot — une sélection, ou toutes celles d'un import."""
    conditions: list[Any] = []
    if ids:
        try:
            choisis = [uuid.UUID(v) for v in ids.split(",") if v.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="ids invalides")
        if len(choisis) > 500:
            raise HTTPException(status_code=400, detail="500 notes au plus par impression")
        conditions.append(Encaissement.id.in_(choisis))
    elif import_id:
        conditions.append(Encaissement.note_debit_import_id == import_id)
    else:
        raise HTTPException(status_code=400, detail="Précisez les notes à imprimer")
    lignes = (await _notes_visibles(db, user, tenant_id, *conditions))[:500]
    articles = await _articles_par_note(db, [note.id for note, _ in lignes])
    return {
        "notes": [_document_note(note, expert, articles.get(note.id, [])) for note, expert in lignes],
        "comptes": await _comptes_de_paiement(db, tenant_id),
    }


async def _releve_membre(db: AsyncSession, user: User, tenant_id: int, expert_id: uuid.UUID) -> dict[str, Any]:
    expert = await db.get(ExpertComptable, expert_id)
    if expert is None:
        raise HTTPException(status_code=404, detail="Expert-comptable introuvable")
    lignes = await _notes_visibles(
        db, user, tenant_id, Encaissement.expert_comptable_id == expert_id, est_exigible(), montant_du() > 0
    )
    articles = await _articles_par_note(db, [note.id for note, _ in lignes])
    notes = [_document_note(note, exp, articles.get(note.id, [])) for note, exp in lignes]
    return {
        "expert": _expert_document(expert),
        "notes": notes,
        "total_du": str(sum((Decimal(n["reste_du"]) for n in notes), Decimal("0.00"))),
        "comptes": await _comptes_de_paiement(db, tenant_id),
    }


@router.get("/membres/{expert_id}/releve")
async def releve_membre(
    expert_id: uuid.UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ce que ce membre doit encore, note par note."""
    return await _releve_membre(db, user, tenant_id, expert_id)


class MiseEnDemeurePayload(BaseModel):
    delai_jours: int = Field(default=DELAI_MISE_EN_DEMEURE_JOURS, ge=1, le=90)


@router.post("/membres/{expert_id}/mise-en-demeure", dependencies=[Depends(has_permission("encaissements"))])
async def mettre_en_demeure(
    expert_id: uuid.UUID,
    payload: MiseEnDemeurePayload,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Émet la mise en demeure d'un membre : la trace sur chaque note, rend le relevé à imprimer.

    Le document part du relevé du jour — toutes les notes non soldées —, pas
    d'une note isolée : on met en demeure un débiteur, pas un reçu.
    """
    releve = await _releve_membre(db, user, tenant_id, expert_id)
    if not releve["notes"]:
        raise HTTPException(status_code=400, detail="Ce membre ne doit rien : aucune mise en demeure à émettre.")
    emise_le = datetime.now(timezone.utc)
    echeance = emise_le + timedelta(days=payload.delai_jours)
    for note in releve["notes"]:
        await log_action(
            db,
            user_id=getattr(user, "id", None),
            action=ACTION_MISE_EN_DEMEURE,
            target_table="encaissements",
            target_id=note["id"],
            new_value={
                "reste_du": note["reste_du"],
                "total_du": releve["total_du"],
                "delai_jours": payload.delai_jours,
                "echeance": echeance.date().isoformat(),
            },
        )
    await db.commit()
    return {**releve, "emise_le": emise_le.isoformat(), "echeance": echeance.date().isoformat(), "delai_jours": payload.delai_jours}


# ---------------------------------------------------------------------------
# Lot 3 : tableau de bord du recouvrement, régularité pour le Tableau
# ---------------------------------------------------------------------------


def _tranche(jours: int) -> str:
    # Mêmes bornes que la liste des débiteurs (`encaissements._tranche_anciennete`).
    if jours < 30:
        return "moins_30"
    if jours < 60:
        return "30_60"
    if jours < 90:
        return "60_90"
    return "plus_90"


def _sans_accents_minuscules(texte: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", texte or "") if not unicodedata.combining(c)).lower()


async def _notes_jusqu_a(db: AsyncSession, user: User, tenant_id: int, annee: int, *conditions: Any):
    """Les notes non annulées émises jusqu'à la fin de `annee`, sous la portée de l'utilisateur.

    Une note annulée ne réclame plus rien et n'a rien émis : le tableau de bord
    l'écarte quel que soit le droit de la voir.
    """
    fin = datetime(annee + 1, 1, 1, tzinfo=timezone.utc)
    return await _notes_visibles(
        db,
        user,
        tenant_id,
        Encaissement.statut_operation != "ANNULEE",
        Encaissement.date_encaissement < fin,
        *conditions,
    )


def _reste(note: Encaissement) -> Decimal:
    return max(Decimal(note.montant_total or 0) - Decimal(note.montant_paye or 0), Decimal("0"))


@router.get("/tableau-de-bord")
async def tableau_de_bord(
    annee: int | None = Query(default=None, ge=2000, le=2100),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Où en est le recouvrement des notes de débit d'un exercice.

    « Émis » et « encaissé » portent sur les notes de l'exercice ; « reste à
    recouvrer », l'ancienneté et les débiteurs portent sur tout ce qui est dû à
    la fin de l'exercice, arriérés compris : c'est cette dette qui ferme la porte
    du Tableau suivant (art. 12 du RI), pas celle de la seule année.
    """
    maintenant = datetime.now(timezone.utc)
    annee = annee or maintenant.year
    lignes = await _notes_jusqu_a(db, user, tenant_id, annee)
    de_l_annee = [(n, e) for n, e in lignes if n.date_encaissement and n.date_encaissement.year == annee]
    dues = [(n, e) for n, e in lignes if _reste(n) > 0]

    zero = Decimal("0.00")
    emis = sum((Decimal(n.montant_total or 0) for n, _ in de_l_annee), zero)
    encaisse = sum((Decimal(n.montant_paye or 0) for n, _ in de_l_annee), zero)
    reste_annee = sum((_reste(n) for n, _ in de_l_annee), zero)
    reste_total = sum((_reste(n) for n, _ in dues), zero)

    articles = await _articles_par_note(db, [n.id for n, _ in lignes])

    # Les pénalités dues : la part « pénalité » de chaque note impayée, au prorata
    # de ce qui en reste — un versement partiel solde chaque ligne à proportion.
    penalites = zero
    for note, _ in dues:
        total = Decimal(note.montant_total or 0)
        if total <= 0:
            continue
        part = sum(
            (Decimal(a["montant"]) for a in articles.get(note.id, []) if "penalit" in _sans_accents_minuscules(a["libelle"])),
            zero,
        )
        penalites += (part * _reste(note) / total).quantize(Decimal("0.01"))

    def regroupe(cle, sources):
        groupes: dict[Any, dict[str, Any]] = {}
        for note, expert in sources:
            k = cle(note, expert)
            g = groupes.setdefault(k, {"emis": zero, "encaisse": zero, "reste": zero, "nb": 0})
            g["emis"] += Decimal(note.montant_total or 0)
            g["encaisse"] += Decimal(note.montant_paye or 0)
            g["reste"] += _reste(note)
            g["nb"] += 1
        return groupes

    def taux(g):
        return float(g["encaisse"] / g["emis"] * 100) if g["emis"] > 0 else 0.0

    par_type = regroupe(lambda n, e: n.type_client, de_l_annee)
    par_province = regroupe(lambda n, e: e.province_attache or "Non renseignée", de_l_annee)

    libelles: dict[str, dict[str, Any]] = {}
    for note, _ in de_l_annee:
        for a in articles.get(note.id, []):
            g = libelles.setdefault(" ".join(a["libelle"].split()), {"emis": zero, "nb": 0})
            g["emis"] += Decimal(a["montant"])
            g["nb"] += 1

    anciennete = {t: {"reste": zero, "nb": 0} for t in ("moins_30", "30_60", "60_90", "plus_90")}
    debiteurs: dict[uuid.UUID, dict[str, Any]] = {}
    for note, expert in dues:
        jours = (maintenant - note.date_encaissement).days if note.date_encaissement else 0
        t = anciennete[_tranche(jours)]
        t["reste"] += _reste(note)
        t["nb"] += 1
        d = debiteurs.setdefault(
            expert.id,
            {
                "expert_id": str(expert.id),
                "numero_ordre": expert.numero_ordre,
                "nom": expert.nom_denomination,
                "type_ec": expert.type_ec,
                "reste": zero,
                "nb_notes": 0,
            },
        )
        d["reste"] += _reste(note)
        d["nb_notes"] += 1

    def txt(v: Decimal) -> str:
        return str(v.quantize(Decimal("0.01")))

    return {
        "annee": annee,
        "kpi": {
            "emis": txt(emis),
            "encaisse": txt(encaisse),
            "reste_annee": txt(reste_annee),
            "reste_total": txt(reste_total),
            "arrieres_anterieurs": txt(reste_total - reste_annee),
            "taux_recouvrement": round(float(encaisse / emis * 100), 1) if emis > 0 else 0.0,
            "nb_notes": len(de_l_annee),
            "penalites_dues": txt(penalites),
            "membres_non_en_regle": len(debiteurs),
        },
        "par_type": [
            {"type_client": k, "emis": txt(g["emis"]), "encaisse": txt(g["encaisse"]), "reste": txt(g["reste"]), "nb": g["nb"], "taux": round(taux(g), 1)}
            for k, g in sorted(par_type.items(), key=lambda kv: kv[1]["emis"], reverse=True)
        ],
        "par_libelle": [
            {"libelle": k, "emis": txt(g["emis"]), "nb": g["nb"]}
            for k, g in sorted(libelles.items(), key=lambda kv: kv[1]["emis"], reverse=True)[:8]
        ],
        "anciennete": [{"tranche": k, "reste": txt(g["reste"]), "nb": g["nb"]} for k, g in anciennete.items()],
        "par_province": [
            {"province": k, "emis": txt(g["emis"]), "encaisse": txt(g["encaisse"]), "reste": txt(g["reste"]), "nb": g["nb"], "taux": round(taux(g), 1)}
            for k, g in sorted(par_province.items(), key=lambda kv: kv[1]["reste"], reverse=True)
        ],
        "top_debiteurs": [
            {**d, "reste": txt(d["reste"])}
            for d in sorted(debiteurs.values(), key=lambda d: d["reste"], reverse=True)[:10]
        ],
    }


@router.get("/regularite")
async def regularite_membres(
    expert_ids: str = Query(..., description="Identifiants séparés par des virgules"),
    annee: int | None = Query(default=None, ge=2000, le=2100),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Chaque membre est-il en règle pour le Tableau de l'année suivante ?

    Art. 12 du RI : cotisation et pénalités soldées avant la fin de l'année pour
    être inscrit au prochain Tableau. Trois réponses, qui ne se confondent pas :
      - `non_en_regle` : il reste dû sur une note émise jusqu'à fin `annee` ;
      - `en_regle` : au moins une note de `annee`, et plus rien de dû ;
      - `sans_note` : rien d'émis pour `annee` — « en règle » serait trompeur,
        la cotisation n'a simplement pas été appelée.
    """
    try:
        ids = [uuid.UUID(v) for v in expert_ids.split(",") if v.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="expert_ids invalides")
    if not ids or len(ids) > 500:
        raise HTTPException(status_code=400, detail="De 1 à 500 membres par demande")
    annee = annee or datetime.now(timezone.utc).year
    lignes = await _notes_jusqu_a(db, user, tenant_id, annee, Encaissement.expert_comptable_id.in_(ids))
    membres: dict[str, dict[str, Any]] = {
        str(i): {"statut": "sans_note", "reste_du": "0.00", "nb_notes_dues": 0, "nb_notes_annee": 0} for i in ids
    }
    for note, expert in lignes:
        m = membres[str(expert.id)]
        if note.date_encaissement and note.date_encaissement.year == annee:
            m["nb_notes_annee"] += 1
        reste = _reste(note)
        if reste > 0:
            m["reste_du"] = str((Decimal(m["reste_du"]) + reste).quantize(Decimal("0.01")))
            m["nb_notes_dues"] += 1
    for m in membres.values():
        if m["nb_notes_dues"]:
            m["statut"] = "non_en_regle"
        elif m["nb_notes_annee"]:
            m["statut"] = "en_regle"
    return {"annee": annee, "tableau": annee + 1, "membres": membres}


@router.get("/{note_id}")
async def fiche_note(
    note_id: uuid.UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Une note de débit et tout ce qui lui est arrivé : versements, relances, mises en demeure."""
    from app.models.audit_log import AuditLog
    from app.models.payment_history import PaymentHistory

    lignes = await _notes_visibles(db, user, tenant_id, Encaissement.id == note_id)
    if not lignes:
        raise HTTPException(status_code=404, detail="Note de débit introuvable")
    note, expert = lignes[0]
    articles = (await _articles_par_note(db, [note.id])).get(note.id, [])

    paiements = (
        await db.execute(
            select(PaymentHistory, User)
            .outerjoin(User, User.id == PaymentHistory.created_by)
            .where(PaymentHistory.encaissement_id == note.id, PaymentHistory.organisation_id == tenant_id)
            .order_by(PaymentHistory.date_paiement)
        )
    ).all()
    journal = (
        await db.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(AuditLog.entity_type == "encaissements", AuditLog.entity_id == str(note.id))
            .order_by(AuditLog.created_at)
        )
    ).all()
    createur = await db.get(User, note.created_by) if note.created_by else None
    enregistrement = await db.get(NoteDebitImport, note.note_debit_import_id) if note.note_debit_import_id else None

    historique: list[dict[str, Any]] = [
        {
            "date": note.created_at.isoformat() if note.created_at else None,
            "type": "emission",
            "libelle": f"Note émise (import « {enregistrement.fichier} »)" if enregistrement else "Note émise",
            "auteur": _nom_utilisateur(createur),
        }
    ]
    for paiement, auteur in paiements:
        annule = (paiement.statut or "").upper() != "ACTIF"
        historique.append(
            {
                "date": paiement.date_paiement.isoformat() if paiement.date_paiement else None,
                "type": "paiement_annule" if annule else "paiement",
                "libelle": f"{'Versement annulé' if annule else 'Versement'} de {paiement.montant} {paiement.devise}",
                "auteur": _nom_utilisateur(auteur),
            }
        )
    for entree, auteur in journal:
        historique.append(
            {
                "date": entree.created_at.isoformat() if entree.created_at else None,
                "type": TYPES_HISTORIQUE.get(entree.action, "journal"),
                "libelle": LIBELLES_HISTORIQUE.get(entree.action, entree.action.replace("_", " ").capitalize()),
                "auteur": _nom_utilisateur(auteur),
            }
        )
    historique.sort(key=lambda e: e["date"] or "")

    return {
        **_document_note(note, expert, articles),
        "description": note.description,
        "relance_count": note.relance_count or 0,
        "derniere_relance_le": note.derniere_relance_le.isoformat() if note.derniere_relance_le else None,
        "nb_paiements": sum(1 for p, _ in paiements if (p.statut or "").upper() == "ACTIF"),
        "nb_mises_en_demeure": sum(1 for e, _ in journal if e.action == ACTION_MISE_EN_DEMEURE),
        "import": (
            {"id": str(enregistrement.id), "fichier": enregistrement.fichier}
            if enregistrement is not None
            else None
        ),
        "historique": historique,
        "comptes": await _comptes_de_paiement(db, tenant_id),
    }
