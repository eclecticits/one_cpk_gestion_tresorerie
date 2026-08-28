#!/usr/bin/env python3
"""Tableau de la matrice workers x paliers, avec ventilation des erreurs par CAUSE.

    ./matrice_tableau.py resultats/matrice_20260827_180000

Lit les flux bruts k6 (`palier_<N>vu_raw.json`) de chaque groupe `w<N>/`.

Pourquoi la ventilation par cause plutot qu'un taux d'echec global : la campagne
du 27/08 affichait 34,6 % d'echec, dont 80 % venaient du jeu de test (tenant
suspendu, adresses invalides) et non de la charge. Un taux global ne distingue
pas « le serveur sature » de « le scenario est casse » — et les deux appellent
des corrections opposees.

Les codes sont regroupes ainsi :

    saturation   statut 0        pas de reponse HTTP : timeout ou abandon client
    serveur      5xx             defaut applicatif
    debit        429             anti-bruteforce, pas de la capacite
    metier       400/409         regle metier appliquee (comportement correct)
    droits       401/403         authentification ou permission
    abonnement   402             tenant inactif — artefact de jeu de test
    payload      422             charge utile refusee — souvent le jeu de test
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CAUSES = [
    ("saturation", lambda s: s == "0"),
    ("serveur", lambda s: s.startswith("5")),
    ("debit", lambda s: s == "429"),
    ("abonnement", lambda s: s == "402"),
    ("droits", lambda s: s in ("401", "403")),
    ("payload", lambda s: s == "422"),
    ("metier", lambda s: s in ("400", "409")),
]


def cause_de(statut: str) -> str:
    for nom, predicat in CAUSES:
        if predicat(statut):
            return nom
    return f"autre({statut})"


def fmt_ms(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 60_000:
        return f"{int(v // 60_000)}m{int((v % 60_000) / 1000):02d}s"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    return f"{v:.0f}ms"


def lire_palier(chemin: Path) -> dict | None:
    """Depouille un flux brut k6. Renvoie None si le palier n'a pas ete mesure."""
    if not chemin.exists():
        return None
    durees: list[float] = []
    total = 0
    echecs = 0
    par_cause: dict[str, int] = defaultdict(int)
    par_requete_cause: dict[tuple[str, str], int] = defaultdict(int)
    iterations = 0

    with chemin.open(errors="replace") as f:
        for ligne in f:
            try:
                d = json.loads(ligne)
            except ValueError:
                continue
            if d.get("type") != "Point":
                continue
            metrique = d.get("metric")
            data = d.get("data") or {}
            tags = data.get("tags") or {}
            if metrique == "http_req_duration":
                durees.append(data.get("value", 0.0))
            elif metrique == "http_req_failed":
                total += 1
                if data.get("value") == 1:
                    echecs += 1
                    statut = str(tags.get("status", "?"))
                    cause = cause_de(statut)
                    par_cause[cause] += 1
                    par_requete_cause[(tags.get("name", "?"), cause)] += 1
            elif metrique == "iterations":
                iterations += 1

    if total == 0:
        return None
    durees.sort()

    def centile(p: float) -> float | None:
        if not durees:
            return None
        return durees[min(len(durees) - 1, int(len(durees) * p))]

    return {
        "requetes": total,
        "echecs": echecs,
        "taux": echecs / total,
        "p50": centile(0.50),
        "p95": centile(0.95),
        "p99": centile(0.99),
        "iterations": iterations,
        "causes": dict(par_cause),
        "par_requete": dict(par_requete_cause),
    }


def main(racine: Path) -> int:
    groupes = sorted(
        (d for d in racine.iterdir() if d.is_dir() and re.fullmatch(r"w\d+", d.name)),
        key=lambda d: int(d.name[1:]),
    )
    if not groupes:
        print(f"Aucun groupe w<N> dans {racine}", file=sys.stderr)
        return 1

    paliers = sorted(
        {int(m.group(1))
         for g in groupes
         for f in g.glob("palier_*vu_raw.json")
         if (m := re.search(r"palier_(\d+)vu", f.name))}
    )

    releves: dict[tuple[str, int], dict | None] = {}
    for g in groupes:
        for vus in paliers:
            releves[(g.name, vus)] = lire_palier(g / f"palier_{vus}vu_raw.json")

    # ---- Tableau principal --------------------------------------------------
    print("=" * 86)
    print(" MATRICE workers x paliers")
    print("=" * 86)
    print(f"\n{'workers':<9}{'VU':>5}{'requetes':>10}{'echecs':>9}{'taux':>8}"
          f"{'p50':>10}{'p95':>10}{'p99':>10}")
    print("-" * 86)
    for g in groupes:
        for vus in paliers:
            r = releves[(g.name, vus)]
            if r is None:
                print(f"{g.name[1:]:<9}{vus:>5}{'—':>10}{'—':>9}{'non mesure':>8}")
                continue
            print(f"{g.name[1:]:<9}{vus:>5}{r['requetes']:>10}{r['echecs']:>9}"
                  f"{r['taux']:>7.1%}{fmt_ms(r['p50']):>10}{fmt_ms(r['p95']):>10}"
                  f"{fmt_ms(r['p99']):>10}")
        print()

    # ---- Ventilation par cause ---------------------------------------------
    toutes_causes = sorted({c for r in releves.values() if r for c in r["causes"]})
    if toutes_causes:
        print("=" * 86)
        print(" ERREURS PAR CAUSE")
        print("=" * 86)
        entete = f"\n{'workers':<9}{'VU':>5}" + "".join(f"{c:>13}" for c in toutes_causes)
        print(entete)
        print("-" * (14 + 13 * len(toutes_causes)))
        for g in groupes:
            for vus in paliers:
                r = releves[(g.name, vus)]
                if r is None:
                    continue
                ligne = f"{g.name[1:]:<9}{vus:>5}"
                for c in toutes_causes:
                    n = r["causes"].get(c, 0)
                    ligne += f"{(str(n) if n else '·'):>13}"
                print(ligne)
            print()

        print("  saturation = statut 0, aucune reponse HTTP recue (timeout/abandon)")
        print("  metier     = 400/409, la regle metier s'applique : ce n'est pas une panne")
        print("  abonnement/payload/droits = artefacts de jeu de test s'ils sont massifs")

    # ---- Top des requetes fautives -----------------------------------------
    cumul: dict[tuple[str, str], int] = defaultdict(int)
    for r in releves.values():
        if r:
            for (nom, cause), n in r["par_requete"].items():
                cumul[(nom, cause)] += n
    if cumul:
        print("\n" + "=" * 86)
        print(" REQUETES LES PLUS FAUTIVES (toute la matrice)")
        print("=" * 86)
        print(f"\n{'requete':<32}{'cause':<14}{'occurrences':>12}")
        print("-" * 60)
        for (nom, cause), n in sorted(cumul.items(), key=lambda kv: -kv[1])[:15]:
            print(f"{nom:<32}{cause:<14}{n:>12}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
