"""Import du Lot 1 du journal reel 2026 (CPK) — mode historique.

Cree, en chaine complete par enveloppe (poste x mois) :
  Requisition (PAYEE) -> LigneRequisition -> historique de statut
  -> OrdreDecaissement (PAYE) -> SortieFonds (VALIDE)
et les Encaissements (dont les retours en caisse, codes I.7.x, ligne a ligne).

Les soldes ne sont PAS forces au chiffre du journal : ils sont recalcules par la
formule de l'application = ouverture + (encaissements - sorties) sur les seules
operations importees. Ils se completeront donc au Lot 2 (CN, transferts).

Lecture seule par defaut (--dry-run : tout est ecrit puis ROLLBACK). --execute
pour valider (COMMIT). --rollback pour tout supprimer.

Usage (dans le conteneur) :
  docker compose -p onec_smart cp backend/app/scripts/import_lot1_reel.py backend:/app/app/scripts/import_lot1_reel.py
  docker compose -p onec_smart cp backend/app/scripts/lot1_data.json      backend:/app/app/scripts/lot1_data.json
  docker compose -p onec_smart exec backend python -m app.scripts.import_lot1_reel --dry-run
  docker compose -p onec_smart exec backend python -m app.scripts.import_lot1_reel --execute --limit 3   # petit essai
  docker compose -p onec_smart exec backend python -m app.scripts.import_lot1_reel --execute
  docker compose -p onec_smart exec backend python -m app.scripts.import_lot1_reel --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.models.organisation import Organisation
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.caisse_centrale import CaisseCentrale
from app.models.ouverture_caisse import OuvertureCaisse
from app.models.client import Client  # noqa: F401 - registers clients table for Encaissement FK
from app.models.projet_activite import ProjetActivite  # noqa: F401 - registers FK table
from app.models.user import User  # noqa: F401 - registers users table for Encaissement FK
from app.models.expert_comptable import ExpertComptable
from app.models.requisition import Requisition
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition_status_history import RequisitionStatusHistory
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.sortie_fonds import SortieFonds
from app.models.encaissement import Encaissement

IMPORT_SOURCE = "IMPORT_JOURNAL_2026"
DEFAULT_DATA = os.path.join(os.path.dirname(__file__), "lot1_data.json")


def D(x) -> Decimal:
    return Decimal(str(round(float(x or 0), 2)))


def dt(dstr: str | None) -> datetime:
    if dstr:
        try:
            y, m, d = (int(p) for p in dstr.split("-"))
            return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def norm_name(s: str | None) -> str:
    s = re.sub(r"^(EC|SEC|MR|MME|MLLE|M)\.?\s+", "", (s or "").strip(), flags=re.I)
    return re.sub(r"\s+", " ", s).strip().upper()


# --------------------------------------------------------------------------- #
async def load_refs(session, org_id: int, annee: int) -> dict:
    ex = (
        await session.execute(
            select(BudgetExercice).where(BudgetExercice.organisation_id == org_id, BudgetExercice.annee == annee)
        )
    ).scalar_one()
    postes = (
        await session.execute(
            select(BudgetPoste).where(
                BudgetPoste.organisation_id == org_id,
                BudgetPoste.exercice_id == ex.id,
                BudgetPoste.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().all()

    def nc(c):
        return re.sub(r"\.+", ".", (c or "").strip().upper().replace(" ", "")).rstrip(".")

    poste_by_code = {nc(p.code): p for p in postes}

    comptes = (await session.execute(select(CompteBancaire).where(CompteBancaire.organisation_id == org_id))).scalars().all()
    banques = {b.id: b.nom for b in (await session.execute(select(Banque).where(Banque.organisation_id == org_id))).scalars().all()}
    compte_by_bank = {}
    for cpt in comptes:
        nom = (banques.get(cpt.banque_id) or cpt.intitule or "").upper()
        if "EQUITY" in nom:
            compte_by_bank["Equity"] = cpt
        elif "TMB" in nom:
            compte_by_bank["TMB"] = cpt

    services = (await session.execute(select(Service).where(Service.organisation_id == org_id))).scalars().all()
    svc_by_code = {s.code.upper(): s for s in services}
    default_service = svc_by_code.get("BR") or svc_by_code.get("ADM") or (services[0] if services else None)
    # service par poste via service_rubriques (premier actif)
    sr = (await session.execute(select(ServiceRubrique))).scalars().all()
    svc_by_poste = {}
    svc_ids = {s.id for s in services}
    for link in sr:
        if link.service_id in svc_ids and link.budget_poste_id not in svc_by_poste:
            svc_by_poste[link.budget_poste_id] = link.service_id
    svc_by_id = {s.id: s for s in services}

    experts = (await session.execute(select(ExpertComptable.id, ExpertComptable.nom_denomination))).all()
    expert_by_name = {}
    for eid, nom in experts:
        key = norm_name(nom)
        if key and key not in expert_by_name:
            expert_by_name[key] = eid

    caisse = (await session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id))).scalar_one_or_none()
    return dict(exercice=ex, poste_by_code=poste_by_code, compte_by_bank=compte_by_bank,
                default_service=default_service, svc_by_poste=svc_by_poste, svc_by_id=svc_by_id,
                expert_by_name=expert_by_name, caisse=caisse)


async def do_rollback(session, org_id: int) -> dict:
    counts = {}
    # ordres puis sorties puis encaissements, puis requisitions (cascade lignes/statut/ordres)
    for label, stmt in [
        ("ordres_decaissement", delete(OrdreDecaissement).where(OrdreDecaissement.organisation_id == org_id, OrdreDecaissement.numero_ordre.like("OD-IMP26-%"))),
        ("sorties_fonds", delete(SortieFonds).where(SortieFonds.organisation_id == org_id, SortieFonds.reference_numero.like("SF-IMP26-%"))),
        ("encaissements", delete(Encaissement).where(Encaissement.organisation_id == org_id, Encaissement.numero_recu.like("EN-IMP26-%"))),
        ("requisitions", delete(Requisition).where(Requisition.organisation_id == org_id, Requisition.import_source == IMPORT_SOURCE)),
        ("ouvertures_caisse", delete(OuvertureCaisse).where(OuvertureCaisse.organisation_id == org_id, OuvertureCaisse.reference_numero.like("OUV-IMP26-%"))),
    ]:
        res = await session.execute(stmt)
        counts[label] = res.rowcount or 0
    return counts


async def run(args) -> None:
    data = json.load(open(args.data, encoding="utf-8"))
    opening = data["opening"]
    encs = data["encaissements"]
    sors = data["sorties"]

    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True  # bypass hooks tenant : on fixe org_id nous-memes
        org = (await session.execute(select(Organisation).where(func.lower(Organisation.slug) == "cpk"))).scalar_one()
        org_id = org.id

        if args.rollback:
            counts = await do_rollback(session, org_id)
            # remettre les soldes touches a l'ouverture
            for bank, cpt in (await load_refs(session, org_id, args.annee))["compte_by_bank"].items():
                cpt.solde_initial = D(opening["banks"].get(bank, 0)); cpt.solde_actuel = D(opening["banks"].get(bank, 0))
            caisse = (await session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id))).scalar_one_or_none()
            if caisse:
                caisse.solde_usd = D(opening["caisse_usd"])
            await session.commit()
            print("ROLLBACK effectue :", counts)
            return

        refs = await load_refs(session, org_id, args.annee)
        existing = await session.scalar(
            select(func.count()).select_from(Requisition).where(
                Requisition.organisation_id == org_id, Requisition.import_source == IMPORT_SOURCE)
        )
        if existing and args.execute and not args.force:
            raise SystemExit(f"Refus: {existing} requisitions IMPORT_JOURNAL_2026 existent deja. --rollback d'abord, ou --force.")

        warnings = []
        missing_poste = set()
        # accumulateurs de solde (formule app)
        caisse_in = Decimal("0"); caisse_out = Decimal("0")
        bank_in = defaultdict(lambda: Decimal("0")); bank_out = defaultdict(lambda: Decimal("0"))
        poste_paye = defaultdict(lambda: Decimal("0")); poste_engage = defaultdict(lambda: Decimal("0"))
        n = defaultdict(int)

        # ---- Ouverture (mode historique) ----
        caisse = refs["caisse"]
        if caisse is None:
            caisse = CaisseCentrale(organisation_id=org_id, solde_usd=D(0), solde_cdf=D(0)); session.add(caisse)
        session.add(OuvertureCaisse(
            organisation_id=org_id, reference_numero="OUV-IMP26-001",
            date_ouverture=dt("2026-01-01"), solde_ouverture_usd=D(opening["caisse_usd"]),
            solde_attendu_usd=D(opening["caisse_usd"]), statut="OUVERTE",
            observation="Report 2025 — import historique du journal 2026",
        ))
        for bank, cpt in refs["compte_by_bank"].items():
            cpt.solde_initial = D(opening["banks"].get(bank, 0))

        # ---- Enveloppes (poste x mois) — insertion en NIVEAUX pour respecter
        # ---- l'ordre des cles etrangeres (pas de relation ORM entre ces tables) :
        # ---- requisitions -> lignes/historique -> sorties -> ordres.
        env = defaultdict(list)
        for s in sors:
            env[(s["journal"], s["code"], s["mois"])].append(s)
        env_keys = sorted(env.keys())
        if args.limit:
            env_keys = env_keys[: args.limit]

        # Niveau 1 : requisitions
        req_of, meta_of = {}, {}
        seq_req = 0
        for key in env_keys:
            journal, code, mois = key
            poste = refs["poste_by_code"].get(code)
            if poste is None:
                missing_poste.add(code); continue
            lines = sorted(env[key], key=lambda x: x["date"] or mois)
            total = sum((D(x["montant"]) for x in lines), Decimal("0"))
            canal = lines[0]["canal"]; banque = lines[0]["banque"]
            svc_id = refs["svc_by_poste"].get(poste.id) or (refs["default_service"].id if refs["default_service"] else None)
            d0 = dt(lines[0]["date"]); dN = dt(lines[-1]["date"])
            seq_req += 1
            req = Requisition(
                id=uuid.uuid4(), organisation_id=org_id,
                numero_requisition=f"REQ-IMP26-{seq_req:04d}",
                reference_numero=f"ENV-{journal[:3]}-{code}-{mois}"[:50],
                objet=f"Depenses {poste.libelle} — {mois}"[:2000],
                mode_paiement="cash" if canal == "CAISSE" else "virement",
                type_requisition="classique", status="EN_ATTENTE",
                montant_total=total, date_requisition=d0, devise="USD",
                service_id=svc_id, decaissement_progressif=len(lines) > 1,
                validee_le=d0, approuvee_le=d0, payee_le=dN,
                import_source=IMPORT_SOURCE, examen_status="EXAMINE",
                historical_snapshot_status="not_finalized",
            )
            session.add(req); n["requisitions"] += 1
            req_of[key] = req
            meta_of[key] = (poste, svc_id, canal, banque, lines, total, d0, dN)
            poste_engage[poste.id] += total
        await session.flush()

        # Niveau 2 : lignes de requisition + historique de statut
        for key, req in req_of.items():
            poste, svc_id, canal, banque, lines, total, d0, dN = meta_of[key]
            mois = key[2]
            session.add(LigneRequisition(
                id=uuid.uuid4(), organisation_id=org_id, requisition_id=req.id,
                budget_poste_id=poste.id, rubrique=(poste.libelle[:200] or key[1]),
                description=f"{poste.libelle} — {mois}"[:2000], quantite=1,
                montant_unitaire=total, montant_total=total, devise="USD",
                budget_poste_code_snapshot=poste.code, budget_poste_libelle_snapshot=poste.libelle[:255],
            ))
            n["lignes_requisition"] += 1
            for old, new, when in [(None, "EN_ATTENTE", d0), ("EN_ATTENTE", "APPROUVEE", d0),
                                   ("APPROUVEE", "EN_DECAISSEMENT", d0), ("EN_DECAISSEMENT", "PAYEE", dN)]:
                session.add(RequisitionStatusHistory(organisation_id=org_id, requisition_id=req.id,
                                                     old_status=old, new_status=new, changed_at=when,
                                                     comment="Reprise historique (import journal 2026)"))
        await session.flush()

        for req in req_of.values():
            req.status = "PAYEE"
            req.historical_snapshot_status = "complete"

        # Niveau 3 : sorties de fonds
        sortie_of = {}
        seq_sf = 0
        for key, req in req_of.items():
            poste, svc_id, canal, banque, lines, total, d0, dN = meta_of[key]
            sortie_of[key] = []
            for x in lines:
                benef = ((x.get("beneficiaire") or "").strip() or "Beneficiaire non precise")[:200]
                dpay = dt(x["date"])
                compte = refs["compte_by_bank"].get(banque) if canal == "BANQUE" else None
                if canal == "BANQUE" and compte is None:
                    warnings.append(f"compte bancaire introuvable pour {banque} (sortie {x.get('ref')})"); continue
                seq_sf += 1
                sortie = SortieFonds(
                    id=uuid.uuid4(), organisation_id=org_id, type_sortie="requisition",
                    requisition_id=req.id, budget_poste_id=poste.id, budget_poste_code=poste.code,
                    budget_poste_libelle=poste.libelle[:255], rubrique_code=poste.code, service_id=svc_id,
                    montant_paye=D(x["montant"]), date_paiement=dpay,
                    mode_paiement="cash" if canal == "CAISSE" else "virement",
                    devise="USD", canal=canal, compte_bancaire_id=(compte.id if compte else None),
                    reference_numero=f"SF-IMP26-{seq_sf:05d}", reference=(x.get("ref") or None),
                    statut="VALIDE", motif=x["libelle"][:2000], beneficiaire=benef,
                    piece_justificative=(x.get("ref") or None),
                )
                session.add(sortie); n["sorties_fonds"] += 1
                sortie_of[key].append((sortie, x, benef, dpay))
                poste_paye[poste.id] += D(x["montant"])
                if canal == "CAISSE":
                    caisse_out += D(x["montant"])
                else:
                    bank_out[banque] += D(x["montant"])
        await session.flush()

        # Niveau 4 : ordres de decaissement (references requisition + sortie)
        seq_od = 0
        for key, req in req_of.items():
            poste, svc_id, canal, banque, lines, total, d0, dN = meta_of[key]
            for (sortie, x, benef, dpay) in sortie_of[key]:
                seq_od += 1
                session.add(OrdreDecaissement(
                    id=uuid.uuid4(), organisation_id=org_id, requisition_id=req.id,
                    numero_ordre=f"OD-IMP26-{seq_od:05d}", beneficiaire=benef,
                    montant=D(x["montant"]), devise="USD", motif=x["libelle"][:2000],
                    service_id=svc_id, statut="PAYE", autorise_le=d0, paye_le=dpay,
                    sortie_fonds_id=sortie.id,
                ))
                n["ordres_decaissement"] += 1
        await session.flush()

        # ---- Encaissements (dont retours en caisse, ligne a ligne) ----
        seq_en = 0
        for e in encs:
            poste = refs["poste_by_code"].get(e["code"])
            if poste is None:
                missing_poste.add(e["code"]); continue
            seq_en += 1
            canal = e["canal"]; banque = e["banque"]
            compte = refs["compte_by_bank"].get(banque) if canal == "BANQUE" else None
            if canal == "BANQUE" and compte is None:
                warnings.append(f"compte introuvable {banque} (enc {e.get('ref')})"); continue
            payer = (e.get("payer") or "").strip()
            expert_id = None
            if e["code"].startswith("I.3") and payer:
                expert_id = refs["expert_by_name"].get(norm_name(payer))
            if expert_id:
                type_client = "expert_comptable"; client_nom = None; n["enc_expert_matched"] += 1
            else:
                type_client = "client_externe" if payer else "autre"
                client_nom = payer or (e["libelle"][:120] if e["libelle"] else "Divers")
            montant = D(e["montant"])
            session.add(Encaissement(
                id=uuid.uuid4(), organisation_id=org_id,
                numero_recu=f"EN-IMP26-{seq_en:05d}", reference=(e.get("ref") or None),
                type_client=type_client, expert_comptable_id=expert_id, client_nom=client_nom,
                libelle=(("RETOUR EN CAISSE — " if e.get("is_retour") else "") + e["libelle"])[:255],
                description=e["libelle"], montant=montant, montant_total=montant,
                montant_paye=montant, montant_percu=montant, devise_perception="USD",
                taux_change_applique=D(1), canal=canal, compte_bancaire_id=(compte.id if compte else None),
                budget_poste_id=poste.id, budget_poste_code=poste.code, budget_poste_libelle=poste.libelle[:255],
                service_id=refs["svc_by_poste"].get(poste.id) or (refs["default_service"].id if refs["default_service"] else None),
                statut_paiement="complet", mode_paiement="cash" if canal == "CAISSE" else "virement",
                statut_operation="ACTIVE", date_encaissement=dt(e["date"]),
            ))
            n["encaissements"] += 1
            if e.get("is_retour"):
                n["dont_retours"] += 1
            if canal == "CAISSE":
                caisse_in += montant
            else:
                bank_in[banque] += montant

        # ---- Recompute des soldes = ouverture + net importe (formule app) ----
        caisse.solde_usd = D(opening["caisse_usd"]) + caisse_in - caisse_out
        for bank, cpt in refs["compte_by_bank"].items():
            cpt.solde_actuel = D(opening["banks"].get(bank, 0)) + bank_in[bank] - bank_out[bank]
        # budget : montant_paye / montant_engage recalcules sur l'import
        all_postes = {p.id: p for p in refs["poste_by_code"].values()}
        for pid, p in all_postes.items():
            if pid in poste_paye or pid in poste_engage:
                p.montant_paye = poste_paye.get(pid, Decimal("0"))
                p.montant_engage = poste_engage.get(pid, Decimal("0"))

        await session.flush()  # declenche contraintes/triggers sans committer

        # ---- Rapport ----
        print("=" * 68)
        print(f"IMPORT LOT 1 — {'EXECUTE (COMMIT)' if args.execute else 'DRY-RUN (rollback)'}"
              + (f" — LIMIT {args.limit} enveloppes" if args.limit else ""))
        print("=" * 68)
        print(f"Organisation CPK id={org_id} | exercice {args.annee} id={refs['exercice'].id}")
        for k in ["requisitions", "lignes_requisition", "ordres_decaissement", "sorties_fonds",
                  "encaissements", "dont_retours", "enc_expert_matched"]:
            print(f"  {k:22s}: {n[k]}")
        print("-" * 68)
        print("SOLDES recalcules (ouverture + net Lot1, formule application) :")
        print(f"  Caisse   : {opening['caisse_usd']:>12.2f} + {caisse_in} - {caisse_out} = {caisse.solde_usd}")
        for bank, cpt in refs["compte_by_bank"].items():
            print(f"  {bank:8s} : {opening['banks'][bank]:>12.2f} + {bank_in[bank]} - {bank_out[bank]} = {cpt.solde_actuel}")
        print("  (les soldes se completeront au Lot 2 : CN + transferts)")
        print("-" * 68)
        print(f"Budget : {len(poste_paye)} postes imputes | total montant_paye = {sum(poste_paye.values(), Decimal('0'))}")
        if missing_poste:
            print(f"  ⚠ codes sans poste en base : {sorted(missing_poste)}")
        if warnings:
            print(f"  ⚠ {len(warnings)} avertissements, ex: {warnings[:3]}")

        if args.execute:
            await session.commit()
            print("\n✅ COMMIT effectue.")
        else:
            await session.rollback()
            print("\n(dry-run) ROLLBACK — rien n'a ete ecrit. Relancer avec --execute pour valider.")


def parse_args():
    p = argparse.ArgumentParser(description="Import Lot 1 du journal reel 2026 (mode historique).")
    m = p.add_mutually_exclusive_group()
    m.add_argument("--dry-run", action="store_true", help="Ecrit tout puis rollback (defaut).")
    m.add_argument("--execute", action="store_true", help="Ecrit et COMMIT.")
    m.add_argument("--rollback", action="store_true", help="Supprime les enregistrements importes.")
    p.add_argument("--data", default=DEFAULT_DATA, help="Chemin de lot1_data.json.")
    p.add_argument("--annee", type=int, default=2026)
    p.add_argument("--limit", type=int, default=None, help="Limiter au N premieres enveloppes (essai).")
    p.add_argument("--force", action="store_true", help="Autoriser un 2e import malgre des lignes existantes.")
    args = p.parse_args()
    if not (args.execute or args.rollback):
        args.dry_run = True
    return args


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
