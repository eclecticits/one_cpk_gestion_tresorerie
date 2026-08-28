from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models.banque import Banque
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.rbac import Permission, Role, role_permissions
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User


PROFILES = [
    "super_admin",
    "admin",
    "comptable",
    "caissier",
    "valideur",
    "expert_comptable",
    "utilisateur",
]

PASSWORD = "Load_Test_2026!"


@dataclass
class Result:
    name: str
    status: int
    elapsed_ms: float
    ok: bool
    detail: str | None = None
    response_bytes: int = 0


@dataclass
class StageReport:
    users: int
    duration_seconds: int
    warmup_seconds: int = 0
    wall_seconds: float = 0
    results: list[Result] = field(default_factory=list)
    warmup_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        total = len(self.results)
        errors = [r for r in self.results if not r.ok]
        latencies = [r.elapsed_ms for r in self.results]
        by_endpoint: dict[str, list[Result]] = {}
        statuses: dict[str, int] = {}
        error_types: dict[str, int] = {}
        for result in self.results:
            by_endpoint.setdefault(result.name, []).append(result)
            statuses[str(result.status)] = statuses.get(str(result.status), 0) + 1
            if not result.ok:
                key = result.detail or f"HTTP {result.status}"
                error_types[key] = error_types.get(key, 0) + 1

        def percentile(values: list[float], percent: float) -> float:
            if not values:
                return 0
            ordered = sorted(values)
            if len(ordered) == 1:
                return ordered[0]
            rank = (len(ordered) - 1) * (percent / 100)
            lower = int(rank)
            upper = min(lower + 1, len(ordered) - 1)
            weight = rank - lower
            return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

        def endpoint_stats(items: list[Result]) -> dict[str, Any]:
            endpoint_latencies = [item.elapsed_ms for item in items]
            endpoint_errors = [item for item in items if not item.ok]
            endpoint_statuses: dict[str, int] = {}
            for item in items:
                endpoint_statuses[str(item.status)] = endpoint_statuses.get(str(item.status), 0) + 1
            return {
                "requests": len(items),
                "errors": len(endpoint_errors),
                "error_rate_percent": round((len(endpoint_errors) / len(items)) * 100, 2) if items else 0,
                "status_codes": dict(sorted(endpoint_statuses.items())),
                "avg_response_bytes": round(statistics.mean([item.response_bytes for item in items]), 2) if items else 0,
                "avg_ms": round(statistics.mean(endpoint_latencies), 2) if endpoint_latencies else 0,
                "p50_ms": round(percentile(endpoint_latencies, 50), 2),
                "p90_ms": round(percentile(endpoint_latencies, 90), 2),
                "p95_ms": round(percentile(endpoint_latencies, 95), 2),
                "p99_ms": round(percentile(endpoint_latencies, 99), 2),
                "max_ms": round(max(endpoint_latencies), 2) if endpoint_latencies else 0,
            }

        data = {
            "users": self.users,
            "duration_seconds": self.duration_seconds,
            "warmup_seconds": self.warmup_seconds,
            "wall_seconds": round(self.wall_seconds, 2),
            "requests": total,
            "requests_per_second": round(total / self.duration_seconds, 2) if self.duration_seconds else 0,
            "completed_requests_per_second": round(total / self.wall_seconds, 2) if self.wall_seconds else 0,
            "errors": len(errors),
            "error_rate_percent": round((len(errors) / total) * 100, 2) if total else 0,
            "status_codes": dict(sorted(statuses.items())),
            "error_types": dict(sorted(error_types.items(), key=lambda item: item[1], reverse=True)[:10]),
            "error_samples": [
                {"endpoint": r.name, "status": r.status, "detail": r.detail}
                for r in errors[:10]
            ],
            "latency_ms": {
                "avg": round(statistics.mean(latencies), 2) if latencies else 0,
                "min": round(min(latencies), 2) if latencies else 0,
                "max": round(max(latencies), 2) if latencies else 0,
                "p50": round(percentile(latencies, 50), 2),
                "p90": round(percentile(latencies, 90), 2),
                "p95": round(percentile(latencies, 95), 2),
                "p99": round(percentile(latencies, 99), 2),
            },
            "endpoints": {
                name: endpoint_stats(items)
                for name, items in sorted(by_endpoint.items())
            },
        }
        if self.warmup_summary is not None:
            data["warmup_summary"] = self.warmup_summary
        return data


