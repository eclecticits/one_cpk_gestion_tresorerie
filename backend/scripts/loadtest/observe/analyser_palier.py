#!/usr/bin/env python3
"""Diagnostic d'un palier : ou passe le temps, et quel mur a ete touche.

    ./analyser_palier.py resultats/apres_8workers/palier_10vu [--route /api/v1/dashboard/stats]

Le comparateur (comparer_paliers.py) dit SI c'est mieux ; celui-ci dit POURQUOI.
Il croise les trois sources produites pendant le tir :

  _pool.log         marqueurs applicatifs (SLOW_REQUEST, DB_*, WORKER TIMEOUT)
  _pg_activity.csv  connexions PostgreSQL par etat, echantillonnees
  _docker_stats.csv CPU par conteneur

La question qu'il tranche : le temps est-il dans SQL ou hors SQL ? C'est elle
qui separe « il faut un index » de « il faut des workers ». Un p95 en minutes
avec 40 % de SQL ne se corrige pas dans PostgreSQL.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

MARQUEURS = [
    "SLOW_REQUEST",
    "DB_SLOW_QUERY",
    "DB_POOL_AT_CAPACITY",
    "DB_POOL_SLOW_USAGE",
    "QueuePool limit",
    "WORKER TIMEOUT",
    "too many clients",
]

MOTIF_SLOW = re.compile(
    r"SLOW_REQUEST method=(\S+) path=(\S+) status=(\S+) duration_ms=(\d+) tenant_id=(\S+) "
    r"db_queries=(\d+) db_total_ms=(\d+) db_slowest_ms=(\d+) db_conn_uses=(\d+) "
    r"db_conn_total_ms=(\d+) db_conn_max_ms=(\d+)"
)


def fmt(ms: float) -> str:
    if ms >= 60_000:
        return f"{int(ms // 60_000)}m{int((ms % 60_000) / 1000):02d}s"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"


def charger_requetes(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    lignes = []
    for l in chemin.read_text(errors="replace").splitlines():
        m = MOTIF_SLOW.search(l)
        if not m:
            continue
        methode, path, statut, dur, tenant, nq, dbt, dbs, cu, ct, cm = m.groups()
        lignes.append({
            "methode": methode, "path": path, "statut": statut,
            "duree": int(dur), "requetes_sql": int(nq), "sql_ms": int(dbt),
            "sql_max_ms": int(dbs), "conn_ms": int(ct),
        })
    return lignes


def section_marqueurs(pool_log: Path) -> None:
    if not pool_log.exists():
        print("  (pas de _pool.log — collecte absente pour ce palier)")
        return
    texte = pool_log.read_text(errors="replace")
    print(f"\n  {'marqueur':<24}{'occurrences':>12}")
    print("  " + "-" * 36)
    for marqueur in MARQUEURS:
        n = texte.count(marqueur)
        if n:
            print(f"  {marqueur:<24}{n:>12}")


def section_routes(requetes: list[dict], filtre: str | None) -> None:
    if not requetes:
        print("\n  Aucune requete lente enregistree.")
        return
    par_route: dict[str, list[dict]] = defaultdict(list)
    for r in requetes:
        par_route[r["path"]].append(r)

    if filtre:
        par_route = {k: v for k, v in par_route.items() if filtre in k}
        if not par_route:
            print(f"\n  Aucune requete lente sur les routes contenant « {filtre} ».")
            return

    print(f"\n  {'route':<40}{'n':>4}{'max':>9}{'moy':>9}{'SQL':>9}{'hors SQL':>10}{'req SQL':>9}")
    print("  " + "-" * 90)
    total_d = total_sql = 0
    for path, v in sorted(par_route.items(), key=lambda kv: -max(x["duree"] for x in kv[1])):
        n = len(v)
        dmoy = sum(x["duree"] for x in v) / n
        sqlmoy = sum(x["sql_ms"] for x in v) / n
        total_d += sum(x["duree"] for x in v)
        total_sql += sum(x["sql_ms"] for x in v)
        affiche = path if len(path) <= 39 else path[:36] + "..."
        print(f"  {affiche:<40}{n:>4}{fmt(max(x['duree'] for x in v)):>9}{fmt(dmoy):>9}"
              f"{fmt(sqlmoy):>9}{fmt(dmoy - sqlmoy):>10}"
              f"{sum(x['requetes_sql'] for x in v) / n:>9.0f}")
    if total_d:
        part = total_sql / total_d
        print("  " + "-" * 90)
        print(f"  {part:.0%} du temps dans SQL, {1 - part:.0%} hors SQL "
              f"(Python, GIL, attente d'un worker libre).")
        print("  " + ("  → le mur est applicatif, pas PostgreSQL." if part < 0.5
                      else "  → PostgreSQL porte la moitie ou plus du temps."))


def section_postgres(pg_csv: Path) -> None:
    if not pg_csv.exists():
        print("\n  (pas de _pg_activity.csv)")
        return
    par_horodatage: dict[str, dict[str, int]] = defaultdict(dict)
    for r in csv.DictReader(pg_csv.open()):
        try:
            par_horodatage[r["horodatage"]][r["etat"]] = int(r["connexions"])
        except (KeyError, ValueError):
            continue
    if not par_horodatage:
        print("\n  PostgreSQL : aucun echantillon exploitable.")
        return
    totaux = [sum(e.values()) for e in par_horodatage.values()]
    actifs = [e.get("active", 0) for e in par_horodatage.values()]
    idle_tx = [e.get("idle in transaction", 0) for e in par_horodatage.values()]
    print(f"\n  PostgreSQL ({len(totaux)} echantillons)")
    print(f"    connexions totales     moy {sum(totaux)/len(totaux):>5.0f}   max {max(totaux):>4}")
    print(f"    dont actives           moy {sum(actifs)/len(actifs):>5.0f}   max {max(actifs):>4}")
    print(f"    idle in transaction    moy {sum(idle_tx)/len(idle_tx):>5.0f}   max {max(idle_tx):>4}")
    if max(idle_tx) > 2:
        print("    ⚠ des connexions restent en transaction ouverte : elles tiennent"
              " des verrous et une place du pool sans travailler.")


def section_cpu(stats_csv: Path) -> None:
    if not stats_csv.exists():
        return
    cpu: dict[str, list[float]] = defaultdict(list)
    for r in csv.DictReader(stats_csv.open()):
        try:
            cpu[r["conteneur"]].append(float(r["cpu_pct"].rstrip("%")))
        except (KeyError, ValueError):
            continue
    interessants = {c: v for c, v in cpu.items() if "onec" in c and v}
    if not interessants:
        return
    print(f"\n  CPU par conteneur ({len(next(iter(interessants.values())))} echantillons)")
    for c, v in sorted(interessants.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"    {c:<28} moy {sum(v)/len(v):>5.0f}%   max {max(v):>5.0f}%")
    print("    (100% = un coeur ; N workers satures plafonnent vers N x 100%)")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    filtre = None
    if "--route" in sys.argv:
        i = sys.argv.index("--route")
        if i + 1 < len(sys.argv):
            filtre = sys.argv[i + 1]
            args = [a for a in args if a != filtre]
    if len(args) != 1:
        print(__doc__)
        return 2

    prefixe = Path(args[0])
    print(f"{'=' * 94}\n PALIER {prefixe.name}\n{'=' * 94}")
    section_marqueurs(Path(f"{prefixe}_pool.log"))
    section_routes(charger_requetes(Path(f"{prefixe}_pool.log")), filtre)
    section_postgres(Path(f"{prefixe}_pg_activity.csv"))
    section_cpu(Path(f"{prefixe}_docker_stats.csv"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
