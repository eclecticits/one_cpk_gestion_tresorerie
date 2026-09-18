"""Résolution des tarifs d'encaissement vers l'exercice budgétaire courant.

Un tarif désigne son poste par un code (« II.1.1.2 »), pas par un identifiant :
un poste appartient à un exercice, et son identifiant change d'une année à
l'autre. Le code se résout ici, au moment de s'en servir — l'ouverture d'un
exercice ne demande donc pas de repointer les tarifs.

Un code qui ne désigne aucun poste de recette actif de l'exercice courant ne
vaut pas imputation : la résolution rend `None`, et l'appelant le dit plutôt
que d'imputer au hasard.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement_tarif import EncaissementTarif, normaliser_libelle
from app.models.print_settings import PrintSettings


async def exercice_courant(db: AsyncSession, organisation_id: int) -> BudgetExercice | None:
    """L'exercice sur lequel travaille l'organisation.

    Même règle que l'écran Budget (`endpoints/budget.py`) : l'exercice des
    réglages s'il existe, sinon le plus récent non clôturé, sinon le plus
    récent. Deux règles divergentes feraient qu'un tarif viserait un exercice
    et l'encaissement un autre.
    """
    settings = (
        await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1))
    ).scalar_one_or_none()
    if settings and settings.fiscal_year:
        exercice = (
            await db.execute(
                select(BudgetExercice).where(
                    BudgetExercice.organisation_id == organisation_id,
                    BudgetExercice.annee == settings.fiscal_year,
                )
            )
        ).scalar_one_or_none()
        if exercice:
            return exercice

    actif = (
        await db.execute(
            select(BudgetExercice)
            .where(
                BudgetExercice.organisation_id == organisation_id,
                BudgetExercice.statut != StatutBudget.CLOTURE,
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if actif:
        return actif

    return (
        await db.execute(
            select(BudgetExercice)
            .where(BudgetExercice.organisation_id == organisation_id)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def postes_par_code(
    db: AsyncSession, organisation_id: int, codes: list[str]
) -> dict[str, BudgetPoste]:
    """Postes de RECETTE actifs de l'exercice courant, par code normalisé.

    Un encaissement alimente une recette : un tarif qui pointerait une dépense
    n'est pas résolu, et l'écran le signale comme un code introuvable.
    """
    cherches = {code.strip().upper() for code in codes if (code or "").strip()}
    if not cherches:
        return {}
    exercice = await exercice_courant(db, organisation_id)
    if exercice is None:
        return {}
    postes = (
        await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.organisation_id == organisation_id,
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.active.is_(True),
                func.upper(BudgetPoste.type) == "RECETTE",
                func.upper(BudgetPoste.code).in_(cherches),
            )
        )
    ).scalars().all()
    return {(poste.code or "").strip().upper(): poste for poste in postes}


async def tarifs_resolus(
    db: AsyncSession,
    organisation_id: int,
    *,
    actifs_seulement: bool = False,
    a_la_date: date | None = None,
    inclure_closes: bool = False,
) -> list[tuple[EncaissementTarif, BudgetPoste | None]]:
    """Les tarifs de l'organisation, chacun avec le poste où il tombe aujourd'hui.

    Un tarif est une SUITE DE VERSIONS : ce qu'on lit dépend donc du moment.
    Sans précision, on rend le catalogue en cours (les versions ouvertes), qui
    est ce que l'écran des réglages doit montrer. Avec `a_la_date`, on rend ce
    qui faisait foi ce jour-là — c'est cette forme que la saisie emploie, pour
    qu'un reçu antidaté ne prenne pas un prix voté depuis. `inclure_closes`
    rend toute l'histoire, pour la relire.
    """
    requete = select(EncaissementTarif).where(EncaissementTarif.organisation_id == organisation_id)
    if actifs_seulement:
        requete = requete.where(EncaissementTarif.is_active.is_(True))
    if a_la_date is not None:
        requete = requete.where(
            EncaissementTarif.effet_du <= a_la_date,
            or_(EncaissementTarif.effet_au.is_(None), EncaissementTarif.effet_au > a_la_date),
        )
    elif not inclure_closes:
        requete = requete.where(EncaissementTarif.effet_au.is_(None))
    tarifs = list(
        (
            await db.execute(requete.order_by(EncaissementTarif.position, EncaissementTarif.id))
        ).scalars().all()
    )
    postes = await postes_par_code(
        db, organisation_id, [t.budget_poste_code for t in tarifs if t.budget_poste_code]
    )
    return [
        (tarif, postes.get((tarif.budget_poste_code or "").strip().upper()) if tarif.budget_poste_code else None)
        for tarif in tarifs
    ]


async def succession(
    db: AsyncSession, organisation_id: int, libelle_normalise: str
) -> EncaissementTarif | None:
    """La version en cours qui a succédé à un libellé qu'on ne trouve plus.

    Le libellé est la CLÉ d'application d'un tarif. Le renommer libérerait donc
    l'ancien nom : le caissier qui le retape — il est encore dans ses habitudes
    et dans la pré-liste — ne serait plus verrouillé du tout, et rien ne le
    signalerait. On remonte la chaîne des versions pour pouvoir le dire.

    Rend `None` quand le tarif a simplement été retiré : là, l'administrateur a
    voulu que ce libellé redevienne libre, et le dire autrement serait le
    contredire. `None` également quand la version qui a pris le relais porte le
    MÊME nom : ce n'est pas un renommage mais un changement de prix, et le nom
    n'a jamais cessé d'être le bon — s'il ne s'applique pas à la date demandée,
    c'est que le tarif n'existait pas encore ce jour-là.
    """
    close = (
        await db.execute(
            select(EncaissementTarif)
            .where(
                EncaissementTarif.organisation_id == organisation_id,
                EncaissementTarif.libelle_normalise == libelle_normalise,
                EncaissementTarif.effet_au.is_not(None),
            )
            .order_by(EncaissementTarif.effet_au.desc(), EncaissementTarif.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Une chaîne de renommages successifs mène au nom d'aujourd'hui. La borne
    # évite qu'un cycle — que rien n'interdit en base — ne tourne sans fin.
    vue: set[int] = set()
    courante = close
    for _ in range(20):
        if courante is None or courante.id in vue:
            return None
        vue.add(courante.id)
        suivante = (
            await db.execute(
                select(EncaissementTarif).where(
                    EncaissementTarif.organisation_id == organisation_id,
                    EncaissementTarif.remplace_id == courante.id,
                )
            )
        ).scalars().first()
        if suivante is None:
            return None
        if suivante.effet_au is None:
            return suivante if suivante.libelle_normalise != libelle_normalise else None
        courante = suivante
    return None


async def appliquer_tarifs(
    db: AsyncSession,
    organisation_id: int,
    articles: list[dict[str, Any]],
    *,
    peut_forcer: bool,
    date_encaissement: date | None = None,
) -> list[dict[str, Any]]:
    """Impose aux articles ce que leur tarif définit, et rend les écarts.

    Le verrou vit ici et non dans l'écran : une saisie qui contournerait le
    formulaire contournerait aussi le tarif, et deux encaissements du même
    libellé se remettraient à différer.

    Ce qui est défini s'impose, champ par champ — un tarif peut ne fixer que le
    prix, ne fixer que le poste, ou les deux. Ce qui n'est pas défini reste tel
    que la caisse l'a saisi.

    C'est la version en vigueur À LA DATE DE L'ENCAISSEMENT qui s'applique, non
    celle d'aujourd'hui : un reçu antidaté doit porter le prix qui était réglé
    ce jour-là, sinon un changement de tarif réécrirait le passé au moment
    même où l'on tente de le rattraper.

    Chaque ligne garde le tarif sous lequel elle est passée (`tarif_id`) et dit
    si son prix s'en est écarté (`tarif_force`) : le libellé et le montant
    restent la photo qui fait foi, ce lien dit sous quelle définition réglée
    elle a été émise.

    Forcer est possible, mais se sait : sans le droit d'y toucher, un écart au
    prix tarifé est refusé ; avec ce droit, il est appliqué et rendu à
    l'appelant, qui le consigne. Sans cette porte, un tarif mal réglé bloquerait
    une recette réelle jusqu'à ce qu'un administrateur le corrige.
    """
    if not articles:
        return []

    jour = date_encaissement or date.today()
    resolus = await tarifs_resolus(db, organisation_id, actifs_seulement=True, a_la_date=jour)
    par_libelle = {tarif.libelle_normalise: (tarif, poste) for tarif, poste in resolus}

    ecarts: list[dict[str, Any]] = []
    for article in articles:
        cle = normaliser_libelle(article.get("libelle"))
        trouve = par_libelle.get(cle)
        if trouve is None:
            # Aucun tarif ne porte ce nom ce jour-là. Reste à savoir si le nom
            # est libre, ou s'il a été renommé — auquel cas le laisser passer
            # rouvrirait en silence le verrou qu'on croit avoir posé.
            if cle:
                remplacant = await succession(db, organisation_id, cle)
                if remplacant is not None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"« {article.get('libelle')} » est devenu "
                            f"« {remplacant.libelle} » : reprenez ce libellé, "
                            f"les encaissements déjà passés ne changent pas."
                        ),
                    )
            continue
        tarif, poste = trouve
        avant = len(ecarts)

        if tarif.montant is not None:
            tarife = Decimal(str(tarif.montant))
            saisi = Decimal(str(article.get("prix_unitaire") or 0))
            if saisi != tarife:
                if not peut_forcer:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"« {tarif.libelle} » est tarifé à {tarife} {tarif.devise} : "
                            f"montant {saisi} refusé. Corrigez le tarif dans les réglages, ou "
                            f"faites forcer le montant par un administrateur."
                        ),
                    )
                ecarts.append(
                    {
                        "libelle": tarif.libelle,
                        "tarif_id": tarif.id,
                        "champ": "prix_unitaire",
                        "tarif": str(tarife),
                        "saisi": str(saisi),
                    }
                )
            else:
                # Le prix est ferme, donc le total de la ligne l'est aussi : sans
                # ce contrôle, un prix tarifé accompagné d'un total réduit
                # laisserait passer une remise que personne n'a décidée.
                quantite = Decimal(str(article.get("quantite") or 1))
                attendu = (tarife * quantite).quantize(Decimal("0.01"))
                montant_ligne = Decimal(str(article.get("montant") or 0))
                if montant_ligne != attendu:
                    if not peut_forcer:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"« {tarif.libelle} » : {quantite} × {tarife} vaut {attendu}, "
                                f"total {montant_ligne} refusé."
                            ),
                        )
                    ecarts.append(
                        {
                            "libelle": tarif.libelle,
                            "tarif_id": tarif.id,
                            "champ": "montant",
                            "tarif": str(attendu),
                            "saisi": str(montant_ligne),
                        }
                    )

        if poste is not None:
            actuel = article.get("budget_poste_id")
            if actuel is None:
                article["budget_poste_id"] = poste.id
            elif int(actuel) != poste.id:
                if not peut_forcer:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"« {tarif.libelle} » s'impute sur {poste.code} : "
                            f"un autre poste ne peut être choisi ici."
                        ),
                    )
                ecarts.append(
                    {
                        "libelle": tarif.libelle,
                        "tarif_id": tarif.id,
                        "champ": "budget_poste_id",
                        "tarif": poste.code,
                        "saisi": str(actuel),
                    }
                )

        # La ligne porte désormais sa provenance : sous quelle version réglée
        # elle est passée, et si elle s'en est écartée.
        article["tarif_id"] = tarif.id
        article["tarif_force"] = len(ecarts) > avant

    return ecarts