async def wait_for_api(base_url: str, *, timeout_seconds: int = 60) -> None:
    ready_url = f"{base_url.rstrip('/')}/health/ready"
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(ready_url)
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}: {response.text[:160]}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            await asyncio.sleep(1)
    raise RuntimeError(f"API non prête après {timeout_seconds}s: {last_error or 'aucun détail'}")


async def seed_data(slug: str, users: int, experts: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        res = await db.execute(select(Organisation).where(Organisation.slug == slug))
        org = res.scalar_one_or_none()
        if org is None:
            org = Organisation(
                nom=f"Load Test {slug}",
                slug=slug,
                plan_type="STANDARD",
                status_abonnement="ACTIVE",
                limite_utilisateurs=max(users + 10, 100),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(org)
            await db.flush()

        service = (
            await db.execute(select(Service).where(Service.organisation_id == org.id, Service.code == "LOAD"))
        ).scalar_one_or_none()
        if service is None:
            service = Service(organisation_id=org.id, code="LOAD", libelle="Service charge", is_active=True)
            db.add(service)
            await db.flush()

        permission_ids = (await db.execute(select(Permission.id))).scalars().all()
        role_ids: dict[str, int | None] = {"super_admin": None, "admin": None}
        for profile in PROFILES:
            if profile in role_ids:
                continue
            code = f"load_test_{profile}"
            role = (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
            if role is None:
                role = Role(code=code, label=f"Load test {profile}", description="Role utilise uniquement par les tests de charge")
                db.add(role)
                await db.flush()
            role_ids[profile] = role.id
            if permission_ids:
                existing_permission_ids = (
                    await db.execute(
                        select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role.id)
                    )
                ).scalars().all()
                missing = set(permission_ids) - set(existing_permission_ids)
                for permission_id in missing:
                    await db.execute(
                        role_permissions.insert().values(role_id=role.id, permission_id=permission_id)
                    )

        exercice = (
            await db.execute(select(BudgetExercice).where(BudgetExercice.organisation_id == org.id, BudgetExercice.annee == 2026))
        ).scalar_one_or_none()
        if exercice is None:
            exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
            db.add(exercice)
            await db.flush()

        recette = (
            await db.execute(
                select(BudgetPoste).where(
                    BudgetPoste.organisation_id == org.id,
                    BudgetPoste.exercice_id == exercice.id,
                    BudgetPoste.code == "LT-REC",
                )
            )
        ).scalar_one_or_none()
        if recette is None:
            recette = BudgetPoste(
                organisation_id=org.id,
                exercice_id=exercice.id,
                code="LT-REC",
                libelle="Recettes test charge",
                type="RECETTE",
                active=True,
                montant_prevu=Decimal("1000000"),
                montant_engage=0,
                montant_paye=0,
                is_deleted=False,
            )
            db.add(recette)
        depense = (
            await db.execute(
                select(BudgetPoste).where(
                    BudgetPoste.organisation_id == org.id,
                    BudgetPoste.exercice_id == exercice.id,
                    BudgetPoste.code == "LT-DEP",
                )
            )
        ).scalar_one_or_none()
        if depense is None:
            depense = BudgetPoste(
                organisation_id=org.id,
                exercice_id=exercice.id,
                code="LT-DEP",
                libelle="Dépenses test charge",
                type="DEPENSE",
                active=True,
                montant_prevu=Decimal("1000000"),
                montant_engage=0,
                montant_paye=0,
                is_deleted=False,
            )
            db.add(depense)
        await db.flush()

        allowed_ids = (
            await db.execute(
                select(ServiceRubrique.budget_poste_id).where(ServiceRubrique.service_id == service.id)
            )
        ).scalars().all()
        for poste_id in {recette.id, depense.id} - set(allowed_ids):
            db.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste_id))

        caisse = (
            await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id))
        ).scalar_one_or_none()
        if caisse is None:
            db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500000"), solde_cdf=Decimal("0"), est_ouverte=True))

        banque = (
            await db.execute(
                select(Banque).where(
                    Banque.organisation_id == org.id,
                    Banque.nom == "LOAD BANK",
                )
            )
        ).scalar_one_or_none()
        if banque is None:
            banque = Banque(organisation_id=org.id, nom="LOAD BANK", code="LOAD", is_active=True)
            db.add(banque)
            await db.flush()

        bank = (
            await db.execute(
                select(CompteBancaire).where(
                    CompteBancaire.organisation_id == org.id,
                    CompteBancaire.numero_compte == "LOAD-BANK-USD",
                )
            )
        ).scalar_one_or_none()
        if bank is None:
            db.add(
                CompteBancaire(
                    organisation_id=org.id,
                    banque_id=banque.id,
                    intitule="Compte load test",
                    numero_compte="LOAD-BANK-USD",
                    devise="USD",
                    solde_initial=Decimal("500000"),
                    solde_actuel=Decimal("500000"),
                    is_active=True,
                    account_type="BANK",
                )
            )

        existing_users = (
            await db.execute(
                select(func.count(User.id)).where(
                    User.organisation_id == org.id,
                    User.email.like("load-%@example.com"),
                )
            )
        ).scalar_one()
        if existing_users < users:
            existing = (
                await db.execute(
                    select(User.email).where(
                        User.organisation_id == org.id,
                        User.email.like("load-%@example.com"),
                    )
                )
            ).scalars().all()
            existing_set = set(existing)
            password_hash = hash_password(PASSWORD)
            for i in range(users):
                profile = PROFILES[i % len(PROFILES)]
                email = f"load-{i:04d}@example.com"
                if email in existing_set:
                    continue
                db.add(
                    User(
                        id=uuid.uuid4(),
                        email=email,
                        nom=f"Load{i:04d}",
                        prenom=profile,
                        hashed_password=password_hash,
                        role=profile,
                        role_id=role_ids.get(profile),
                        organisation_id=org.id,
                        service_id=service.id,
                        active=True,
                        is_email_verified=True,
                        is_first_login=False,
                        must_change_password=False,
                    )
                )
                existing_set.add(email)
                if len(existing_set) >= users:
                    break

        existing_load_users = (
            await db.execute(
                select(User).where(
                    User.organisation_id == org.id,
                    User.email.like("load-%@example.com"),
                )
            )
        ).scalars().all()
        for user in existing_load_users:
            profile = (user.role or "").strip().lower()
            if profile in role_ids and user.role_id != role_ids[profile]:
                user.role_id = role_ids[profile]

        existing_experts = (
            await db.execute(select(ExpertComptable.numero_ordre).where(ExpertComptable.numero_ordre.like("LT/%")))
        ).scalars().all()
        existing_experts_set = set(existing_experts)
        for i in range(experts):
            numero = f"LT/{i:05d}"
            if numero in existing_experts_set:
                continue
            db.add(
                ExpertComptable(
                    numero_ordre=numero,
                    nom_denomination=f"Expert charge {i:05d}",
                    type_ec="SEC" if i % 7 == 0 else "EC",
                    categorie_personne="Personne Morale" if i % 7 == 0 else "Personne Physique",
                    statut_professionnel=random.choice(["En Cabinet", "Indépendant", "Salarié"]),
                    active=True,
                    created_at=now,
                )
            )

        await db.commit()
        user_rows = (
            await db.execute(
                select(User.id, User.role).where(
                    User.organisation_id == org.id,
                    User.email.like("load-%@example.com"),
                ).order_by(User.email.asc())
            )
        ).all()
        return {
            "organisation_id": org.id,
            "organisation_slug": org.slug,
            "service_id": service.id,
            "recette_id": recette.id,
            "depense_id": depense.id,
            "users": [{"id": str(row[0]), "role": row[1]} for row in user_rows],
        }


