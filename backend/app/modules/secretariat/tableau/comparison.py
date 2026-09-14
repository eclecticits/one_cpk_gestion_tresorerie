from __future__ import annotations

from typing import Any


def compare_exercices(
    dossiers_a: list[dict[str, Any]],
    dossiers_b: list[dict[str, Any]],
    exercice_a: str,
    exercice_b: str,
) -> dict[str, Any]:
    def key(d: dict) -> str:
        numero = (d.get("numero_ordre") or "").strip().upper().replace(" ", "")
        if numero:
            return f"ordre:{numero}"
        return f"{(d.get('nom') or '').strip().lower()}|{(d.get('prenom') or '').strip().lower()}"

    map_a = {key(d): d for d in dossiers_a}
    map_b = {key(d): d for d in dossiers_b}

    keys_a = set(map_a)
    keys_b = set(map_b)

    en_commun = keys_a & keys_b
    nouveaux_dans_b = keys_b - keys_a
    absents_de_b = keys_a - keys_b

    changements_categorie = []
    for k in en_commun:
        cat_a = (map_a[k].get("categorie") or "").strip()
        cat_b = (map_b[k].get("categorie") or "").strip()
        if cat_a != cat_b:
            d = map_b[k]
            changements_categorie.append({
                "numero_ordre": d.get("numero_ordre"),
                "nom": d.get("nom"),
                "prenom": d.get("prenom"),
                "categorie_avant": cat_a,
                "categorie_apres": cat_b,
            })

    details: list[dict[str, Any]] = []
    for k in sorted(nouveaux_dans_b):
        d = map_b[k]
        details.append({
            "type": "nouveau",
            "numero_ordre": d.get("numero_ordre"),
            "nom": d.get("nom"),
            "prenom": d.get("prenom"),
            "categorie": d.get("categorie"),
            "exercice": exercice_b,
        })
    for k in sorted(absents_de_b):
        d = map_a[k]
        details.append({
            "type": "absent",
            "numero_ordre": d.get("numero_ordre"),
            "nom": d.get("nom"),
            "prenom": d.get("prenom"),
            "categorie": d.get("categorie"),
            "exercice": exercice_a,
        })
    for item in changements_categorie:
        details.append({"type": "changement_categorie", **item})

    return {
        "exercice_a": exercice_a,
        "exercice_b": exercice_b,
        "dossiers_en_commun": len(en_commun),
        "nouveaux_dans_b": len(nouveaux_dans_b),
        "absents_de_b": len(absents_de_b),
        "changements_categorie": len(changements_categorie),
        "details": details,
    }
