from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def generate_analyse_report(
    exercice: str,
    stats: dict[str, Any],
    anomalies: list[dict[str, Any]],
    instructions: str | None = None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    anomalies_haute = [a for a in anomalies if a.get("gravite") == "high"]
    anomalies_moyenne = [a for a in anomalies if a.get("gravite") == "medium"]
    anomalies_basse = [a for a in anomalies if a.get("gravite") == "low"]

    lines = [
        f"RAPPORT D'ANALYSE — TABLEAU {exercice}",
        f"Généré le : {now}",
        "",
        "═" * 60,
        "STATISTIQUES GÉNÉRALES",
        "═" * 60,
        f"  Dossiers importés     : {stats.get('total_dossiers', 0)}",
        f"  Dossiers complets     : {stats.get('dossiers_complets', 0)}",
        f"  Dossiers incomplets   : {stats.get('dossiers_incomplets', 0)}",
        f"  Anomalies détectées   : {stats.get('anomalies_count', 0)}",
        f"  Doublons              : {stats.get('doublons_count', 0)}",
        f"  Cotisations non payées: {stats.get('cotisations_non_payees', 0)}",
        f"  Heures FORCO insuff.  : {stats.get('heures_forco_insuffisantes', 0)}",
        f"  Assurances manquantes : {stats.get('assurances_manquantes', 0)}",
        "",
    ]

    cats = (stats.get("stats_json") or {}).get("categories", {})
    if cats:
        lines += ["RÉPARTITION PAR CATÉGORIE", "─" * 40]
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat:<30} {cnt}")
        lines.append("")

    if anomalies_haute:
        lines += ["ANOMALIES CRITIQUES (gravité haute)", "─" * 40]
        for a in anomalies_haute[:20]:
            lines.append(f"  [{a['type_anomalie']}] Dossier #{a['dossier_id']} — {a['description']}")
        lines.append("")

    if anomalies_moyenne:
        lines += ["ANOMALIES IMPORTANTES (gravité moyenne)", "─" * 40]
        for a in anomalies_moyenne[:20]:
            lines.append(f"  [{a['type_anomalie']}] Dossier #{a['dossier_id']} — {a['description']}")
        lines.append("")

    if anomalies_basse:
        lines += ["ANOMALIES MINEURES (gravité basse)", "─" * 40]
        for a in anomalies_basse[:10]:
            lines.append(f"  [{a['type_anomalie']}] Dossier #{a['dossier_id']} — {a['description']}")
        lines.append("")

    if instructions:
        lines += ["INSTRUCTIONS COMPLÉMENTAIRES", "─" * 40, f"  {instructions}", ""]

    lines += [
        "═" * 60,
        "FIN DU RAPPORT",
        "═" * 60,
    ]
    return "\n".join(lines)


def generate_pv(
    exercice: str,
    stats: dict[str, Any],
    decisions: list[dict[str, Any]],
    instructions: str | None = None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

    lines = [
        f"PROCÈS-VERBAL DE LA COMMISSION TABLEAU — EXERCICE {exercice}",
        f"Date de génération : {now}",
        "",
        "═" * 60,
        "L'AN DEUX MIL VINGT-SIX, la Commission Tableau s'est réunie",
        f"pour examiner le tableau de l'exercice {exercice}.",
        "",
        "ORDRE DU JOUR :",
        "  1. Examen du tableau des experts-comptables",
        "  2. Analyse des dossiers d'inscription",
        "  3. Examen des changements de catégorie",
        "  4. Contrôle des cotisations",
        "  5. Contrôle des heures FORCO",
        "  6. Contrôle de l'assurance",
        "  7. Divers",
        "",
        "═" * 60,
        "BILAN DE L'EXAMEN",
        "═" * 60,
        f"  Nombre de dossiers examinés : {stats.get('total_dossiers', 0)}",
        f"  Dossiers conformes          : {stats.get('dossiers_complets', 0)}",
        f"  Dossiers avec anomalies     : {stats.get('anomalies_count', 0)}",
        "",
    ]

    if decisions:
        lines += ["DÉCISIONS DE LA COMMISSION", "─" * 40]
        for d in decisions[:30]:
            lines.append(f"  • {d.get('type_decision', '')} — {d.get('decision', '')} (Dossier #{d.get('dossier_id', '')})")
            if d.get("motif"):
                lines.append(f"    Motif : {d['motif']}")
        lines.append("")

    if instructions:
        lines += ["OBSERVATIONS COMPLÉMENTAIRES", "─" * 40, f"  {instructions}", ""]

    lines += [
        "═" * 60,
        "Le présent procès-verbal a été rédigé et est soumis à validation.",
        "─" * 60,
        "Signature du Président de séance : _______________________",
        "Signature du Secrétaire          : _______________________",
        "═" * 60,
        "FIN DU PROCÈS-VERBAL",
    ]
    return "\n".join(lines)