async def timed(client: httpx.AsyncClient, method: str, url: str, *, name: str, **kwargs: Any) -> Result:
    start = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        detail = None
        if response.status_code >= 400:
            detail = response.text[:300]
        return Result(
            name=name,
            status=response.status_code,
            elapsed_ms=elapsed,
            ok=200 <= response.status_code < 400,
            detail=detail,
            response_bytes=len(response.content or b""),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        message = str(exc).strip()
        detail = type(exc).__name__ if not message else f"{type(exc).__name__}: {message[:260]}"
        return Result(name=name, status=0, elapsed_ms=elapsed, ok=False, detail=detail)


async def login(client: httpx.AsyncClient, base_url: str, org_id: int, index: int) -> str | None:
    response = await client.post(
        f"{base_url}/auth/login",
        json={"email": f"load-{index:04d}@example.com", "password": PASSWORD, "tenant_id": org_id},
        headers={"X-Tenant-ID": str(org_id)},
    )
    if response.status_code != 200:
        return None
    return response.json().get("access_token")


def direct_token(context: dict[str, Any], index: int) -> str | None:
    users = context.get("users") or []
    if not users:
        return None
    user = users[index % len(users)]
    token, _ = create_access_token(
        subject=user["id"],
        role=user["role"],
        org_id=context["organisation_id"],
        org_slug=context["organisation_slug"],
    )
    return token


async def virtual_user(
    index: int,
    *,
    base_url: str,
    org_id: int,
    duration: int,
    context: dict[str, Any],
    report: StageReport,
    auth_mode: str,
    think_min: float,
    think_max: float,
) -> None:
    timeout = httpx.Timeout(20.0, connect=5.0, read=20.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = direct_token(context, index) if auth_mode == "direct-token" else await login(client, base_url, org_id, index)
        if not token:
            report.results.append(Result(name="login", status=401, elapsed_ms=0, ok=False))
            return
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(org_id)}
        deadline = time.monotonic() + duration
        offset = random.randint(0, 20)
        profile = PROFILES[index % len(PROFILES)]
        can_write = profile in {"super_admin", "admin"}
        while time.monotonic() < deadline:
            action = random.random() if can_write else random.uniform(0, 0.84)
            if action < 0.16:
                result = await timed(client, "GET", f"{base_url}/dashboard/stats", name="dashboard", headers=headers)
            elif action < 0.32:
                result = await timed(
                    client,
                    "GET",
                    f"{base_url}/experts-comptables?include_summary=true&limit=25&offset={offset}",
                    name="experts_list",
                    headers=headers,
                )
            elif action < 0.48:
                result = await timed(
                    client,
                    "GET",
                    f"{base_url}/budget/postes/tree?annee=2026&type={random.choice(['RECETTE', 'DEPENSE'])}",
                    name="budget_tree",
                    headers=headers,
                )
            elif action < 0.60:
                result = await timed(client, "GET", f"{base_url}/requisitions?limit=20&offset={offset}", name="requisitions_list", headers=headers)
            elif action < 0.72:
                result = await timed(client, "GET", f"{base_url}/encaissements?limit=20&offset={offset}", name="encaissements_list", headers=headers)
            elif action < 0.84:
                result = await timed(client, "GET", f"{base_url}/reports/summary", name="reports_summary", headers=headers)
            elif action < 0.93:
                payload = {
                    "objet": f"Charge requisition {uuid.uuid4().hex[:8]}",
                    "mode_paiement": "cash",
                    "type_requisition": "classique",
                    "montant_total": "25.00",
                    "devise": "USD",
                    "service_id": context["service_id"],
                    "status": "BROUILLON",
                }
                result = await timed(client, "POST", f"{base_url}/requisitions", name="requisition_create", headers=headers, json=payload)
            else:
                payload = {
                    "type_client": "autre",
                    "client_nom": f"Client charge {uuid.uuid4().hex[:8]}",
                    "libelle": "Encaissement charge",
                    "montant": "15.00",
                    "montant_total": "15.00",
                    "mode_paiement": "cash",
                    "canal": "CAISSE",
                    "montant_paye": "15.00",
                    "montant_percu": "15.00",
                    "devise_perception": "USD",
                    "statut_paiement": "complet",
                    "budget_poste_id": context["recette_id"],
                    "service_id": context["service_id"],
                }
                result = await timed(client, "POST", f"{base_url}/encaissements", name="encaissement_create", headers=headers, json=payload)
            report.results.append(result)
            offset = (offset + 25) % 500
            if think_max > 0:
                await asyncio.sleep(random.uniform(think_min, think_max))


async def run_stage(
    base_url: str,
    context: dict[str, Any],
    users: int,
    duration: int,
    auth_mode: str,
    *,
    warmup: int,
    think_min: float,
    think_max: float,
) -> StageReport:
    if warmup > 0:
        warmup_report = StageReport(users=users, duration_seconds=warmup, warmup_seconds=warmup)
        warmup_tasks = [
            virtual_user(
                i,
                base_url=base_url,
                org_id=context["organisation_id"],
                duration=warmup,
                context=context,
                report=warmup_report,
                auth_mode=auth_mode,
                think_min=think_min,
                think_max=think_max,
            )
            for i in range(users)
        ]
        warmup_start = time.perf_counter()
        await asyncio.gather(*warmup_tasks)
        warmup_report.wall_seconds = time.perf_counter() - warmup_start

    report = StageReport(users=users, duration_seconds=duration, warmup_seconds=warmup)
    if warmup > 0:
        report.warmup_summary = warmup_report.to_dict()
    tasks = [
        virtual_user(
            i,
            base_url=base_url,
            org_id=context["organisation_id"],
            duration=duration,
            context=context,
            report=report,
            auth_mode=auth_mode,
            think_min=think_min,
            think_max=think_max,
        )
        for i in range(users)
    ]
    start = time.perf_counter()
    await asyncio.gather(*tasks)
    report.wall_seconds = time.perf_counter() - start
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ONEC Smart backend load campaign")
    parser.add_argument("--base-url", default="http://backend:8000/api/v1")
    parser.add_argument("--slug", default="load-test-20260803")
    parser.add_argument("--seed-users", type=int, default=1000)
    parser.add_argument("--seed-experts", type=int, default=1000)
    parser.add_argument("--stages", default="100")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--stabilize-seconds", type=int, default=10)
    parser.add_argument("--profile", choices=["realistic", "stress"], default="realistic")
    parser.add_argument("--think-min", type=float, default=None)
    parser.add_argument("--think-max", type=float, default=None)
    parser.add_argument("--auth-mode", choices=["direct-token", "login"], default="direct-token")
    parser.add_argument("--out", default="/tmp/onec_load_report.json")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    context = await seed_data(args.slug, args.seed_users, args.seed_experts)
    if args.think_min is None or args.think_max is None:
        if args.profile == "realistic":
            think_min = 0.5
            think_max = 2.0
        else:
            think_min = 0.0
            think_max = 0.0
    else:
        think_min = max(0.0, args.think_min)
        think_max = max(think_min, args.think_max)
    reports = []
    for users in [int(part.strip()) for part in args.stages.split(",") if part.strip()]:
        if reports and args.stabilize_seconds > 0:
            await asyncio.sleep(args.stabilize_seconds)
        await wait_for_api(args.base_url.rstrip("/"))
        started = datetime.now(timezone.utc).isoformat()
        stage = await run_stage(
            args.base_url.rstrip("/"),
            context,
            users,
            args.duration,
            args.auth_mode,
            warmup=args.warmup,
            think_min=think_min,
            think_max=think_max,
        )
        data = stage.to_dict()
        data["started_at"] = started
        reports.append(data)
        print(json.dumps(data, ensure_ascii=False, indent=2))

    output = {
        "base_url": args.base_url,
        "auth_mode": args.auth_mode,
        "profile": args.profile,
        "think_time_seconds": {"min": think_min, "max": think_max},
        "stage_isolation": {
            "warmup_seconds": args.warmup,
            "stabilize_seconds_between_stages": args.stabilize_seconds,
            "note": "Chaque palier est lance avec de nouveaux clients HTTP apres une pause de stabilisation.",
        },
        "seed": {key: value for key, value in context.items() if key != "users"},
        "seeded_users": len(context.get("users") or []),
        "stages": reports,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cleanup_marker": args.slug,
    }
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LOAD_REPORT={args.out}")


if __name__ == "__main__":
    asyncio.run(main())
