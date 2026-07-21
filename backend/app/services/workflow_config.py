"""Configuration du circuit de validation des réquisitions / sorties de fonds.

Le circuit complet enchaîne :
  création → signature service → examen → 1re validation → 2e validation → paiement

Chaque organisation peut activer/désactiver certaines étapes via
`OrganisationSettings.workflow_config` (JSONB). Étapes configurables :
  - signature_service   (désactivable)
  - examen              (désactivable ; couvre soumission + visa d'examen)
  - validation_2        (désactivable ; seuil de montant optionnel)
La 1re validation (validation_1) est TOUJOURS obligatoire — garde-fou : on
n'autorise jamais une sortie de fonds sans aucune validation.

Ce module centralise les défauts, les presets et la normalisation, pour que
le backend ET le frontend partagent exactement la même logique.
"""

from __future__ import annotations

from typing import Any

# Étapes configurables et leur caractère obligatoire.
CONFIGURABLE_STEPS = ("signature_service", "examen", "validation_1", "validation_2")
MANDATORY_STEPS = ("validation_1",)

# Presets prêts à l'emploi (l'admin part de là puis ajuste si besoin).
PRESETS: dict[str, dict[str, bool]] = {
    "complet": {
        "signature_service": True,
        "examen": True,
        "validation_1": True,
        "validation_2": True,
    },
    "standard": {
        "signature_service": True,
        "examen": False,
        "validation_1": True,
        "validation_2": True,
    },
    "simplifie": {
        "signature_service": False,
        "examen": False,
        "validation_1": True,
        "validation_2": True,
    },
    "express": {
        "signature_service": False,
        "examen": False,
        "validation_1": True,
        "validation_2": False,
    },
}

DEFAULT_PRESET = "complet"


def default_config() -> dict[str, Any]:
    """Circuit complet — comportement historique (aucun changement)."""
    steps = {
        name: {"enabled": PRESETS[DEFAULT_PRESET][name]}
        for name in CONFIGURABLE_STEPS
    }
    return {"preset": DEFAULT_PRESET, "steps": steps}


def _coerce_amount(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        amount = float(value)
        return amount if amount > 0 else None
    except (TypeError, ValueError):
        return None


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise une config brute (venant de la base ou de l'API) vers une
    structure complète et sûre. Applique les garde-fous.
    """
    base = default_config()
    if not isinstance(raw, dict):
        return base

    preset = raw.get("preset")
    if preset in PRESETS:
        for name in CONFIGURABLE_STEPS:
            base["steps"][name]["enabled"] = PRESETS[preset][name]
        base["preset"] = preset
    else:
        base["preset"] = "personnalise"

    raw_steps = raw.get("steps") or {}
    if isinstance(raw_steps, dict):
        for name in CONFIGURABLE_STEPS:
            step_raw = raw_steps.get(name)
            if isinstance(step_raw, dict) and "enabled" in step_raw:
                base["steps"][name]["enabled"] = bool(step_raw["enabled"])
            elif isinstance(step_raw, bool):
                base["steps"][name]["enabled"] = step_raw
        # Seuil de montant pour la 2e validation
        v2 = raw_steps.get("validation_2")
        if isinstance(v2, dict):
            seuil = _coerce_amount(v2.get("seuil_montant"))
            if seuil is not None:
                base["steps"]["validation_2"]["seuil_montant"] = seuil

    # Garde-fous
    for name in MANDATORY_STEPS:
        base["steps"][name]["enabled"] = True

    # Si la config ne correspond plus exactement à un preset, on le marque perso.
    if base["preset"] in PRESETS:
        current = {n: base["steps"][n]["enabled"] for n in CONFIGURABLE_STEPS}
        if current != PRESETS[base["preset"]] or "seuil_montant" in base["steps"]["validation_2"]:
            base["preset"] = "personnalise"

    return base


# Statut « en attente » associé à chaque étape (l'endroit où le dossier patiente
# tant que l'étape n'est pas faite) et statut final si plus aucune étape active.
STEP_ORDER = ("signature_service", "examen", "validation_1", "validation_2")
WAITING_STATUS = {
    "signature_service": "BROUILLON",
    "examen": "SIGNEE_SERVICE",
    "validation_1": "EN_ATTENTE",
    "validation_2": "AUTORISEE",
}
FINAL_STATUS = "APPROUVEE"


def first_active_waiting(
    config: dict[str, Any] | None,
    amount: float | None = None,
    after_step: str | None = None,
) -> str:
    """Statut où doit se trouver le dossier : le statut d'attente de la première
    étape ACTIVE après `after_step` (ou depuis le début si None). Si plus aucune
    étape n'est active, renvoie le statut final APPROUVEE.
    """
    cfg = normalize_config(config)
    started = after_step is None
    for step in STEP_ORDER:
        if not started:
            if step == after_step:
                started = True
            continue
        if step_enabled(cfg, step, amount):
            return WAITING_STATUS[step]
    return FINAL_STATUS


def step_enabled(config: dict[str, Any] | None, step: str, amount: float | None = None) -> bool:
    """Indique si une étape est active pour un montant donné.

    Pour `validation_2`, si un seuil est défini, l'étape n'est active que si le
    montant atteint/dépasse le seuil.
    """
    cfg = normalize_config(config)
    step_cfg = cfg["steps"].get(step)
    if not step_cfg or not step_cfg.get("enabled"):
        return False
    if step == "validation_2":
        seuil = step_cfg.get("seuil_montant")
        if seuil is not None and amount is not None and amount < seuil:
            return False
    return True
