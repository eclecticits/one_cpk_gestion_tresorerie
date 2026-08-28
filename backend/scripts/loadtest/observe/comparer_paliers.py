#!/usr/bin/env python3
"""Compare deux campagnes de charge palier par palier, a partir des summary k6.

    ./comparer_paliers.py resultats/avant_listener resultats/apres_listener_et_index

Lit les fichiers `palier_<N>vu_summary.txt` des deux repertoires et met en
regard les metriques qui portent une decision : taux d'echec, p95 par parcours,
iterations menees a terme. Les seuils viennent de k6/journeys.js (thresholds) ;
une valeur qui les depasse est marquee, pour qu'on lise « tenu / pas tenu »
plutot qu'un simple mieux/moins bien.

Ne relit PAS les flux _raw.json : le summary suffit pour la comparaison, et il
est le seul artefact present pour les campagnes deja archivees.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Seuils p95 par parcours, en millisecondes — recopies de k6/journeys.js.
# S'ils changent la-bas, ils doivent changer ici, sinon la colonne « seuil »
# ment silencieusement.
SEUILS_P95_MS = {
    "dashboard": 1500,
    "listes": 2000,
    "rapports": 3000,
    "encaissement": 2000,
    "requisition": 2500,
    "sortie": 2500,
    "export": 10000,
}
SEUIL_ECHEC_GLOBAL = 0.01


def en_ms(valeur: str) -> float | None:
    """Convertit une duree k6 ('1m40s', '865.24ms', '4m53s', '0s') en ms."""
    valeur = valeur.strip()
    if not valeur:
        return None
    total = 0.0
    trouve = False
    for nombre, unite in re.findall(r"(\d+(?:\.\d+)?)(h|ms|m|s|µs)", valeur):
        trouve = True
        n = float(nombre)
        total += {"h": 3_600_000, "m": 60_000, "s": 1_000, "ms": 1, "µs": 0.001}[unite] * n
    return total if trouve else None


def lire_summary(chemin: Path) -> dict:
    """Extrait du summary les metriques finales. Prend la DERNIERE occurrence :
    le bloc de synthese est ecrit apres les lignes de progression."""
    if not chemin.exists():
        return {}
    texte = chemin.read_text(errors="replace")
    resultat: dict = {"p95": {}, "echec_parcours": {}}

    for parcours in SEUILS_P95_MS:
        motif = rf"\{{ journey:{parcours} \}}\.*:.*?p\(95\)=(\S+)"
        trouvailles = re.findall(motif, texte)
        if trouvailles:
            resultat["p95"][parcours] = en_ms(trouvailles[-1])

        motif_echec = rf"\{{ journey:{parcours} \}}\.*:\s+([\d.]+)%\s+\d+ out of \d+"
        trouvailles = re.findall(motif_echec, texte)
        if trouvailles:
            resultat["echec_parcours"][parcours] = float(trouvailles[-1]) / 100

    m = re.findall(r"http_req_failed\.+:\s+([\d.]+)%\s+(\d+) out of (\d+)", texte)
    if m:
        taux, echecs, total = m[-1]
        resultat["echec_global"] = float(taux) / 100
        resultat["requetes"] = int(total)
        resultat["echecs"] = int(echecs)

    m = re.findall(r"iterations\.+:\s+(\d+)\s", texte)
    if m:
        resultat["iterations"] = int(m[-1])

    m = re.findall(r"erreurs_5xx\.+:\s+(\d+)\s", texte)
    if m:
        resultat["erreurs_5xx"] = int(m[-1])

    m = re.findall(r"(\d+) complete and (\d+) interrupted iterations", texte)
    if m:
        resultat["completes"], resultat["interrompues"] = int(m[-1][0]), int(m[-1][1])

    return resultat


def fmt_ms(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 60_000:
        return f"{int(v // 60_000)}m{int((v % 60_000) / 1000):02d}s"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    return f"{v:.0f}ms"


def facteur(avant: float | None, apres: float | None) -> str:
    if not avant or apres is None:
        return "—"
    if apres == 0:
        return "→ 0"
    r = avant / apres
    return f"x{r:.1f}" if r >= 1 else f"/{1 / r:.1f} (recul)"


def comparer(dir_avant: Path, dir_apres: Path) -> int:
    paliers = sorted(
        {int(m.group(1))
         for d in (dir_avant, dir_apres)
         for f in d.glob("palier_*vu_summary.txt")
         if (m := re.search(r"palier_(\d+)vu", f.name))}
    )
    if not paliers:
        print("Aucun palier trouve dans ces deux repertoires.", file=sys.stderr)
        return 1

    print(f"AVANT : {dir_avant}")
    print(f"APRES : {dir_apres}")

    regression = False
    for vus in paliers:
        a = lire_summary(dir_avant / f"palier_{vus}vu_summary.txt")
        b = lire_summary(dir_apres / f"palier_{vus}vu_summary.txt")
        print(f"\n{'=' * 72}\n PALIER {vus} VU\n{'=' * 72}")
        if not a or not b:
            manquant = "AVANT" if not a else "APRES"
            print(f"  summary {manquant} absent ou incomplet — palier non comparable.")
            continue

        print(f"\n  {'':<24}{'avant':>12}{'apres':>12}")
        ea = a.get("echec_global")
        eb = b.get("echec_global")
        verdict = "" if eb is None else ("   TENU" if eb < SEUIL_ECHEC_GLOBAL else "   hors seuil")
        ea_txt = "—" if ea is None else f"{ea:.1%}"
        eb_txt = "—" if eb is None else f"{eb:.1%}"
        print(f"  {'taux d echec':<24}{ea_txt:>12}{eb_txt:>12}{verdict}")
        print(f"  {'requetes servies':<24}{a.get('requetes', 0):>12}{b.get('requetes', 0):>12}")
        print(f"  {'iterations completes':<24}{a.get('completes', 0):>12}{b.get('completes', 0):>12}")
        print(f"  {'iterations interrompues':<24}{a.get('interrompues', 0):>12}{b.get('interrompues', 0):>12}")
        print(f"  {'erreurs 5xx':<24}{a.get('erreurs_5xx', 0):>12}{b.get('erreurs_5xx', 0):>12}")

        print(f"\n  {'p95 par parcours':<24}{'avant':>12}{'apres':>12}{'gain':>16}{'seuil':>12}")
        for parcours, seuil in SEUILS_P95_MS.items():
            va = a["p95"].get(parcours)
            vb = b["p95"].get(parcours)
            if va is None and vb is None:
                continue
            etat = "—" if vb is None else ("TENU" if vb <= seuil else f"> {seuil}ms")
            if vb is not None and va is not None and vb > va * 1.1:
                regression = True
            print(f"  {parcours:<24}{fmt_ms(va):>12}{fmt_ms(vb):>12}{facteur(va, vb):>16}{etat:>12}")

    print(f"\n{'=' * 72}")
    print("Regression detectee sur au moins un parcours." if regression
          else "Aucune regression de p95 detectee.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(comparer(Path(sys.argv[1]), Path(sys.argv[2])))
